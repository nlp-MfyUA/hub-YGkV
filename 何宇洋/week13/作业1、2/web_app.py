"""本地 SQL 对话网页。默认使用 deepseek-flash，--demo 启用离线演示。"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from demo_sql_model import EXAMPLES, demo_model
from sql_agent_core import MODEL_NAME
from sql_agent_langgraph import LangGraphSQLAgent, WorkflowError

ROOT = Path(__file__).resolve().parent


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=8)

    @field_validator("question")
    @classmethod
    def require_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


def contextual_question(request: ChatRequest) -> str:
    if not request.history:
        return request.question
    history = "\n".join(
        f"{'用户' if turn.role == 'user' else '助手'}：{turn.content}"
        for turn in request.history
    )
    return ("请结合以下历史对话理解当前问题；历史只提供语境，数据请重新查询数据库。\n"
            f"<history>\n{history}\n</history>\n\n当前问题：{request.question}")


def create_app(*, live: bool = True, db_path: str | Path = ROOT / "chinook.db",
               agent_factory: Callable[[], Any] | None = None) -> FastAPI:
    app = FastAPI(title="Chinook SQL 对话")
    app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(ROOT / "web" / "index.html")

    @app.get("/api/config")
    def config():
        return {"mode": "live" if live else "demo", "examples": list(EXAMPLES),
                "model": MODEL_NAME if live else None,
                "api_key_configured": bool((os.getenv("DEEPSEEK_API_KEY") or "").strip()) if live else False}

    @app.post("/api/chat")
    def chat(request: ChatRequest):
        # 每个请求独立创建 agent，避免表授权、状态或结果在用户间共享。
        if live and agent_factory is None and not (os.getenv("DEEPSEEK_API_KEY") or "").strip():
            raise HTTPException(503, "服务端尚未配置 DEEPSEEK_API_KEY，请配置后重新查询。")
        try:
            if agent_factory is not None:
                agent = agent_factory()
            elif live:
                agent = LangGraphSQLAgent(db_path)
            else:
                agent = LangGraphSQLAgent(db_path, model=demo_model(request.question))
            result = agent.run(contextual_question(request) if live else request.question)
            return {**result, "question": request.question, "mode": "live" if live else "demo"}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except WorkflowError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            # 不向浏览器输出上游异常全文，以免暴露服务端配置或凭据。
            logging.warning("SQL 查询失败：%s", type(exc).__name__)
            raise HTTPException(502, "查询未完成，请稍后重试；真实模式下请检查模型服务配置。") from exc

    return app


app = create_app()


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="启动本地 SQL 对话网页（默认 deepseek-flash）")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--live", dest="live", action="store_true", help="使用真实模型（默认），需要 DEEPSEEK_API_KEY")
    modes.add_argument("--demo", dest="live", action="store_false", help="离线演示，不调用模型")
    parser.set_defaults(live=True)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db", default=str(ROOT / "chinook.db"))
    args = parser.parse_args()
    uvicorn.run(create_app(live=args.live, db_path=args.db), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
