"""配置与模型工厂。

一个 ChatOpenAI 实例 + provider 名字，就是全部差异。
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

# 中英文对照，前端展示用
RISK_LABELS_CN: dict[str, str] = {
    "none": "无风险",
    "low": "低风险",
    "medium": "中风险",
    "high": "高风险",
    "non_hallway": "非楼道",
}

RISK_COLORS: dict[str, str] = {
    "none": "#1a9c5b",
    "low": "#c8a415",
    "medium": "#e8722c",
    "high": "#d8342f",
    "non_hallway": "#7a8699",
}

# 分档与分数的大致对应区间，用于一致性校验
SCORE_RANGES: dict[str, tuple[int, int]] = {
    "none": (0, 20),
    "low": (10, 45),
    "medium": (35, 75),
    "high": (65, 100),
    "non_hallway": (0, 100),
}

PROVIDERS: dict[str, dict[str, str | None]] = {
    "deepseek": {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4.1-flash"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "api_key": os.getenv("DEEPSEEK_API_KEY") or None,
    },
    "qwen": {
        "model": os.getenv("QWEN_MODEL", "qwen-flash"),
        "base_url": os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        "api_key": os.getenv("DASHSCOPE_API_KEY") or None,
    },
}

DEFAULT_PROVIDER = os.getenv("VLM_PROVIDER", "deepseek")
STRUCTURED_MODE = os.getenv("STRUCTURED_MODE", "tool")
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))


class ProviderError(RuntimeError):
    """供应商配置缺失或不支持。"""


def _clean(cfg: dict[str, str | None]) -> dict[str, str]:
    return {k: v for k, v in cfg.items() if v}


@lru_cache(maxsize=8)
def build_model(provider: str = DEFAULT_PROVIDER, temperature: float = 0.0) -> ChatOpenAI:
    """按 provider 名字构建聊天模型。

    lru_cache 让同一个 provider 只建一次客户端，重复请求复用连接池。
    """
    if provider not in PROVIDERS:
        raise ProviderError(f"未知的模型供应商: {provider}（可选 deepseek / qwen）")

    cfg = _clean(PROVIDERS[provider])
    if not cfg.get("api_key"):
        raise ProviderError(
            f"未配置 {provider} 的 API Key，请在 .env 中填写 "
            f"{'DEEPSEEK_API_KEY' if provider == 'deepseek' else 'DASHSCOPE_API_KEY'}"
        )

    return ChatOpenAI(
        **cfg,
        temperature=temperature,
        timeout=60,
        max_retries=2,  # 只对网络错误/5xx 自动重试，不做业务重试
    )


def provider_status() -> dict[str, dict[str, object]]:
    """给 /api/health 用：哪个 provider 配好了 key。"""
    return {
        name: {
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "configured": bool(cfg.get("api_key")),
        }
        for name, cfg in PROVIDERS.items()
    }
