"""OpenAI Agents SDK 的模型接入层。"""

from __future__ import annotations

from agents import set_tracing_disabled
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

import config

# Magpie 不提供 OpenAI 官方 tracing 上传能力
set_tracing_disabled(True)

_client: AsyncOpenAI | None = None
_models: dict[str, OpenAIChatCompletionsModel] = {}


def reset() -> None:
    """模型配置修改后清空客户端与模型缓存。"""
    global _client
    _client = None
    _models.clear()


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.BASE_URL,
            api_key=config.API_KEY or "EMPTY",
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _client


def model(name: str) -> OpenAIChatCompletionsModel:
    if name not in _models:
        _models[name] = OpenAIChatCompletionsModel(model=name, openai_client=client())
    return _models[name]


def usage_dict(result) -> dict:
    """尽量从 RunResult 中提取 token 用量，取不到就返回空字典。"""
    try:
        usage = result.context_wrapper.usage
    except Exception:  # noqa: BLE001
        return {}
    return {
        "requests": getattr(usage, "requests", 0),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }
