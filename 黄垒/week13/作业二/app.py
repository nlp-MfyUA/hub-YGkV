"""
作业二：给作业一的 LangGraph SQL Agent 配一个网页前端。

后端只做三件事：
    1. 托管 static/ 下的页面；
    2. 把浏览器发来的问题交给 LangGraph 图执行；
    3. 用 SSE 把「表选择 / SQL 生成 / 校验 / 改写 / 执行 / 汇总」的每一步实时推给前端。

运行：
    cd week13/作业二
    pip install -r requirements.txt
    copy .env.example .env   # 填入 LLM_API_KEY
    python app.py            # http://127.0.0.1:8000

接口：
    GET  /                  页面
    GET  /api/health        健康检查（模型 / 表数量 / 启动错误）
    POST /api/chat          一次性返回完整结果（调试 / 命令行测试）
    POST /api/chat/stream   流式返回执行过程（前端使用）
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
AGENT_DIR = BASE_DIR.parent / "作业一"
STATIC_DIR = BASE_DIR / "static"

# 先加载本目录的 .env，再加载作业一的 .env（不覆盖已有值）
load_dotenv(BASE_DIR / ".env")
load_dotenv(AGENT_DIR / ".env")
load_dotenv()

# 复用作业一的 LangGraph 实现
sys.path.insert(0, str(AGENT_DIR))

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from sql_graph import SQLAgentGraph, final_payload, node_event  # noqa: E402

_db_from_env = os.environ.get("DB_PATH")
DB_PATH = Path(_db_from_env) if _db_from_env else AGENT_DIR / "chinook.db"
if not DB_PATH.is_absolute():
    # DB_PATH 按作业二目录解析，避免从其它工作目录启动时找不到数据库
    DB_PATH = (BASE_DIR / DB_PATH).resolve()

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "4"))

STARTUP_ERROR: str | None = None
try:
    AGENT: SQLAgentGraph | None = SQLAgentGraph(
        DB_PATH,
        inject_bad_sql=os.environ.get("INJECT_BAD_SQL", "0") == "1",
    )
except Exception as exc:  # 缺 Key / 数据库不存在时，服务仍然能起来并给出提示
    AGENT = None
    STARTUP_ERROR = str(exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    if AGENT is not None:
        AGENT.close()


app = FastAPI(
    title="Chinook ChatBI",
    description="LangGraph SQL Agent + 网页对话前端",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 同一个会话串行执行（LangGraph 的 thread 状态不能被并发写）；全局限制并发数
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_GUARD = asyncio.Lock()
_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENCY)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    session_id: str = Field(
        default="web-default",
        min_length=4,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )


def sse(payload: dict[str, Any]) -> str:
    """打包成一条 SSE 消息（前端用 fetch + ReadableStream 解析）。"""
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _session_lock(session_id: str) -> asyncio.Lock:
    async with _LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id, asyncio.Lock())


def _require_agent() -> SQLAgentGraph:
    if AGENT is None:
        raise HTTPException(
            status_code=503,
            detail=STARTUP_ERROR or "SQL Agent 未初始化",
        )
    return AGENT


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    agent = AGENT
    return {
        "ok": agent is not None,
        "error": STARTUP_ERROR,
        "framework": "LangGraph",
        "model": agent.model_name if agent else os.environ.get("LLM_MODEL", "deepseek-chat"),
        "db": DB_PATH.name,
        "tables": len(agent.parser.table_names) if agent else 0,
        "fields": (
            sum(len(v) for v in agent.parser._table_fields.values()) if agent else 0
        ),
        "foreign_keys": len(agent.parser.foreign_keys) if agent else 0,
    }


@app.post("/api/chat")
async def chat(req: ChatRequest) -> dict[str, Any]:
    """非流式接口：一次返回最终结果 + 各阶段耗时（便于 curl / 自动化测试）。"""
    agent = _require_agent()
    message = req.message.strip()
    lock = await _session_lock(req.session_id)

    async with lock:
        async with _SEMAPHORE:
            result = await asyncio.to_thread(agent.run, message, req.session_id, False)

    return {
        "ok": result.ok,
        "answer": result.answer,
        "sql": result.sql,
        "tables": result.tables,
        "table_reason": result.table_reason,
        "columns": result.columns,
        "rows": result.rows,
        "truncated": result.truncated,
        "error": result.error,
        "attempts": result.attempts,
        "stages": [
            {"name": stage.name, "elapsed": round(stage.elapsed, 3), "detail": stage.detail}
            for stage in result.stages
        ],
    }


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """流式接口：每完成一个 LangGraph 节点就推一条 SSE 事件。"""
    agent = _require_agent()
    message = req.message.strip()
    session_id = req.session_id
    lock = await _session_lock(session_id)

    async def event_stream():
        if lock.locked():
            yield sse(
                {
                    "type": "error",
                    "message": "当前会话还在处理上一条问题，请稍候再发。",
                }
            )
            return

        async with lock:
            async with _SEMAPHORE:
                config = {"configurable": {"thread_id": session_id}}
                started = time.perf_counter()
                last = started

                yield sse(
                    {
                        "type": "start",
                        "message": message,
                        "session_id": session_id,
                        "db": DB_PATH.name,
                    }
                )

                try:
                    async for update in agent.graph.astream(
                        {"question": message},
                        config,
                        stream_mode="updates",
                    ):
                        now = time.perf_counter()
                        elapsed = now - last
                        last = now

                        for node, delta in update.items():
                            if node == "prepare":
                                continue
                            event = node_event(node, delta, elapsed)
                            event["session_id"] = session_id
                            yield sse(event)

                    state = (await agent.graph.aget_state(config)).values
                    payload = final_payload(state)
                    payload["elapsed"] = round(time.perf_counter() - started, 3)
                    payload["session_id"] = session_id
                    yield sse(payload)
                except Exception as exc:  # 图执行异常 / 模型异常
                    yield sse(
                        {
                            "type": "error",
                            "message": f"执行失败：{exc}",
                            "session_id": session_id,
                        }
                    )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    # 直接传 app 对象，避免 uvicorn 再 import 一次模块、重复创建 Agent
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )
