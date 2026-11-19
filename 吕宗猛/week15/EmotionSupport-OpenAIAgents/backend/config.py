"""全局配置：Magpie 模型网关、运行端口与离线演示开关。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env", override=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


# ---- Magpie（OpenAI 兼容协议）----
# Docker 容器内用 host.docker.internal 访问宿主机 Magpie；本地运行仍用 127.0.0.1
_DEFAULT_BASE_URL = (
    "http://host.docker.internal:3425/v1"
    if os.getenv("DOCKER_ENV", "").strip() == "1"
    else "http://127.0.0.1:3425/v1"
)
BASE_URL = _env("BASE_URL", _DEFAULT_BASE_URL)
API_KEY = _env("API_KEY", "")
MODEL_NAME = _env("MODEL_NAME", "workbuddy/deepseek-v4.1-flash")

EMOTION_MODEL = _env("EMOTION_MODEL", MODEL_NAME)
REPLY_MODEL = _env("REPLY_MODEL", MODEL_NAME)
TITLE_MODEL = _env("TITLE_MODEL", MODEL_NAME)

LLM_TIMEOUT_SECONDS = float(_env("LLM_TIMEOUT_SECONDS", "120"))
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.7"))

MOCK_MODE = _env("MOCK_MODE", "0").lower() in {"1", "true", "yes", "on"}

# ---- 服务：后端进程 ----
HOST = _env("BACKEND_HOST", "127.0.0.1")
PORT = int(_env("BACKEND_PORT", "8623"))
FRONTEND_HOST = _env("FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = int(_env("FRONTEND_PORT", "8613"))

# ---- 对话上下文 ----
MAX_HISTORY_ROUNDS = int(_env("MAX_HISTORY_ROUNDS", "5"))

# ---- 本地 SQLite 会话库 ----
_db_raw = Path(_env("SESSION_DB_PATH", "./data/sessions.db"))
SESSION_DB_PATH = (_db_raw if _db_raw.is_absolute() else (ROOT / _db_raw)).resolve()


def apply_model_config(base_url: str, api_key: str, model_name: str) -> None:
    """把 SQLite 中的模型配置应用到当前进程。"""
    global BASE_URL, API_KEY, MODEL_NAME, EMOTION_MODEL, REPLY_MODEL, TITLE_MODEL
    BASE_URL = base_url.strip().rstrip("/")
    API_KEY = api_key.strip()
    MODEL_NAME = model_name.strip()
    EMOTION_MODEL = MODEL_NAME
    REPLY_MODEL = MODEL_NAME
    TITLE_MODEL = MODEL_NAME


def summary() -> dict:
    """健康检查用，不暴露密钥。"""
    return {
        "framework": "OpenAI Agents SDK",
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