"""全局配置：模型网关、运行端口与离线演示开关。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# override=True：.env 优先于系统同名环境变量；没有 .env 时使用下面的默认值
load_dotenv(ROOT / ".env", override=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


# ---- 模型网关（OpenAI 兼容协议）----
BASE_URL = _env("BASE_URL", "http://127.0.0.1:3425/v1")
API_KEY = _env("API_KEY", "")
MODEL_NAME = _env("MODEL_NAME", "workbuddy/deepseek-v4.1-flash")

# 情感识别与回应可以使用不同模型；默认沿用 MODEL_NAME
EMOTION_MODEL = _env("EMOTION_MODEL", MODEL_NAME)
REPLY_MODEL = _env("REPLY_MODEL", MODEL_NAME)
TITLE_MODEL = _env("TITLE_MODEL", MODEL_NAME)

LLM_TIMEOUT_SECONDS = float(_env("LLM_TIMEOUT_SECONDS", "120"))
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.7"))

# MOCK_MODE=1 时不调用真实模型，用本地规则跑通整条多 Agent 链路。
# 适合课堂演示、无网关环境和自动化测试；接真实模型时设为 0。
MOCK_MODE = _env("MOCK_MODE", "0").lower() in {"1", "true", "yes", "on"}

# ---- 服务：后端进程 ----
HOST = _env("BACKEND_HOST", "127.0.0.1")
PORT = int(_env("BACKEND_PORT", "8622"))
FRONTEND_HOST = _env("FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = int(_env("FRONTEND_PORT", "8612"))

# ---- 对话上下文 ----
MAX_HISTORY_ROUNDS = int(_env("MAX_HISTORY_ROUNDS", "5"))

# ---- 本地 SQLite 会话库 ----
_db_raw = Path(_env("SESSION_DB_PATH", "./data/sessions.db"))
SESSION_DB_PATH = (_db_raw if _db_raw.is_absolute() else (ROOT / _db_raw)).resolve()


def summary() -> dict:
    """健康检查用，不暴露密钥。"""
    return {
        "framework": "LangGraph",
        "base_url": BASE_URL,
        "models": {
            "emotion": EMOTION_MODEL,
            "reply": REPLY_MODEL,
            "title": TITLE_MODEL,
        },
        "mock_mode": MOCK_MODE,
        "history_rounds": MAX_HISTORY_ROUNDS,
        "session_db": str(SESSION_DB_PATH),
        "host": HOST,
        "port": PORT,
        "frontend_port": FRONTEND_PORT,
    }
