"""Qwen Provider（备选通道，DashScope compatible-mode）。

结构与 DeepSeek 相同，差别仅在默认 base_url / model（见 config.py）。
"""
from __future__ import annotations

from .base import OpenAICompatProvider


class QwenProvider(OpenAICompatProvider):
    name = "qwen"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30.0):
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
