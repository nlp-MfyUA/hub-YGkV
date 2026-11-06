"""FastAPI 网页接口：浏览器 -> API -> LangGraph -> 只读 SQLite。

启动：
    python run_web.py                 # 离线 MockBrain
    python run_web.py --mode llm      # 使用 .env 里的真实模型

提供：
    GET  /                HTML 页面
    GET  /api/config      模式和限额
    GET  /api/health      服务状态
    POST /api/chat        JSON 结果（便于调试）
    POST /api/chat/stream SSE 节点进度和最终结果（前端实际使用）
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from brains import LLMBrain, MockBrain
from db_tools import SQLiteTools
from sql_graph import build_graph

LOG = logging.getLogger("sql_agent_web")
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_PREVIEW_ROWS = 40
MAX_QUESTION_LENGTH = 500
START_STATE = {"repair_count": 0, "trace": []}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)


class ChatResponse(BaseModel):
    question: str
    answer: str
    sql: str | None = None
    tables: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    shown_rows: int = 0
    preview_rows: int = 0
    truncated: bool = False
    repair_count: int = 0
    trace: list[str] = Field(default_factory=list)
    error: str | None = None
    success: bool = True


def selected_mode() -> Literal["mock", "llm"]:
    value = os.getenv("SQL_AGENT_MODE", "mock").lower().strip()
    if value not in ("mock", "llm"):
        raise ValueError("SQL_AGENT_MODE 必须是 mock 或 llm")
    return value  # type: ignore[return-value]


@lru_cache(maxsize=2)
def get_graph(mode: str):
    """一次创建数据库目录和 LangGraph，多个请求共享编译后的图定义。

    每一次 graph.invoke/stream 都有自己的 SQLState，因此不共享会话。
    """
    db = SQLiteTools(ROOT / "chinook.db")
    brain = MockBrain() if mode == "mock" else LLMBrain()
    return build_graph(db, brain, max_repairs=3)


def make_input(message: str) -> dict:
    question = message.strip()
    if not question:
        raise HTTPException(status_code=422, detail="请输入非空问题")
    return {"question": question, "repair_count": 0, "trace": []}


def to_response(state: dict) -> ChatResponse:
    shown = int(state.get("shown_rows", 0))
    rows = state.get("rows") or []
    preview = rows[:MAX_PREVIEW_ROWS]
    error = state.get("error") or None
    return ChatResponse(
        question=state.get("question", ""),
        answer=state.get("answer") or "Agent 没有返回回答。",
        sql=state.get("sql"),
        tables=state.get("tables", []),
        columns=state.get("columns", []),
        rows=preview,
        shown_rows=shown,
        preview_rows=len(preview),
        truncated=bool(state.get("truncated", False) or shown > len(preview)),
        repair_count=state.get("repair_count", 0),
        trace=state.get("trace", []),
        error=error,
        success=not bool(error),
    )


def sse(event_type: str, payload: dict) -> str:
    return (
        f"event: {event_type}\n"
        + "data: "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n\n"
    )


app = FastAPI(
    title="LangGraph SQL Chat",
    description="教学版聊天式 SQL Agent，提供只读 SQLite 查询。",
    version="1.0.0",
)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(
        STATIC / "index.html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/config")
def config():
    return {
        "mode": selected_mode(),
        "database": "Chinook / SQLite",
        "max_question_length": MAX_QUESTION_LENGTH,
        "max_preview_rows": MAX_PREVIEW_ROWS,
        "single_turn_only": True,
    }


@app.get("/api/health")
def health():
    return {"ok": True, "mode": selected_mode()}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """非流式：适合 Postman、curl 或查看 FastAPI /docs。"""
    state_input = make_input(req.message)
    try:
        graph = get_graph(selected_mode())
        result = graph.invoke(state_input, config={"recursion_limit": 40})
        return to_response(result)
    except Exception:
        LOG.exception("SQL Agent 运行失败")
        raise HTTPException(status_code=500, detail="Agent 执行失败，请查看后端终端日志")


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    """使用 Server-Sent Events (SSE) 实时发送节点进度；由 fetch POST 接收。"""
    state_input = make_input(req.message)

    # 在开始响应前创建图，这样配置/API Key 错误会返回常规 HTTP 500。
    try:
        graph = get_graph(selected_mode())
    except Exception:
        LOG.exception("SQL Agent 初始化失败")
        raise HTTPException(status_code=500, detail="Agent 初始化失败，请检查 .env 和服务端日志")

    def event_generator():
        printed = 0
        last_state = state_input

        try:
            yield sse("started", {"message": "已收到问题，开始执行 LangGraph"})
            for state in graph.stream(
                state_input,
                config={"recursion_limit": 40},
                stream_mode="values",
            ):
                last_state = state
                trace = state.get("trace", [])
                for line in trace[printed:]:
                    yield sse("progress", {"stage": line})
                printed = len(trace)

            yield sse("result", to_response(last_state).model_dump())
        except Exception:
            LOG.exception("流式 SQL Agent 运行失败")
            yield sse(
                "error",
                {"message": "Agent 执行失败，请查看后端终端日志"},
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
