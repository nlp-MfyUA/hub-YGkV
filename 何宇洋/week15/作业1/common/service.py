"""同一服务入口按 role 启动不同 OS 进程；通过 HTTP 传递 Pydantic 协议。"""
import argparse
import importlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from common.llm import create_client
from common.models import ChatResult, Reply, ReplyInput, Sentiment, UserInput

log = logging.getLogger(__name__)


def create_app(role: str, framework: str) -> FastAPI:
    package = "langgraph_app" if framework == "langgraph" else "agents_app"

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=150.0, trust_env=False) as http:
            app.state.http = http
            if role in ("sentiment", "response"):
                client = create_client()
                app.state.engine = importlib.import_module(f"{package}.engine").Engine(client)
                try:
                    yield
                finally:
                    await client.close()
            else:
                yield

    app = FastAPI(title=f"{framework} / {role}", lifespan=lifespan)

    async def rpc(target, path, body=None):
        defaults = {"backend": 8001, "sentiment": 8002, "response": 8003}
        url = os.getenv(f"{target.upper()}_URL", f"http://127.0.0.1:{defaults[target]}")
        try:
            if body is None:
                result = await app.state.http.get(url + path)
            else:
                result = await app.state.http.post(url + path, json=body)
            result.raise_for_status()
            value = result.json()
            schema = {"/classify": Sentiment, "/respond": Reply, "/api/chat": ChatResult}.get(path)
            return schema.model_validate(value).model_dump() if schema else value
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "处理超时，请稍后重试") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"{target} 服务不可用或返回无效结果，请检查服务日志") from exc

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        # 不输出上游响应体、请求头、SDK 异常全文，避免凭证泄露。
        log.error("request failed: %s", type(exc).__name__)
        if isinstance(exc, APITimeoutError):
            return JSONResponse(status_code=504, content={"detail": "模型请求超时"})
        if isinstance(exc, (APIConnectionError, APIStatusError, ValidationError)):
            return JSONResponse(status_code=502, content={"detail": "模型调用失败或输出格式无效，请检查模型配置、额度及网络"})
        return JSONResponse(status_code=500, content={"detail": "处理失败，请检查服务日志"})

    @app.get("/health")
    async def health():
        # 只检查进程及依赖服务，不调用付费模型接口。
        targets = {"frontend": ["backend"], "backend": ["sentiment", "response"]}.get(role, [])
        for target in targets:
            await rpc(target, "/health")
        return {"status": "ok", "role": role, "framework": framework}

    if role == "frontend":
        @app.get("/", response_class=HTMLResponse)
        async def index():
            return Path(__file__).with_name("index.html").read_text(encoding="utf-8").replace("{{framework}}", framework)

        @app.post("/api/chat", response_model=ChatResult)
        async def proxy(data: UserInput):
            return await rpc("backend", "/api/chat", data.model_dump())

    elif role == "backend":
        pipeline = importlib.import_module(f"{package}.workflow").run_pipeline

        @app.post("/api/chat", response_model=ChatResult)
        async def chat(data: UserInput):
            result = await pipeline(data.text, rpc)
            return ChatResult(framework=framework, **result)

    elif role == "sentiment":
        @app.post("/classify", response_model=Sentiment)
        async def classify(data: UserInput):
            return await app.state.engine.classify(data.text)

    elif role == "response":
        @app.post("/respond", response_model=Reply)
        async def respond(data: ReplyInput):
            return await app.state.engine.respond(data)

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["frontend", "backend", "sentiment", "response"], required=True)
    parser.add_argument("--framework", choices=["langgraph", "openai-agents"], default="openai-agents")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    uvicorn.run(create_app(args.role, args.framework), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
