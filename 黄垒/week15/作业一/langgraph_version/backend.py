"""后端进程（LangGraph 版）：接收前端输入，串联进程1 和 进程2。

    START
      │
   validate        清洗输入（去空白 / 截断超长）
      │
   recognize       调用进程1（HTTP）→ 情感标签
      │
      ├── 进程1 失败 ──────────────> degraded ──┐
      │                                          │
   comfort         调用进程2（HTTP）→ 回应正文    │
      │                                          │
      ├── 进程2 失败 ──────────────> degraded ──┤
      │                                          │
   assemble        汇总成 ChatResponse <─────────┘
      │
     END

降级分支是这个后端的重点：任何一个子进程挂掉，链路都要给用户一个「有回应」的结果，
而不是抛 500。降级时用词典 + 固定话术兜底，并把 degraded=True 标出来。

运行：
    python -m langgraph_version.backend                # 端口 8100
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from common import config, rules, service  # noqa: E402
from common import rpc  # noqa: E402
from common.protocol import ChatResponse, ReplyResult, SentimentResult, TraceStep  # noqa: E402

NAME = "后端-编排"
STATIC_DIR = Path(__file__).resolve().parents[1] / "common" / "static"


class State(TypedDict, total=False):
    text: str
    sentiment: dict[str, Any]
    reply: dict[str, Any]
    trace: list[dict[str, Any]]
    degraded: bool
    errors: list[str]
    started: float


def _step(state: State, stage: str, node: str, detail: str, ms: float) -> list[dict]:
    trace = list(state.get("trace") or [])
    trace.append({"stage": stage, "node": node, "detail": detail, "ms": int(ms)})
    return trace


def _strip_notes(data: dict) -> dict:
    """子进程内部的执行轨迹放到 trace 里展示，不塞进业务字段。"""
    return {k: v for k, v in data.items() if k != "notes"}


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def validate(state: State) -> dict:
    started = time.perf_counter()
    text = (state.get("text") or "").strip()
    clipped = text[: config.MAX_INPUT_CHARS]
    ms = (time.perf_counter() - started) * 1000
    detail = f"输入 {len(text)} 字" + ("（已截断）" if len(text) > len(clipped) else "")
    return {"text": clipped, "trace": _step(state, "后端", "validate", detail, ms)}


def recognize(state: State) -> dict:
    started = time.perf_counter()
    try:
        resp = rpc.post_json_with_retry(config.SENTIMENT_URL, "/analyze", {"text": state["text"]})
    except rpc.RpcError as exc:
        ms = (time.perf_counter() - started) * 1000
        service.log(NAME, f"进程1 调用失败：{exc}")
        return {
            "errors": list(state.get("errors") or []) + [f"进程1: {exc}"],
            "trace": _step(state, "后端", "recognize", f"进程1 不可用：{exc}", ms),
        }
    ms = (time.perf_counter() - started) * 1000
    data = resp.get("data") or {}
    sentiment = _strip_notes(data)
    notes = data.get("notes") or []
    detail = f'{sentiment.get("label")}/{sentiment.get("emotion")} 置信{sentiment.get("confidence")}'
    return {
        "sentiment": sentiment,
        "trace": _step(state, "进程1", "analyze", detail + (f"｜图内：{' → '.join(notes[-2:])}" if notes else ""), ms),
    }


def comfort(state: State) -> dict:
    started = time.perf_counter()
    try:
        resp = rpc.post_json_with_retry(
            config.REPLY_URL, "/respond", {"text": state["text"], "sentiment": state.get("sentiment") or {}}
        )
    except rpc.RpcError as exc:
        ms = (time.perf_counter() - started) * 1000
        service.log(NAME, f"进程2 调用失败：{exc}")
        return {
            "errors": list(state.get("errors") or []) + [f"进程2: {exc}"],
            "trace": _step(state, "后端", "comfort", f"进程2 不可用：{exc}", ms),
        }
    ms = (time.perf_counter() - started) * 1000
    data = resp.get("data") or {}
    reply = _strip_notes(data)
    notes = data.get("notes") or []
    detail = f'{reply.get("strategy")} {len(str(reply.get("reply") or ""))}字'
    return {
        "reply": reply,
        "trace": _step(state, "进程2", "respond", detail + (f"｜图内：{' → '.join(notes[-2:])}" if notes else ""), ms),
    }


def degraded(state: State) -> dict:
    """任一子进程失败：用规则补齐缺的那一半，保证前端一定拿到完整结果。"""
    started = time.perf_counter()
    sentiment = state.get("sentiment")
    reply = state.get("reply")
    detail: list[str] = []
    if not sentiment:
        sentiment = rules.rule_sentiment(state["text"]).model_dump()
        detail.append("规则识别情绪")
    if not reply:
        reply = rules.rule_reply(sentiment["label"], state["text"]).model_dump()
        detail.append("固定话术回应")
    ms = (time.perf_counter() - started) * 1000
    return {
        "sentiment": sentiment,
        "reply": reply,
        "degraded": True,
        "trace": _step(state, "后端", "degraded", "降级：".join([""]) + "、".join(detail), ms),
    }


def assemble(state: State) -> dict:
    started = time.perf_counter()
    total = (time.perf_counter() - float(state.get("started") or started)) * 1000
    ms = (time.perf_counter() - started) * 1000
    return {"trace": _step(state, "后端", "assemble", f"总耗时 {total:.0f}ms", ms)}


def route_after_recognize(state: State) -> str:
    return "comfort" if state.get("sentiment") else "degraded"


def route_after_comfort(state: State) -> str:
    return "assemble" if state.get("reply") else "degraded"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("validate", validate)
    graph.add_node("recognize", recognize)
    graph.add_node("comfort", comfort)
    graph.add_node("degraded", degraded)
    graph.add_node("assemble", assemble)

    graph.add_edge(START, "validate")
    graph.add_edge("validate", "recognize")
    graph.add_conditional_edges("recognize", route_after_recognize, {"comfort": "comfort", "degraded": "degraded"})
    graph.add_conditional_edges("comfort", route_after_comfort, {"assemble": "assemble", "degraded": "degraded"})
    graph.add_edge("degraded", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


GRAPH = build_graph()

NODE_LABEL = {
    "validate": ("后端", "校验输入"),
    "recognize": ("进程1", "情感识别"),
    "comfort": ("进程2", "情绪回应"),
    "degraded": ("后端", "降级兜底"),
    "assemble": ("后端", "汇总结果"),
}


def to_response(state: State, session_id: str) -> dict:
    payload = ChatResponse(
        session_id=session_id,
        text=state.get("text") or "",
        sentiment=SentimentResult.model_validate(state.get("sentiment") or {}),
        reply=ReplyResult.model_validate(state.get("reply") or {}),
        trace=[TraceStep(**step) for step in (state.get("trace") or [])],
        elapsed_ms=sum(int(s.get("ms") or 0) for s in (state.get("trace") or [])),
        degraded=bool(state.get("degraded")),
    )
    return payload.model_dump()


# --------------------------------------------------------------------------- #
# HTTP 外壳
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    text: str = ""
    session_id: str = "default"


app = service.create_app(NAME, "后端 · 串联进程1/进程2（LangGraph）")


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="输入不能为空")
    started = time.perf_counter()
    final_state = GRAPH.invoke({"text": req.text, "trace": [], "errors": [], "started": started, "degraded": False})
    return to_response(final_state, req.session_id)


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE：每跑完一个节点推一条事件，前端能看着链路一步步亮起来。"""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="输入不能为空")

    def events():
        started = time.perf_counter()
        init = {"text": req.text, "trace": [], "errors": [], "started": started, "degraded": False}
        yield _sse({"type": "stage", "stage": "前端", "detail": f"收到输入（{len(req.text)} 字），交给后端"})
        merged: dict = dict(init)
        for update in GRAPH.stream(init, stream_mode="updates"):
            for node, patch in update.items():
                if patch:
                    merged.update(patch)
                stage, label = NODE_LABEL.get(node, ("后端", node))
                detail = f"{label} {next((t['detail'] for t in reversed(patch.get('trace', [])) if t['node'] == node), '')}"
                yield _sse({"type": "stage", "stage": stage, "detail": detail.strip()})
        merged.setdefault("text", req.text)
        yield _sse({"type": "final", "data": to_response(merged, req.session_id)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(obj: dict) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


@app.get("/api/probe/sentiment")
def probe_sentiment() -> dict:
    ok = rpc.healthy(config.SENTIMENT_URL, timeout=1.5)
    return {"ok": ok, "url": config.SENTIMENT_URL}


@app.get("/api/meta")
def meta() -> dict:
    """给前端回填真实端口：端口是可以用环境变量改的，界面不该写死。"""
    return {
        "version": "langgraph",
        "backend_port": config.BACKEND_PORT,
        "sentiment_port": config.SENTIMENT_PORT,
        "reply_port": config.REPLY_PORT,
        "model": config.LLM_MODEL,
        "llm": config.has_llm(),
    }


@app.get("/api/probe/reply")
def probe_reply() -> dict:
    ok = rpc.healthy(config.REPLY_URL, timeout=1.5)
    return {"ok": ok, "url": config.REPLY_URL}


@app.get("/api/graph")
def graph_spec() -> dict:
    return {
        "mermaid": GRAPH.get_graph().draw_mermaid(),
        "sentiment": rpc.healthy(config.SENTIMENT_URL) and rpc.post_json(config.SENTIMENT_URL, "/graph", {})["mermaid"],
        "reply": rpc.healthy(config.REPLY_URL) and rpc.post_json(config.REPLY_URL, "/graph", {})["mermaid"],
    }


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="web")


if __name__ == "__main__":
    service.serve(app, config.BACKEND_PORT, NAME, "后端：串联进程1/进程2（LangGraph）")
