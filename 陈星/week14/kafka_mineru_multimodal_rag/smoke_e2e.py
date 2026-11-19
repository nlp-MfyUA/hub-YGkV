"""端到端冒烟测试：真实的 Kafka 消息流转 + 解析 worker 进程，MinerU 和模型服务用离线替身。

用途：在没有 GPU / parse-server / API Key 的环境里，验证“上传 → Kafka → worker → 解析 → 索引 → 问答”
整条链路能跑通。MinerU 用 fake_mineru.py 模拟（输出同格式的 Markdown），模型用本地假接口
（回答里标注“模拟回答”）。MinerU 的真实解析效果见 docs/截图说明.md。

运行前提：
    本机有 Kafka（默认 127.0.0.1:19092，可用 KAFKA_BOOTSTRAP_SERVERS 指定）
    python smoke_e2e.py                     # 使用 sample/ 下的示例 PDF
"""
import asyncio
import io
import json
import logging
import os
import subprocess
import http.server
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

CODE_DIR = Path(__file__).resolve().parent
HERE = CODE_DIR
DATA = Path(tempfile.mkdtemp(prefix="rag-e2e-"))
os.environ["DATA_DIR"] = str(DATA)
os.environ["KAFKA_BOOTSTRAP_SERVERS"] = os.getenv("KAFKA_BOOTSTRAP_SERVERS") or "127.0.0.1:19092"
os.environ["MODEL_API_KEY"] = "smoke-key"
os.environ["KAFKA_GROUP_ID"] = "pdf-parser-smoke-" + uuid.uuid4().hex[:8]
os.environ["REDIS_URL"] = ""  # 冒烟时走内存兜底，不依赖本机 Redis

import app as m  # noqa: E402
logging.basicConfig(level=logging.INFO)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # 避免终端编码让日志写入抛错

# 请求体编码与终端无关：按 UTF-8 / GBK 依次尝试解码
def _decode(raw):
    for codec in ("utf-8", "gbk", "latin-1"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")

BASE = "http://test"


def fake_model():
    """最小的 OpenAI 兼容服务：/embeddings 用字符哈希向量，/chat/completions 回可解析 JSON。

    注意：替身只服务 smoke_e2e，目的是验证链路（文件 → Kafka → MinerU → 索引 → 问答）
    是否打通，不代表真实模型效果。真实效果见 docs/真机验证记录.md。
    """

    def text_reply():
        return json.dumps({"blocks": [
            {"type": "text", "text": "根据文档，这里是模拟回答。[S1]"},
            {"type": "text", "text": "以上内容来自检索到的原文片段。"},
        ]}, ensure_ascii=False)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(_decode(request.content))
        if request.url.path.endswith("/embeddings"):
            vec = [0.0] * 64
            for i, ch in enumerate(body["input"]):
                vec[(ord(ch) + i) % 64] += 1.0
            return httpx.Response(200, json={"data": [{"embedding": vec}]})
        content = body["messages"][-1]["content"]
        if isinstance(content, list):
            prompt = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            has_images = any(c.get("type") == "image_url" for c in content)
            text = text_reply() if "返回纯JSON" in prompt else (
                "图片中包含文字、图表与结构关系。" if has_images else "模拟回答")
        else:
            text = "模拟回答"
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return httpx.MockTransport(handler)


_RealClient = httpx.AsyncClient
ASGI = {}


class RouteTransport(httpx.AsyncBaseTransport):
    """本进程内的 httpx：发到 http://test 的（测试客户端自己的请求）交给应用，
    其余（app 里对模型服务的调用）交给替身。"""

    async def handle_async_request(self, request):
        if request.url.host == "test":
            # 测试客户端已经走了 ASGITransport，这里的 http://test 请求只会来自其它客户端
            async with httpx.AsyncClient(transport=ASGI["transport"]) as client:
                return await client.send(request)
        return await fake_model().handle_async_request(request)


def install_fake_model(app):
    """让 app 模块里的 httpx.AsyncClient 使用 RouteTransport（模型调用走替身）。"""
    real = httpx.AsyncClient

    class RoutingClient(real):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = RouteTransport()
            super().__init__(*args, **kwargs)

    m.httpx.AsyncClient = RoutingClient


def make_handler():
    """把替身模型包成本机 HTTP 服务，供 worker 线程里的 embed / vision 调用。"""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # /media/<file>：返回一张示例图片（对应解析结果里的图片定位符）
            if self.path.startswith("/media/"):
                payload = (HERE / "sample" / "question.png").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            self.send_response(404)
            self.end_headers()

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            request = httpx.Request("POST", "http://mock" + self.path, content=self.rfile.read(length))
            response = fake_model().handle_request(request)
            payload = response.content
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    return Handler


def _check_dispatch_error():
    loop = asyncio.get_running_loop()
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]

    def report(task):
        if not task.cancelled() and task.exception() and task.get_coro().__qualname__.startswith("dispatch"):
            print("DISPATCH TASK FAILED:", repr(task.exception()))
    for t in tasks:
        t.add_done_callback(report)


