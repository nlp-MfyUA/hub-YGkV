"""全局配置：模型、端口、超时。所有项都可以用环境变量覆盖。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# common/config.py -> common -> 作业一 -> week15
COMMON_DIR = Path(__file__).resolve().parent
ASSIGNMENT_DIR = COMMON_DIR.parent          # 作业一
WEEK_DIR = ASSIGNMENT_DIR.parent            # week15

# 依次向上找 .env；先加载的优先（override=False），
# 所以 week15/.env 里写一份，两个版本都能共用。
for _env in (WEEK_DIR / ".env", ASSIGNMENT_DIR / ".env", Path.cwd() / ".env"):
    if _env.is_file():
        load_dotenv(_env, override=False)

# --------------------------------------------------------------------------- #
# 大模型（OpenAI 兼容协议：DeepSeek / 通义百炼 / 智谱 都能直接换）
# --------------------------------------------------------------------------- #
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL: str = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT", "90"))
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "900"))

# --------------------------------------------------------------------------- #
# 四个进程的端口：前端(CLI，无端口) -> 后端 8100 -> 进程1 8101 / 进程2 8102
# --------------------------------------------------------------------------- #
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8100"))
SENTIMENT_PORT: int = int(os.getenv("SENTIMENT_PORT", "8101"))
REPLY_PORT: int = int(os.getenv("REPLY_PORT", "8102"))

# 后端访问两个子服务的地址（docker 里用服务名覆盖成 http://sentiment:8101）
SENTIMENT_URL: str = os.getenv("SENTIMENT_URL", f"http://127.0.0.1:{SENTIMENT_PORT}")
REPLY_URL: str = os.getenv("REPLY_URL", f"http://127.0.0.1:{REPLY_PORT}")
BACKEND_URL: str = os.getenv("BACKEND_URL", f"http://127.0.0.1:{BACKEND_PORT}")

# 进程之间是 HTTP 调用，超时要比模型超时略短，避免一个服务卡死拖垮后端
RPC_TIMEOUT: float = float(os.getenv("RPC_TIMEOUT", "45"))
RPC_RETRY: int = int(os.getenv("RPC_RETRY", "1"))
SERVICE_START_TIMEOUT: float = float(os.getenv("SERVICE_START_TIMEOUT", "60"))

MAX_INPUT_CHARS: int = int(os.getenv("MAX_INPUT_CHARS", "500"))


def has_llm() -> bool:
    """没有 Key 也能跑：会走规则兜底，端口和链路依旧可用。"""
    return bool(LLM_API_KEY.strip())


def summary() -> str:
    key = f"{LLM_API_KEY[:6]}***{LLM_API_KEY[-4:]}" if len(LLM_API_KEY) > 12 else "(未配置)"
    return (
        f"model={LLM_MODEL} base_url={LLM_BASE_URL} key={key}\n"
        f"backend={BACKEND_PORT} sentiment={SENTIMENT_URL} reply={REPLY_URL}"
    )
