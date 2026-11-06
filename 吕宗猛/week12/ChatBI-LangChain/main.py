"""ChatBI 服务入口：页面 + SSE 流式问答接口。

启动：
    C:\\SoftWare\\miniconda3\\envs\\py312\\python.exe main.py
或：
    uvicorn main:app --port 8611
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
from core import schema as schema_mod
from pipeline import run_pipeline

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 预热：启动即解析数据库结构，首问不再等待
    try:
        info = schema_mod.get_schema()
        print(
            f"[ChatBI] schema ready: {info.table_count} tables / "
            f"{info.column_count} columns / {info.foreign_key_count} fks "
            f"({info.build_ms:.0f} ms)"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ChatBI] schema warmup failed: {exc}")
    yield


app = FastAPI(title="ChatBI", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


class ChatRequest(BaseModel):
    question: str = Field(default="", max_length=2000)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    payload = config.summary()
    try:
        info = schema_mod.get_schema()
        data_range = ""
        for table_name, _column, low, high in info.temporal:
            if table_name == "invoices":
                data_range = f"发票 {str(low)[:10]} ~ {str(high)[:10]}"
                break
        payload["schema"] = {
            "table_count": info.table_count,
            "column_count": info.column_count,
            "foreign_key_count": info.foreign_key_count,
            "build_ms": round(info.build_ms, 1),
            "data_range": data_range,
        }
    except Exception as exc:  # noqa: BLE001
        payload["schema_error"] = str(exc)
    return payload


@app.get("/api/schema")
async def schema() -> dict:
    try:
        return schema_mod.get_schema().as_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    async def event_stream():
        try:
            async for event in run_pipeline(question):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 保证前端一定收到结束信号
            payload = {
                "type": "error",
                "payload": {"stage": "server", "message": f"{type(exc).__name__}: {exc}"},
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

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
        print(f"[ChatBI] 端口 {config.PORT} 已被占用，可能服务已经在运行。")
        print(f"         直接访问：http://{config.HOST}:{config.PORT}/")
        print("         如需重启：先结束占用该端口的进程，或修改 .env 里的 PORT。")
        raise SystemExit(2)

    # 不用 uvicorn 自带的彩色日志配置：Windows 控制台会把 ANSI 颜色码显示成乱码
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print(f"[ChatBI] 启动中：http://{config.HOST}:{config.PORT}/")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_config=None, log_level="info")
