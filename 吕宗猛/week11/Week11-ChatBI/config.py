"""全局配置：从 .env 读取网关、模型与执行限额。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent

# override=True：.env 优先于系统同名环境变量（与 week10 保持一致）
load_dotenv(ROOT / ".env", override=True)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


# ---- 模型网关 ----
BASE_URL = _env("BASE_URL", "http://127.0.0.1:7863/v1")
API_KEY = _env("API_KEY", "")
MODEL_NAME = _env("MODEL_NAME", "cn:deepseek-v4.1-flash")

# 三个 Agent 可各自覆盖；默认沿用 MODEL_NAME
GENERATE_MODEL = _env("GENERATE_MODEL", MODEL_NAME)
CHECK_MODEL = _env("CHECK_MODEL", MODEL_NAME)
SUMMARY_MODEL = _env("SUMMARY_MODEL", MODEL_NAME)
# 复核模型尾延迟兜底：超时或失败时改用该模型再复核一次
CHECK_FALLBACK_MODEL = _env("CHECK_FALLBACK_MODEL", "cn:minimax-m3.1-flash")
CHECK_TIMEOUT_SECONDS = float(_env("CHECK_TIMEOUT_SECONDS", "15"))

LLM_TIMEOUT_SECONDS = float(_env("LLM_TIMEOUT_SECONDS", "120"))

# ---- 数据库 ----
_db_raw = Path(_env("DB_FILE_PATH", "./db/chinook.db"))
DB_PATH = (_db_raw if _db_raw.is_absolute() else (ROOT / _db_raw)).resolve()

# ---- 流程约束 ----
MAX_REVIEW_ROUNDS = int(_env("MAX_REVIEW_ROUNDS", "3"))

# ---- 执行约束 ----
MAX_RESULT_ROWS = int(_env("MAX_RESULT_ROWS", "200"))   # 结果行数上限（自动补 LIMIT）
QUERY_TIMEOUT_SECONDS = float(_env("QUERY_TIMEOUT_SECONDS", "5"))
MAX_SQL_LENGTH = int(_env("MAX_SQL_LENGTH", "8000"))

# ---- 服务 ----
HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8611"))


def summary() -> dict:
    """健康检查用，不输出密钥。"""
    return {
        "base_url": BASE_URL,
        "models": {
            "generate": GENERATE_MODEL,
            "check": CHECK_MODEL,
            "summary": SUMMARY_MODEL,
        },
        "db_path": str(DB_PATH),
        "db_exists": DB_PATH.is_file(),
        "max_review_rounds": MAX_REVIEW_ROUNDS,
        "max_result_rows": MAX_RESULT_ROWS,
        "query_timeout_seconds": QUERY_TIMEOUT_SECONDS,
    }
