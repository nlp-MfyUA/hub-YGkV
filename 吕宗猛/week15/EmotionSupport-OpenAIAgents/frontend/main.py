"""情感陪伴 · OpenAI Agents 版「前端进程」。

职责：
1. 提供静态页面（frontend/web）。
2. 把 /api/* 请求反向代理到后端进程（默认 http://127.0.0.1:8623），浏览器只需要访问前端端口。

启动：
    cd frontend
    C:\\SoftWare\\miniconda3\\envs\\py312\\python.exe main.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


BACKEND_URL = _env("BACKEND_URL", "http://127.0.0.1:8623").rstrip("/")
HOST = _env("FRONTEND_HOST", "127.0.0.1")
PORT = int(_env("FRONTEND_PORT", "8613"))
WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="心屿 · OpenAI Agents 情感陪伴（前端）", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/model-config")
async def model_config_page() -> FileResponse:
    return FileResponse(WEB_DIR / "model-config.html")


@app.get("/api/model-config")
async def model_config() -> Response:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.get(BACKEND_URL + "/api/model-config")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": f"后端不可用：{type(exc).__name__}: {exc}"},
        )


@app.post("/api/model-config")
async def save_model_config(request: Request) -> Response:
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.post(
                BACKEND_URL + "/api/model-config",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": f"后端不可用：{type(exc).__name__}: {exc}"},
        )


@app.get("/api/health")
async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(BACKEND_URL + "/api/health")
            payload = response.json()
            payload["frontend"] = "ok"
            payload["backend_url"] = BACKEND_URL
            return payload
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "down",
            "role": "frontend",
            "backend_url": BACKEND_URL,
            "error": f"{type(exc).__name__}: {exc}",
        }


@app.get("/api/sessions")
async def sessions() -> Response:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            upstream = await client.get(BACKEND_URL + "/api/sessions")
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": f"后端不可用：{type(exc).__name__}: {exc}"},
        )


@app.get("/api/sessions/{session_id}/messages")
async def session_messages(session_id: str, request: Request) -> Response:
    query = request.url.query
    suffix = "?" + query if query else ""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.get(
                BACKEND_URL + "/api/sessions/" + session_id + "/messages" + suffix
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": f"后端不可用：{type(exc).__name__}: {exc}"},
        )


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            upstream = await client.post(
                BACKEND_URL + "/api/chat",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"detail": f"后端不可用：{type(exc).__name__}: {exc}"},
        )


@app.post("/api/chat/stream")
async def chat_stream(request: Request) -> StreamingResponse:
    body = await request.body()

    async def event_stream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    BACKEND_URL + "/api/chat/stream",
                    content=body,
                    headers={"Content-Type": "application/json"},
                ) as upstream:
                    if upstream.status_code != 200:
                        detail = (await upstream.aread()).decode("utf-8", "replace")
                        payload = {
                            "type": "error",
                            "message": f"后端返回 {upstream.status_code}：{detail[:300]}",
                        }
                        yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                        return
                    async for chunk in upstream.aiter_raw():
                        if chunk:
                            yield chunk
        except Exception as exc:  # noqa: BLE001
            payload = {
                "type": "error",
                "message": f"前端代理失败：{type(exc).__name__}: {exc}",
            }
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
    import socket

    import uvicorn

    def _port_in_use(host: str, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            return sock.connect_ex((host, port)) == 0

    if _port_in_use(HOST, PORT):
        print(f"[心屿/OpenAI-Agents-前端] 端口 {PORT} 已被占用。")
        raise SystemExit(2)

    print(f"[心屿/OpenAI-Agents-前端] 启动中：http://{HOST}:{PORT}/  ->  {BACKEND_URL}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
