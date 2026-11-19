"""四个进程共用的 HTTP 外壳：健康检查、统一日志、统一异常。"""

from __future__ import annotations

import os
import sys
import time
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台打中文不报错


def log(name: str, msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{name}] {msg}", flush=True)


def create_app(name: str, title: str, extra_health: Callable[[], dict] | None = None) -> FastAPI:
    app = FastAPI(title=title, version="1.0.0", docs_url="/docs")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        body = {
            "ok": True,
            "service": name,
            "pid": os.getpid(),
            "model": config.LLM_MODEL,
            "llm": config.has_llm(),
            "ts": time.time(),
        }
        if extra_health:
            try:
                body.update(extra_health())
            except Exception as exc:  # noqa: BLE001 - 健康检查自己不能挂
                body["extra_error"] = str(exc)
        return body

    @app.middleware("http")
    async def access_log(request: Request, call_next):  # noqa: ANN001
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - started) * 1000
            log(name, f"500 {request.method} {request.url.path} {ms:.0f}ms {type(exc).__name__}: {exc}")
            return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        ms = (time.perf_counter() - started) * 1000
        if request.url.path not in ("/health", "/favicon.ico"):
            log(name, f"{response.status_code} {request.method} {request.url.path} {ms:.0f}ms")
        return response

    return app


def serve(app: FastAPI, port: int, name: str, banner: str = "") -> None:
    import uvicorn

    print("=" * 68, flush=True)
    print(f"  {banner or name}   pid={os.getpid()}   port={port}", flush=True)
    print(f"  {config.summary()}", flush=True)
    print("=" * 68, flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
