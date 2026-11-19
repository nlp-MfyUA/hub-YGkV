"""情感陪伴 · OpenAI Agents 版「后端进程」。

只负责多 Agent 编排、会话存储与模型配置，不提供前端页面。
前端进程默认在 8613，本服务默认在 8623。

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
from agent_builders.title_agent import generate_title
from core import llm as llm_core
from pipeline import run_pipeline


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init_db()
    stored = storage.get_model_config()
    if stored:
        config.apply_model_config(
            stored["base_url"], stored["api_key"], stored["model_name"]
        )
        llm_core.reset()
    info = config.summary()
    mode = "离线演示" if info["mock_mode"] else "真实模型"
    print(
        f"[心屿/OpenAI Agents-后端] 启动：{info['host']}:{info['port']} / {mode} / "
        f"{info['models']} / 历史轮数 {info['history_rounds']} / DB {info['session_db']}"
    )
    yield


app = FastAPI(title="心屿 · OpenAI Agents 情感陪伴（后端）", version="1.0.0", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str = Field(default="", max_length=4000)
    session_id: str | None = None


class ModelConfigRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    api_key: str = Field(default="", max_length=500)
    model_name: str = Field(min_length=1, max_length=200)


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "role": "backend",
        **config.summary(),
        "model_configured": bool(storage.get_model_config()),
    }


@app.get("/api/model-config")
async def get_model_config() -> dict:
    stored = storage.get_model_config()
    return {
        "configured": bool(stored),
        "base_url": stored["base_url"] if stored else config.BASE_URL,
        "model_name": stored["model_name"] if stored else config.MODEL_NAME,
        "api_key_set": bool(stored and stored["api_key"]),
    }


@app.post("/api/model-config")
async def put_model_config(request: ModelConfigRequest) -> dict:
    base_url = (request.base_url or "").strip().rstrip("/")
    model_name = (request.model_name or "").strip()
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Base URL 必须以 http:// 或 https:// 开头")
    if not model_name:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    existing = storage.get_model_config() or {}
    api_key = (request.api_key or "").strip() or existing.get("api_key", "")
    storage.save_model_config(base_url, api_key, model_name)
    config.apply_model_config(base_url, api_key, model_name)
    llm_core.reset()
    return {
        "ok": True,
        "configured": True,
        "base_url": base_url,
        "model_name": model_name,
        "api_key_set": bool(api_key),
    }


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

    title = await generate_title(message)
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
        print(f"[心屿/OpenAI Agents-后端] 端口 {config.PORT} 已被占用。")
        raise SystemExit(2)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(f"[心屿/OpenAI Agents-后端] 启动中：http://{config.HOST}:{config.PORT}/")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_config=None, log_level="info")
