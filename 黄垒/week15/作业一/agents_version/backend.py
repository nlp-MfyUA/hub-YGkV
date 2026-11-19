"""后端进程（openai-agents 版）：接收前端输入，串联进程1 和 进程2。

    POST /api/chat
        validate  → 清洗输入
        recognize → HTTP 调进程1（进程1 内部是 Runner.run + 工具）
        comfort   → HTTP 调进程2（进程2 内部是 Triage + handoff）
        assemble  → 汇总 trace 返回

为什么这一层不再套一个 Agent：
「先识别、再回应」是确定性的顺序，交给模型决定只会引入不确定性和额外 2~4 秒延迟。
Agents SDK 的价值在进程1/进程2 内部（工具、护栏、handoff），
后端的职责是**编排 + 兜底**，所以这里用显式的 async 流水线，
每一步失败都能精确降级，而不是让整条链路一起 500。

运行：
    python -m agents_version.backend                    # 端口 8100
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common import config, rules, service  # noqa: E402
from common import rpc  # noqa: E402
from common.protocol import ChatResponse, ReplyResult, SentimentResult, TraceStep  # noqa: E402

NAME = "后端-编排"
STATIC_DIR = Path(__file__).resolve().parents[1] / "common" / "static"


def _strip_notes(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "notes"}


class ChatRequest(BaseModel):
    text: str = ""
    session_id: str = "default"


async def pipeline(text: str) -> AsyncIterator[dict]:
    """四步流水线，边跑边吐事件。最后一条是 final。"""
    started = time.perf_counter()
    trace: list[dict] = []
    degraded = False
    errors: list[str] = []

    def step(stage: str, node: str, detail: str, ms: float) -> None:
        trace.append({"stage": stage, "node": node, "detail": detail, "ms": int(ms)})

    # 1) 清洗
    t0 = time.perf_counter()
    clean = text.strip()[: config.MAX_INPUT_CHARS]
    note = f"输入 {len(text)} 字" + ("（已截断）" if len(clean) < len(text.strip()) else "")
    step("后端", "validate", note, (time.perf_counter() - t0) * 1000)
    yield {"type": "stage", "stage": "后端", "detail": f"校验输入 {note}"}

    # 2) 进程1
    sentiment: dict = {}
    t0 = time.perf_counter()
    try:
        resp = await rpc.post_json_async_with_retry(config.SENTIMENT_URL, "/analyze", {"text": clean})
        raw = resp.get("data") or {}
        sentiment = _strip_notes(raw)
        detail = f'{sentiment.get("label")}/{sentiment.get("emotion")} 置信{sentiment.get("confidence")}'
        step("进程1", "analyze", detail, (time.perf_counter() - t0) * 1000)
        yield {"type": "stage", "stage": "进程1", "detail": f"情感识别 {detail}"}
    except rpc.RpcError as exc:
        step("后端", "recognize", f"进程1 不可用：{exc}", (time.perf_counter() - t0) * 1000)
        errors.append(f"进程1: {exc}")
        yield {"type": "stage", "stage": "后端", "detail": f"进程1 不可用，转降级（{exc}）"}

    # 3) 进程2
    reply: dict = {}
    if sentiment:
        t0 = time.perf_counter()
        try:
            resp = await rpc.post_json_async_with_retry(
                config.REPLY_URL, "/respond", {"text": clean, "sentiment": sentiment}
            )
            raw = resp.get("data") or {}
            reply = _strip_notes(raw)
            detail = f'{reply.get("strategy")} {len(str(reply.get("reply") or ""))}字'
            step("进程2", "respond", detail, (time.perf_counter() - t0) * 1000)
            yield {"type": "stage", "stage": "进程2", "detail": f"情绪回应 {detail}"}
        except rpc.RpcError as exc:
            step("后端", "comfort", f"进程2 不可用：{exc}", (time.perf_counter() - t0) * 1000)
            errors.append(f"进程2: {exc}")
            yield {"type": "stage", "stage": "后端", "detail": f"进程2 不可用，转降级（{exc}）"}

    # 4) 降级兜底
    if not sentiment or not reply:
        t0 = time.perf_counter()
        fixed = []
        if not sentiment:
            sentiment = rules.rule_sentiment(clean).model_dump()
            fixed.append("规则识别情绪")
        if not reply:
            reply = rules.rule_reply(sentiment["label"], clean).model_dump()
            fixed.append("固定话术回应")
        degraded = True
        step("后端", "degraded", "、".join(fixed), (time.perf_counter() - t0) * 1000)
        yield {"type": "stage", "stage": "后端", "detail": f"降级兜底：{'、'.join(fixed)}"}

    step("后端", "assemble", f"总耗时 {(time.perf_counter() - started) * 1000:.0f}ms", 0)
    payload = ChatResponse(
        session_id="",
        text=clean,
        sentiment=SentimentResult.model_validate(sentiment),
        reply=ReplyResult.model_validate(reply),
        trace=[TraceStep(**s) for s in trace],
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        degraded=degraded,
    ).model_dump()
    yield {"type": "final", "data": payload}


app = service.create_app(NAME, "后端 · 串联进程1/进程2（openai-agents）")


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="输入不能为空")
    final: dict = {}
    async for event in pipeline(req.text):
        if event["type"] == "final":
            final = event["data"]
    final["session_id"] = req.session_id
    return final


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="输入不能为空")

    async def events():
        yield _sse({"type": "stage", "stage": "前端", "detail": f"收到输入（{len(req.text)} 字），交给后端"})
        session_id = req.session_id
        async for event in pipeline(req.text):
            if event["type"] == "final":
                event["data"]["session_id"] = session_id
            yield _sse(event)
            await asyncio.sleep(0)     # 让出事件循环，SSE 才能真的一条条推

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


@app.get("/api/probe/sentiment")
async def probe_sentiment() -> dict:
    return {"ok": rpc.healthy(config.SENTIMENT_URL, timeout=1.5), "url": config.SENTIMENT_URL}


@app.get("/api/meta")
async def meta() -> dict:
    """给前端回填真实端口：端口是可以用环境变量改的，界面不该写死。"""
    return {
        "version": "openai-agents",
        "backend_port": config.BACKEND_PORT,
        "sentiment_port": config.SENTIMENT_PORT,
        "reply_port": config.REPLY_PORT,
        "model": config.LLM_MODEL,
        "llm": config.has_llm(),
    }


@app.get("/api/probe/reply")
async def probe_reply() -> dict:
    return {"ok": rpc.healthy(config.REPLY_URL, timeout=1.5), "url": config.REPLY_URL}


@app.get("/api/agents")
async def agents_spec() -> dict:
    """转发两个子进程的 Agent 组成，前端/文档可以直接看。"""
    out: dict = {}
    for name, url in (("sentiment", config.SENTIMENT_URL), ("reply", config.REPLY_URL)):
        try:
            out[name] = rpc.post_json(url, "/agents", {})
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)}
    return out


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="web")


if __name__ == "__main__":
    service.serve(app, config.BACKEND_PORT, NAME, "后端：串联进程1/进程2（openai-agents）")
