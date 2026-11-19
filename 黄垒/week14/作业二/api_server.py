#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FastAPI 入口：网页 + 上传 + 状态轮询 + 多模态问答（SSE）。

不是「上传完就地解析」，而是：
  上传 → 落盘 → 发 Kafka → 立刻返回 doc_id（前端拿到 PENDING）
  worker 异步消费 → 状态从 PENDING → PARSING → DONE
上传接口因此只做三件事：存盘、算哈希去重、投递消息，响应时间与 PDF 大小无关。
"""

import json
import logging
import os
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List

import httpx
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import bus
import config
import db
import indexer
import llm
import rag

log = logging.getLogger("api")

app = FastAPI(title="多模态 RAG · Kafka 解析流水线", version="1.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")
app.mount("/ask_images", StaticFiles(directory=str(config.ASK_IMG_DIR)), name="ask_images")


@app.on_event("startup")
def _startup() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                        datefmt="%H:%M:%S")
    for noisy in ("kafka", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    db.init_database()
    try:
        indexer.ensure_index()
    except Exception as e:                                  # noqa: BLE001
        log.warning("ES 索引检查失败（不影响启动）：%s", e)
    try:
        bus.ensure_topics()
    except Exception as e:                                  # noqa: BLE001
        log.warning("Kafka topic 检查失败（不影响启动）：%s", e)
    log.info("服务已就绪 http://%s:%s", config.HOST, config.PORT)


# ---------------------------------------------------------------- 工具
def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    return v


def _doc_view(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": d["id"],
        "filename": d["filename"],
        "size_bytes": d["size_bytes"],
        "status": d["status"],
        "pages": d["pages"],
        "n_chunks": d["n_chunks"],
        "n_images": d["n_images"],
        "attempts": d["attempts"],
        "parse_seconds": d["parse_seconds"],
        "engine": d["engine"],
        "error": d["error"],
        "created_at": _jsonable(d["created_at"]),
        "finished_at": _jsonable(d["finished_at"]),
    }


def _sse(payload: Dict[str, Any]) -> str:
    return "data: " + json.dumps(_jsonable(payload), ensure_ascii=False) + "\n\n"


# ---------------------------------------------------------------- 页面
@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------------------------------------------------------------- 文档
@app.post("/api/docs")
async def upload_docs(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """多文件上传。每个文件独立去重、独立投递，单个失败不影响其它。"""
    if not files:
        raise HTTPException(400, "没有收到文件")
    items: List[Dict[str, Any]] = []
    for uf in files:
        name = os.path.basename(uf.filename or "unnamed.pdf")
        if not name.lower().endswith(".pdf"):
            items.append({"filename": name, "ok": False, "error": "只接受 .pdf 文件"})
            continue
        tmp = config.UPLOAD_DIR / f".incoming-{uuid.uuid4().hex}.pdf"
        size = 0
        try:
            with open(tmp, "wb") as out:
                while True:
                    block = await uf.read(1 << 20)
                    if not block:
                        break
                    size += len(block)
                    out.write(block)
            if size == 0:
                raise ValueError("空文件")
            sha = db.sha256_of(str(tmp))
            existing = db.find_by_sha(sha)
            if existing:
                tmp.unlink(missing_ok=True)
                items.append({"filename": name, "ok": True, "duplicated": True,
                              "doc_id": existing["id"], "status": existing["status"],
                              "message": "内容已存在，复用已解析结果"})
                continue
            doc_id = db.new_doc_id(sha)
            target = config.UPLOAD_DIR / f"{doc_id}.pdf"
            os.replace(tmp, target)
            db.create_document(doc_id, name, size, sha, str(target))
            md = bus.publish_parse(doc_id, name, str(target))
            bus.publish_status(doc_id, db.STATUS_PENDING, filename=name, size=size)
            items.append({"filename": name, "ok": True, "duplicated": False,
                          "doc_id": doc_id, "status": db.STATUS_PENDING,
                          "size_bytes": size, "kafka": md})
            log.info("已接收 %s → doc_id=%s P%s@%s", name, doc_id,
                     md["partition"], md["offset"])
        except Exception as e:                              # noqa: BLE001
            tmp.unlink(missing_ok=True)
            items.append({"filename": name, "ok": False, "error": f"{type(e).__name__}: {e}"})
    return {"items": items}


@app.get("/api/docs")
def list_docs() -> Dict[str, Any]:
    docs = [_doc_view(d) for d in db.list_documents()]
    return {"items": docs, "stats": db.stats()}


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str) -> Dict[str, Any]:
    d = db.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    return _doc_view(d)


@app.get("/api/docs/{doc_id}/chunks")
def get_chunks(doc_id: str, limit: int = 200) -> Dict[str, Any]:
    d = db.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    rows = db.chunks_of_doc(doc_id, limit)
    return {"doc": _doc_view(d), "items": [
        {"id": r["id"], "idx": r["idx"], "kind": r["kind"], "section": r["section"],
         "page": (r["page"] + 1) if r["page"] is not None else None,
         "text": (r["text"] or "")[:1200],
         "image_url": f"/media/{r['image_path']}" if r["image_path"] else None,
         "n_chars": r["n_chars"]}
        for r in rows]}


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str) -> Dict[str, Any]:
    d = db.get_document(doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    db.delete_document(doc_id)
    try:
        indexer.delete_doc(doc_id)
    except Exception as e:                                  # noqa: BLE001
        log.warning("删除 ES 数据失败：%s", e)
    for p in (config.MEDIA_DIR / doc_id, config.WORK_DIR / doc_id):
        if p.exists():
            import shutil
            shutil.rmtree(p, ignore_errors=True)
    Path(d["file_path"]).unlink(missing_ok=True)
    bus.publish_status(doc_id, "DELETED", filename=d["filename"])
    return {"ok": True, "doc_id": doc_id}


# ---------------------------------------------------------------- 图问
@app.post("/api/ask_image")
async def upload_ask_image(file: UploadFile = File(...)) -> Dict[str, Any]:
    """用户提问时顺带上传的图片（独立于文档库，只用于这一次提问）。"""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        raise HTTPException(400, "只接受 png/jpg/webp/bmp/gif")
    name = f"ask-{uuid.uuid4().hex[:12]}{ext}"
    target = config.ASK_IMG_DIR / name
    with open(target, "wb") as out:
        while True:
            block = await file.read(1 << 20)
            if not block:
                break
            out.write(block)
    return {"ok": True, "image_id": name, "url": f"/ask_images/{name}",
            "size_bytes": target.stat().st_size}


# ---------------------------------------------------------------- 问答
def _resolve_ask_images(ids: List[str]) -> List[Path]:
    out: List[Path] = []
    for i in ids:
        name = os.path.basename(i)
        p = config.ASK_IMG_DIR / name
        if p.exists():
            out.append(p)
    return out


def _qa_stream(question: str, image_ids: List[str], doc_ids: List[str],
               top_k: int) -> Iterator[str]:
    """同步生成器 —— Starlette 会把它放到线程池里迭代，不阻塞事件循环。"""
    t0 = time.time()
    try:
        yield _sse({"type": "start", "question": question,
                    "ts": _jsonable(datetime.now())})

        evidence = rag.retrieve(question, top_k=top_k, doc_ids=doc_ids or None)
        if not evidence:
            msg = ("没有检索到相关资料。请先在左侧上传 PDF，等状态变成「解析完成」再提问；"
                   "也可以换一种说法。")
            yield _sse({"type": "delta", "text": msg})
            yield _sse({"type": "final", "ok": True, "answer": msg, "evidence": [],
                        "images": [], "elapsed": round(time.time() - t0, 2),
                        "note": "no-evidence"})
            return

        ask_images = _resolve_ask_images(image_ids)
        messages, used_images = rag.build_messages(question, evidence, ask_images)
        public_ev = rag.public_evidence(evidence)
        yield _sse({"type": "retrieved", "evidence": public_ev,
                    "images": used_images,
                    "elapsed": round(time.time() - t0, 2)})

        answer, think, usage = [], [], None
        for ev in llm.stream_chat(messages):
            if ev["type"] == "delta":
                answer.append(ev["text"])
                yield _sse({"type": "delta", "text": ev["text"]})
            elif ev["type"] == "think":
                think.append(ev["text"])
                yield _sse({"type": "think", "text": ev["text"]})
            elif ev["type"] == "usage":
                usage = ev["usage"]

        text = "".join(answer).strip()
        if not text:
            text = "（模型没有返回内容，可能是上下文过长或服务异常）"
        yield _sse({"type": "final", "ok": True, "answer": text,
                    "evidence": public_ev, "images": used_images,
                    "cited": rag.cited_ids(text, len(public_ev)),
                    "usage": usage, "elapsed": round(time.time() - t0, 2),
                    "thinking": "".join(think)[:2000]})
    except Exception as e:                                  # noqa: BLE001
        log.exception("问答失败")
        yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}",
                    "elapsed": round(time.time() - t0, 2)})


@app.post("/api/qa")
def qa(payload: Dict[str, Any] = Body(...)) -> StreamingResponse:
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    if len(question) > 500:
        raise HTTPException(400, "问题请控制在 500 字以内")
    image_ids = payload.get("image_ids") or []
    doc_ids = [d for d in (payload.get("doc_ids") or []) if isinstance(d, str)][:20]
    top_k = int(payload.get("top_k") or config.TOP_K)
    top_k = max(1, min(top_k, 12))
    return StreamingResponse(
        _qa_stream(question, image_ids, doc_ids, top_k),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


@app.post("/api/qa/sync")
def qa_sync(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """非流式版本，给 smoke_test / 脚本用。"""
    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    t0 = time.time()
    evidence = rag.retrieve(question, top_k=int(payload.get("top_k") or config.TOP_K),
                            doc_ids=payload.get("doc_ids") or None)
    if not evidence:
        return {"ok": True, "answer": "没有检索到相关资料。", "evidence": [],
                "elapsed": round(time.time() - t0, 2)}
    messages, used = rag.build_messages(question, evidence,
                                        _resolve_ask_images(payload.get("image_ids") or []))
    answer = "".join(e["text"] for e in llm.stream_chat(messages) if e["type"] == "delta")
    return {"ok": True, "answer": answer.strip(), "images": used,
            "evidence": rag.public_evidence(evidence),
            "elapsed": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- 观测
@app.get("/api/health")
def health() -> Dict[str, Any]:
    k = bus.health()
    lag = []
    if k.get("ok"):
        try:
            lag = bus.lag_snapshot(config.CONSUMER_GROUP)
        except Exception:                                   # noqa: BLE001
            lag = []
    mineru: Dict[str, Any] = {"ok": False}
    if config.MINERU_REMOTE_URL:
        try:
            with httpx.Client(timeout=3.0, trust_env=False) as c:
                r = c.get(f"{config.MINERU_REMOTE_URL}/v1/health")
            mineru = {"ok": r.status_code == 200,
                      "url": config.MINERU_REMOTE_URL,
                      "detail": r.json() if r.status_code == 200 else r.text[:200]}
        except Exception as e:                              # noqa: BLE001
            mineru = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    else:
        mineru = {"ok": True, "mode": "local-process"}
    db_ok = True
    db_stats: Dict[str, Any] = {}
    try:
        db_stats = db.stats()
    except Exception as e:                                  # noqa: BLE001
        db_ok = False
        db_stats = {"error": str(e)}
    return {
        "ok": True,
        "kafka": {"ok": k.get("ok"), "bootstrap": config.KAFKA_BOOTSTRAP,
                  "topics": k.get("topics"), "lag": lag,
                  "consumer_group": config.CONSUMER_GROUP},
        "es": indexer.health(),
        "mysql": {"ok": db_ok, **db_stats},
        "mineru": mineru,
        "llm": llm.health(),
        "config": {"topic_parse": config.TOPIC_PARSE, "topic_status": config.TOPIC_STATUS,
                   "topic_dlq": config.TOPIC_DLQ, "top_k": config.TOP_K,
                   "image_max_side": config.IMAGE_MAX_SIDE,
                   "max_images_to_llm": config.MAX_IMAGES_TO_LLM,
                   "mineru_tier": config.MINERU_TIER},
        "ts": _jsonable(datetime.now()),
    }


@app.post("/api/reindex")
def reindex() -> Dict[str, Any]:
    """用 MySQL 里的分块重建 ES 索引（换 mapping / 换分词器时用）。"""
    indexer.reset_index()
    rows = db.all_chunks_for_reindex()
    by_doc: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], {"filename": r["filename"], "chunks": []})
        by_doc[r["doc_id"]]["chunks"].append(r)
    total = 0
    for doc_id, pack in by_doc.items():
        total += indexer.index_chunks(doc_id, pack["filename"], pack["chunks"])
    return {"ok": True, "docs": len(by_doc), "chunks": total}


@app.exception_handler(Exception)
async def _unhandled(request, exc):                        # noqa: ARG001
    log.exception("未处理异常")
    return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status_code=500)


def main() -> None:
    import uvicorn
    uvicorn.run("api_server:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":
    main()
