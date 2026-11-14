#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行冒烟测试：不开浏览器把整条链路跑一遍。

覆盖：健康检查 → 多文件上传 → Kafka 异步解析轮询 → 分块查询 → 流式问答
      → 非流式问答 → 图问（用户上传图片 + 资料图一起送模型）

用法：
  python3 smoke_test.py                 # 用 /workspace/pdf 下的样例 PDF
  python3 smoke_test.py a.pdf b.pdf     # 指定文件
"""

import io
import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8080"
DEFAULT_PDFS = ["/workspace/pdf/test2.pdf", "/workspace/pdf/test.pdf"]
QUESTIONS = [
    "文档里介绍了哪五种问答范式？分别适用于什么场景？",
    "表格问答支持哪些问法？请结合文档里的表格说明。",
    "FAQ 匹配式问答的流程图说明了什么？",
]

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✔' if cond else '✘'} {name}{'' if not detail else '  ' + detail}")


def main() -> int:
    pdfs = sys.argv[1:] or DEFAULT_PDFS
    pdfs = [p for p in pdfs if Path(p).exists()]
    if not pdfs:
        print("没有可用的样例 PDF")
        return 1
    cli = httpx.Client(base_url=BASE, timeout=180.0, trust_env=False)

    print("\n[1] 健康检查")
    h = cli.get("/api/health").json()
    ok("Kafka 可用", h["kafka"]["ok"])
    ok("Elasticsearch 可用", h["es"]["ok"])
    ok("MySQL 可用", h["mysql"]["ok"])
    ok("MinerU 可用", bool(h["mineru"].get("ok")))
    ok("vLLM 可用", bool(h["llm"].get("ok")), str(h["llm"].get("models")))
    print(f"     topics={h['kafka'].get('topics')}")

    print("\n[2] 多文件上传（multipart）")
    files = []
    handles = []
    for p in pdfs:
        fh = open(p, "rb")
        handles.append(fh)
        files.append(("files", (Path(p).name, fh, "application/pdf")))
    r = cli.post("/api/docs", files=files)
    for fh in handles:
        fh.close()
    data = r.json()
    submitted = [i for i in data["items"] if i.get("ok")]
    ok("上传被接受", r.status_code == 200 and len(submitted) == len(pdfs),
       f"{len(submitted)}/{len(pdfs)} 个")
    for it in data["items"]:
        mark = "重复" if it.get("duplicated") else it.get("status")
        kafka = it.get("kafka")
        print(f"     {it['filename']:<24} doc_id={it.get('doc_id')} 状态={mark}"
              + (f"  P{kafka['partition']}@{kafka['offset']}" if kafka else ""))

    print("\n[3] 轮询解析状态（Kafka → worker → MinerU）")
    want = [i["doc_id"] for i in submitted]
    deadline = time.time() + 420
    last = {}
    while time.time() < deadline:
        docs = {d["doc_id"]: d for d in cli.get("/api/docs").json()["items"]}
        states = {k: docs[k]["status"] for k in want if k in docs}
        if states != last:
            print("     " + "  ".join(f"{k[:10]}={v}" for k, v in states.items()))
            last = states
        if all(v in ("DONE", "FAILED") for v in states.values()):
            break
        time.sleep(2)
    ok("全部解析完成", all(v == "DONE" for v in last.values()), str(last))

    doc_id = want[0]
    doc = next(d for d in cli.get("/api/docs").json()["items"] if d["doc_id"] == doc_id)
    print(f"     {doc['filename']}: {doc['pages']} 页 / {doc['n_chunks']} 块 / "
          f"{doc['n_images']} 图 / {doc['parse_seconds']}s")

    print("\n[4] 分块查询")
    ch = cli.get(f"/api/docs/{doc_id}/chunks?limit=200").json()
    kinds = {}
    for c in ch["items"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    ok("有文本块", kinds.get("text", 0) > 0, str(kinds))
    ok("有图片块且带图注", kinds.get("image", 0) > 0,
       f"image={kinds.get('image', 0)}")
    img_chunk = next((c for c in ch["items"] if c["image_url"]), None)
    ok("图片可访问", bool(img_chunk) and
       cli.get(img_chunk["image_url"]).status_code == 200)

    print("\n[5] 非流式问答")
    q = QUESTIONS[0]
    r = cli.post("/api/qa/sync", json={"question": q}).json()
    ok("返回答案", bool(r.get("answer")), f"{len(r.get('answer', ''))} 字")
    ok("命中证据", len(r.get("evidence") or []) > 0, f"{len(r.get('evidence') or [])} 条")
    print("     问：" + q)
    print("     答：" + (r.get("answer") or "").replace("\n", "\n         ")[:600])

    print("\n[6] 流式问答（SSE）")
    deltas, final, ev_retrieved = 0, None, 0
    with cli.stream("POST", "/api/qa", json={"question": QUESTIONS[1]}) as resp:
        ok("Content-Type 是 event-stream",
           "text/event-stream" in resp.headers.get("content-type", ""))
        buf = ""
        for text in resp.iter_text():
            buf += text
            while "\n\n" in buf:
                chunk, buf = buf.split("\n\n", 1)
                line = next((l for l in chunk.split("\n") if l.startswith("data:")), None)
                if not line:
                    continue
                evt = json.loads(line[5:].strip())
                if evt["type"] == "delta":
                    deltas += 1
                elif evt["type"] == "retrieved":
                    ev_retrieved = len(evt.get("evidence") or [])
                elif evt["type"] == "final":
                    final = evt
    ok("收到递增 delta", deltas > 5, f"{deltas} 个分片")
    ok("收到 retrieved 事件", ev_retrieved > 0, f"{ev_retrieved} 条证据")
    ok("收到 final 事件", final is not None,
       f"{len(final.get('answer', '')) if final else 0} 字 / "
       f"{final.get('elapsed') if final else '-'}s")
    if final:
        imgs = [e for e in final.get("evidence") or [] if e.get("image_url")]
        ok("证据里含图片（图文混排的数据源）", len(imgs) > 0, f"{len(imgs)} 张")

    print("\n[7] 图问：用户上传一张图 + 文档图一起送模型")
    # 直接拿解析出来的图片当作「用户上传的图」，避免依赖外部素材
    raw = cli.get(img_chunk["image_url"]).content if img_chunk else b""
    up = cli.post("/api/ask_image",
                  files={"file": ("probe.png", io.BytesIO(raw), "image/png")}).json()
    ok("图片上传成功", bool(up.get("image_id")), up.get("url", ""))
    r2 = cli.post("/api/qa/sync", json={
        "question": "我上传的这张图，和文档里的流程图讲的是同一件事吗？请对比说明。",
        "image_ids": [up["image_id"]],
    }).json()
    used = [u for u in (r2.get("images") or []) if u.get("kind") == "user"]
    ok("用户图进入 prompt", len(used) == 1, str([u["source"] for u in r2.get("images") or []]))
    print("     答：" + (r2.get("answer") or "").replace("\n", "\n         ")[:500])

    print("\n[8] 限定文档范围检索")
    r3 = cli.post("/api/qa/sync", json={"question": QUESTIONS[0], "doc_ids": [doc_id]}).json()
    ok("指定 doc_ids 可检索", len(r3.get("evidence") or []) > 0)

    print("\n" + "=" * 62)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 62)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
