"""Application tests with parser/model/Kafka test doubles, not service E2E tests."""
import asyncio
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

TEST_DIR = tempfile.TemporaryDirectory(prefix="rag-test-", dir=Path(__file__).parent,
                                       ignore_cleanup_errors=True)
os.environ["DATA_DIR"] = TEST_DIR.name
import app as m


def png():
    out = io.BytesIO()
    Image.new("RGB", (12, 8), "teal").save(out, format="PNG")
    return out.getvalue()


class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        m.init_db()
        with m.db() as c:
            for name in ("documents", "chunks", "outbox"):
                c.execute(f"DELETE FROM {name}")
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=m.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def upload(self):
        r = await self.client.post("/documents", files=[("files", ("a.pdf", b"%PDF-fixture", "application/pdf"))])
        self.assertEqual(r.status_code, 202)
        doc_id = r.json()["document_ids"][0]
        with m.db() as c:
            row = c.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return {"doc_id": doc_id, "event_id": row["event_id"]}

    def content_file(self, items):
        folder = m.ROOT / "work" / m.uid()
        (folder / "images").mkdir(parents=True)
        (folder / "images" / "figure.png").write_bytes(png())
        file = folder / "test_content_list.json"
        file.write_text(json.dumps(items), encoding="utf-8")
        return file

    async def model_stub(self, path, payload):
        if path == "/embeddings":
            return {"data": [{"embedding": [1.0, 2.0, 0.5]}]}
        return {"choices": [{"message": {"content": "图片显示系统架构及模块关系。"}}]}

    def test_split_and_math_boundaries(self):
        for n in range(0, 2500):
            text = "x" * n
            chunks = m.split_text(text)
            self.assertTrue(all(0 < len(c) <= 900 for c in chunks))
            if chunks:
                reconstructed = chunks[0] + "".join(c[150:] for c in chunks[1:])
                self.assertEqual(reconstructed, text)
        for v in ([1, 0], [3, 4], [-2, 7, 3]):
            u = m.unit(v)
            self.assertAlmostEqual(sum(x*x for x in u), 1)
            self.assertAlmostEqual(m.cosine(u, u), 1)
            self.assertAlmostEqual(m.cosine(u, [-x for x in u]), -1)
        for v in ([], [0, 0], [float("nan")], [float("inf")]):
            with self.assertRaises(ValueError):
                m.unit(v)
        with self.assertRaises(ValueError):
            m.cosine([1], [1, 0])
        with self.assertRaises(ValueError):
            m.split_text("test", 10, 10)

    async def test_upload_batch_atomic_and_limits(self):
        r = await self.client.post("/documents", files=[
            ("files", ("good.pdf", b"%PDF-test")), ("files", ("bad.pdf", b"not pdf"))])
        self.assertEqual(r.status_code, 400)
        self.assertEqual((await self.client.get("/documents")).json(), [])
        self.assertEqual((await self.client.post("/documents", files=[
            ("files", ("x.pdf", b"%PDF-test")) for _ in range(11)])).status_code, 400)
        with patch.object(m, "MAX_PDF", 8):
            self.assertEqual((await self.client.post("/documents", files={
                "files": ("large.pdf", b"%PDF-1234")})).status_code, 400)
        r = await self.client.post("/documents", files=[
            ("files", ("a.pdf", b"%PDF-a")), ("files", ("b.pdf", b"%PDF-b"))])
        self.assertEqual(r.status_code, 202)
        with m.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM outbox WHERE sent=0").fetchone()[0], 2)

    async def test_middle_json_conversion(self):
        """MinerU middle.json（docvortex 2.0：pages/blocks/content）能转成检索块。"""
        folder = m.ROOT / "work" / m.uid()
        images = folder / "images"
        images.mkdir(parents=True)
        (images / "p0.png").write_bytes(png())
        doc = {"pages": [
            {"page_idx": 0, "blocks": [
                {"type": "paragraph_title", "content": [{"type": "text", "content": "第一章"}]},
                {"type": "text", "content": [{"type": "text", "content": "正文内容"}]},
                {"type": "table", "content": [{"type": "table_body", "content": "<table><tr><td>甲</td></tr></table>"}]},
            ]},
            {"page_idx": 1, "blocks": [
                {"type": "image", "content": [{"type": "image_body", "image_path": "images/p0.png", "content": ""}]},
            ]},
        ]}
        file = folder / "middle.json"
        file.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with patch.object(m, "model", side_effect=self.model_stub):
            chunks = await m.build_chunks("doc", file, "middle")
        self.assertEqual([c[2] for c in chunks], [1, 1, 1, 2])
        self.assertIn("</table>", chunks[2][3])
        self.assertTrue(chunks[3][4].endswith(".jpg"))

    async def test_processing_ready_and_duplicate(self):
        event = await self.upload()
        file = self.content_file([
            {"type": "text", "text": "Kafka传递解析任务", "page_idx": 0},
            {"type": "image", "img_path": "images/figure.png", "image_caption": ["系统架构"], "page_idx": 1}])
        parse = AsyncMock(return_value=file)
        with patch.object(m, "run_mineru", parse), patch.object(m, "model", side_effect=self.model_stub):
            await m.process_event(event)
            await m.process_event(event)
        self.assertEqual(parse.await_count, 1)
        docs = (await self.client.get("/documents")).json()
        self.assertEqual(docs[0]["status"], "ready")
        with m.db() as c:
            rows = c.execute("SELECT * FROM chunks ORDER BY page").fetchall()
        self.assertEqual([r["page"] for r in rows], [1, 2])
        self.assertTrue(rows[1]["image"])
        self.assertEqual((await self.client.get("/media/" + rows[1]["image"])).status_code, 200)

    async def test_failure_retry_and_stale_event(self):
        old = await self.upload()
        with patch.object(m, "run_mineru", AsyncMock(side_effect=RuntimeError("parser failed"))):
            await m.process_event(old)
        self.assertEqual((await self.client.get("/documents")).json()[0]["status"], "failed")
        r = await self.client.post(f"/documents/{old['doc_id']}/retry")
        self.assertEqual(r.status_code, 202)
        with m.db() as c:
            current = c.execute("SELECT * FROM documents").fetchone()
        parse = AsyncMock(return_value=self.content_file([{"text": "retry succeeded"}]))
        with patch.object(m, "run_mineru", parse), patch.object(m, "model", side_effect=self.model_stub):
            await m.process_event(old)
            self.assertEqual(parse.await_count, 0)
            await m.process_event({"doc_id": old["doc_id"], "event_id": current["event_id"]})
        self.assertEqual((await self.client.get("/documents")).json()[0]["status"], "ready")
        self.assertEqual((await self.client.post(f"/documents/{old['doc_id']}/retry")).status_code, 409)

    async def test_empty_and_traversal_content(self):
        with patch.object(m, "model", side_effect=self.model_stub):
            with self.assertRaises(ValueError):
                await m.build_chunks("test", self.content_file([]))
            file = self.content_file([{"img_path": "../../outside.png"}])
            with self.assertRaises(ValueError):
                await m.build_chunks("test", file)

    async def test_subprocess_contract_and_cancellation(self):
        # Windows 不能直接执行带 shebang 的脚本；MINERU_BIN 指向 .py 时 app.py 会用
        # 当前解释器运行它，这样同一份测试在 Windows / Linux 都可用。
        fake = m.ROOT / "fake_mineru.py"
        fake.write_text('''import argparse,json,pathlib
p=argparse.ArgumentParser()
p.add_argument('path', nargs='*', default=[])
for name in ['-o','--pages','--wait','--tier','-p']: p.add_argument(name)
a=p.parse_args()
out=pathlib.Path(a.o)/'fixture'/'auto'
out.mkdir(parents=True,exist_ok=True)
(out/'fixture_content_list.json').write_text(json.dumps([{'text':'parsed'}]))
print('parser fixture completed')
''')
        with patch.dict(os.environ, {"MINERU_BIN": str(fake)}):
            file, _kind = await m.run_mineru(m.uid(), m.uid())
            self.assertEqual(json.loads(file.read_text()), [{"text": "parsed"}])
        fake.write_text("import time\ntime.sleep(100)\n")
        with patch.dict(os.environ, {"MINERU_BIN": str(fake)}):
            with self.assertRaises(TimeoutError):
                async with asyncio.timeout(.15):
                    await m.run_mineru(m.uid(), m.uid())

    async def test_processing_state_visible_and_index_transaction_rollback(self):
        event = await self.upload()
        old = (m.uid(), event["doc_id"], 1, "old index", "", "[1,0]")
        with m.db() as c:
            c.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)", old)
        async def parse(doc_id, event_id):
            self.assertEqual((await self.client.get("/documents")).json()[0]["status"], "processing")
            return self.content_file([{"text": "new index"}]), "content_list"
        duplicate_id = m.uid()
        chunk = (duplicate_id, event["doc_id"], 1, "new index", "", "[1,0]")
        with patch.object(m, "run_mineru", side_effect=parse), patch.object(m, "build_chunks", return_value=[chunk, chunk]):
            await m.process_event(event)
        with m.db() as c:
            rows = c.execute("SELECT text FROM chunks").fetchall()
            self.assertEqual([r["text"] for r in rows], ["old index"])
        self.assertEqual((await self.client.get("/documents")).json()[0]["status"], "failed")

    async def test_input_boundaries(self):
        self.assertEqual((await self.client.post("/chat", data={"question": "  "})).status_code, 400)
        self.assertEqual((await self.client.post("/chat", data={"question": "a" * 4001})).status_code, 400)
        self.assertEqual((await self.client.post("/chat", data={"question": "hello"})).status_code, 409)
        r = await self.client.post("/chat", data={"question": "hello"}, files={"image": ("x.png", b"invalid")})
        self.assertEqual(r.status_code, 400)
        self.assertEqual((await self.client.get("/documents/missing/pdf")).status_code, 404)
        with self.assertRaises((ValueError, OSError)):
            m.image_bytes(b"<svg></svg>")

    async def test_chat_sends_both_images_and_resolves_only_real_sources(self):
        event = await self.upload()
        image_name = m.uid() + ".jpg"
        (m.ROOT / "media" / image_name).write_bytes(m.image_bytes(png()))
        with m.db() as c:
            c.execute("UPDATE documents SET status='ready'")
            c.execute("INSERT INTO chunks VALUES(?,?,?,?,?,?)",
                      (m.uid(), event["doc_id"], 3, "architecture", image_name, json.dumps(m.unit([1, 2, .5]))))
        calls = []
        async def fake_model(path, payload):
            calls.append((path, payload))
            if path == "/embeddings":
                return {"data": [{"embedding": [1, 2, .5]}]}
            images = [x for x in payload["messages"][0]["content"] if x["type"] == "image_url"]
            text = "描述图片"
            if len(images) == 2:
                text = json.dumps({"blocks": [
                    {"type": "text", "text": "说明[S1] <script>"},
                    {"type": "image", "source_id": "S1"},
                    {"type": "image", "source_id": "invented", "url": "https://bad.test/x"}]})
            return {"choices": [{"message": {"content": text}}]}
        with patch.object(m, "model", side_effect=fake_model):
            r = await self.client.post("/chat", data={"question": "这张图和文档有什么关系？"},
                                       files={"image": ("query.png", png(), "image/png")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([b["type"] for b in r.json()["blocks"]], ["text", "image"])
        self.assertEqual(r.json()["sources"]["S1"]["page"], 3)
        images = [b for b in calls[-1][1]["messages"][0]["content"] if b["type"] == "image_url"]
        self.assertEqual(len(images), 2)
        for image in images:
            self.assertTrue(image["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        with patch.object(m, "model", side_effect=self.model_stub):
            r = await self.client.post("/chat", data={"question": "bad model JSON"})
        self.assertEqual(r.status_code, 502)

    async def test_outbox_send_then_mark(self):
        await self.upload()
        sent = asyncio.Event()
        class Producer:
            async def start(self): pass
            async def stop(self): pass
            async def send_and_wait(self, topic, value, key):
                self.outer.assertEqual(topic, m.TOPIC)
                self.outer.assertEqual(json.loads(value)["doc_id"].encode(), key)
                sent.set()
        producer = Producer()
        producer.outer = self
        with patch.object(m, "AIOKafkaProducer", return_value=producer):
            task = asyncio.create_task(m.dispatch())
            await asyncio.wait_for(sent.wait(), timeout=2)
            with m.db() as c:
                self.assertEqual(c.execute("SELECT sent FROM outbox").fetchone()[0], 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_worker_commits_only_after_processing(self):
        order = []
        message = type("Message", (), {"topic": m.TOPIC, "partition": 0, "offset": 4,
                                       "value": json.dumps({"doc_id": "d", "event_id": "e"}).encode()})()
        class Consumer:
            async def start(self): pass
            async def stop(self): order.append("stop")
            def __aiter__(self): return self
            async def __anext__(self):
                if hasattr(self, "used"): raise StopAsyncIteration
                self.used = True
                return message
            async def commit(self, offset):
                self.offset = offset
                order.append("commit")
        async def process(event): order.append("processed")
        consumer = Consumer()
        with patch.object(m, "AIOKafkaConsumer", return_value=consumer), patch.object(m, "process_event", side_effect=process):
            await m.worker()
        self.assertEqual(order, ["processed", "commit", "stop"])
        self.assertEqual(consumer.offset[m.TopicPartition(m.TOPIC, 0)], 5)
        order.clear()
        consumer = Consumer()
        with patch.object(m, "AIOKafkaConsumer", return_value=consumer), patch.object(m, "process_event", side_effect=RuntimeError("DB unavailable")):
            with self.assertRaises(RuntimeError): await m.worker()
        self.assertEqual(order, ["stop"])


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        TEST_DIR.cleanup()
