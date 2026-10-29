"""DeepSeek Provider（主通道）。

base_url / model 全部来自 .env（见 config.py），代码不假设具体端点；
若该模型实际不接受 image_url 数组格式，只需改本文件 analyze() 的消息
组装方式（改调用 OpenAICompatProvider 提供的 _chat 或直接重写），其他模块不动。
"""
from __future__ import annotations

from .base import OpenAICompatProvider


class DeepSeekProvider(OpenAICompatProvider):
    name = "deepseek"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30.0):
        super().__init__(api_key=api_key, base_url=base_url, model=model, timeout=timeout)
