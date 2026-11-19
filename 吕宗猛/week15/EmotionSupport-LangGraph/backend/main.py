"""情感陪伴 · LangGraph 版「后端进程」。

只负责多 Agent 编排与会话存储，不提供前端页面。前端进程默认在 8612，本服务默认在 8622。

启动：
    cd backend
    C:\\SoftWare\\miniconda3\\envs\\py312\\python.exe main.py
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import config
import storage
from agents.title_agent import TitleAgent
from pipeline import run_pipeline


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init_db()
    info = config.summary()
    mode = "离线演示" if info["mock_mode"] else "真实模型"
    print(
        f"[心屿/LangGraph-后端] 启动：{info['host']}:{info['port']} / {mode} / "
        f"{info['models']} / 历史轮数 {info['history_rounds']} / DB {info['session_db']}"
    )
    yield


_TITLE_AGENT = TitleAgent()
app = FastAPI(title="心屿 · LangGraph 情感陪伴（后端）", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    session_id: str | None = None


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "role": "backend", **config.summary()}


@app.get("/api/sessions")
async def list_sessions() -> dict:
    return {"sessions": storage.list_sessions()}


@app.get("/api/sessions/{session_id}/messages")
async def session_messages(
    session_id: str,
    limit: int = Query(default=5, ge=1, le=50),
    before_id: int | None = Query(default=None),
) -> dict:
    session = storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    page = storage.get_message_page(session_id, limit=limit, before_id=before_id)
    return {"session": session, **page}


async def _prepare_turn(message: str, session_id: str | None) -> tuple[dict, list[dict], bool]:
    """准备会话与最近 5 轮上下文；新会话会先生成标题。"""
    if session_id:
        session = storage.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        history = storage.get_recent_messages(session_id, config.MAX_HISTORY_ROUNDS)
        return session, history, False

    title = await _TITLE_AGENT.generate(message)
    session = storage.create_session(title)
    return session, [], True


def _message_meta(event: dict) -> dict:
    return {
        "emotion": event.get("emotion", {}),
        "agent": event.get("agent", ""),
        "agent_name": event.get("agent_name", ""),
    }


@app.post("/api/chat")
async def chat(request: ChatRequest) -> dict:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    session, history, is_new = await _prepare_turn(message, request.session_id)
    storage.add_message(session["id"], "user", message)
    session = storage.get_session(session["id"]) or session

    result: dict = {}
    async for event in run_pipeline(message, history):
        if event["type"] == "done":
            assistant = storage.add_message(
                session["id"], "assistant", event.get("reply", ""), _message_meta(event)
            )
            event["session_id"] = session["id"]
            event["assistant_message_id"] = assistant["id"]
            result = event
    if not result:
        raise HTTPException(status_code=500, detail="流程未产生结果")
    return {"session": storage.get_session(session["id"]) or session, "is_new": is_new, **result}


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    message = (request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息不能为空")

    session, history, is_new = await _prepare_turn(message, request.session_id)
    storage.add_message(session["id"], "user", message)
    session = storage.get_session(session["id"]) or session

    async def event_stream():
        yield "data: " + json.dumps(
            {"type": "session", "session": session, "is_new": is_new},
            ensure_ascii=False,
        ) + "\n\n"
        try:
            async for event in run_pipeline(message, history):
                if event["type"] == "done":
                    assistant = storage.add_message(
                        session["id"], "assistant", event.get("reply", ""), _message_meta(event)
                    )
                    event["session_id"] = session["id"]
                    event["assistant_message_id"] = assistant["id"]
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
        except Exception as exc:  # noqa: BLE001 - 保证前端一定收到结束信号
            payload = {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
            yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import logging
    import socket

    import uvicorn

    def _port_in_use(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            return sock.connect_ex((host, port)) == 0

    if _port_in_use(config.HOST, config.PORT):
        print(f"[心屿/LangGraph-后端] 端口 {config.PORT} 已被占用。")
        raise SystemExit(2)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(f"[心屿/LangGraph-后端] 启动中：http://{config.HOST}:{config.PORT}/")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_config=None, log_level="info")