async def main(pdf: Path):
    ASGI["transport"] = httpx.ASGITransport(app=m.app)
    install_fake_model(m.app)
    # 测试客户端不会触发 ASGI lifespan，这里手动启动和 app 相同的启动流程
    m.init_db()
    dispatcher = asyncio.create_task(m.dispatch())
    m.app.state.dispatcher = dispatcher
    _check_dispatch_error()
    m.init_db()
    print(f"数据目录：{DATA}")
    client = _RealClient(transport=httpx.ASGITransport(app=m.app), base_url=BASE)

    # 1. 上传（此时没有 worker，应停留在待解析）
    with pdf.open("rb") as fh:
        r = await client.post("/documents", files=[("files", (pdf.name, fh.read(), "application/pdf"))])
    r.raise_for_status()
    doc_id = r.json()["document_ids"][0]
    t0 = time.time()
    print("上传完成 doc_id =", doc_id, "状态 =", (await client.get("/documents")).json()[0]["status"])

    # 2. 启动解析 worker：走真实的 Kafka 消费与解析流程；MinerU 与模型服务用离线替身，
    #    这样不需要 GPU / parse-server / API Key 也能验证“上传 → Kafka → worker → 索引 → 问答”。
    #    替身模型服务监听本机端口，worker 里的 embed / vision 通过 MODEL_BASE_URL 调它。
    served = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler())
    threading.Thread(target=served.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{served.server_address[1]}"
    env = {**os.environ, "PYTHONUTF8": "1", "KAFKA_GROUP_ID": m.GROUP, "DATA_DIR": str(DATA),
           "MODEL_BASE_URL": endpoint, "MODEL_API_KEY": "smoke-key",
           "MINERU_BIN": str(HERE / "fake_mineru.py"), "MINERU_SUBCOMMAND": "",
           "MINERU_FETCH_BASE": endpoint}
    env = {k: v for k, v in env.items() if v is not None}
    worker = subprocess.Popen([sys.executable, str(HERE / "app.py"), "worker"], cwd=HERE, env=env,
                              stdout=open(DATA / "worker.log", "wb"), stderr=subprocess.STDOUT)
    try:
        status, last = None, time.time()
        while time.time() - t0 < 300:
            docs = (await client.get("/documents")).json()
            status = docs[0]["status"]
            if status != last:
                print(f"  [{time.time() - t0:6.1f}s] 状态 → {status} {docs[0].get('error') or ''}")
                last = status
            if status in {"ready", "failed"}:
                break
            await asyncio.sleep(2)
        assert status == "ready", f"解析未完成：{status}（worker 日志见 {DATA / 'worker.log'}）"
        print(f"解析耗时 {time.time() - t0:.1f}s")

        # 3. 问答
        r = await client.post("/chat", data={"question": "文档里讲了什么？", "session_id": "smoke-1"})
        r.raise_for_status()
        result = r.json()
        print("回答块数：", len(result["blocks"]), " 来源：",
              [(k, v["name"], v["page"]) for k, v in result["sources"].items()])
        for b in result["blocks"]:
            print("   ", b)

        # 4. 图片提问
        img = (HERE / "sample" / "question.png").read_bytes()
        if img:
            r = await client.post("/chat", data={"question": "这张图与文档有什么关系？"},
                                  files={"image": ("q.png", img, "image/png")})
            r.raise_for_status()
            print("图文提问：", r.json()["blocks"][0])
        print("会话历史条数：", len(m.history.get("smoke-1")))
        print("SMOKE PASSED")
    finally:
        served.shutdown()
        dispatcher.cancel()
        worker.terminate()
        try:
            worker.wait(20)
        except subprocess.TimeoutExpired:
            worker.kill()
        await client.aclose()


if __name__ == "__main__":
    pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "sample" / "示例研究流程.pdf"
    asyncio.run(main(pdf))
