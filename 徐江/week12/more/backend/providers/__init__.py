"""Provider 工厂（技术设计文档 §2.4）。"""
from __future__ import annotations

from .base import VisionProvider
from .deepseek import DeepSeekProvider
from .qwen import QwenProvider


def build_provider(settings) -> VisionProvider:
    """按 settings.vision_provider 构造对应通道；未知值直接报错。"""
    if settings.vision_provider == "deepseek":
        return DeepSeekProvider(
            settings.deepseek_api_key, settings.deepseek_base_url,
            settings.deepseek_model, settings.timeout_s,
        )
    if settings.vision_provider == "qwen":
        return QwenProvider(
            settings.qwen_api_key, settings.qwen_base_url,
            settings.qwen_model, settings.timeout_s,
        )
    raise ValueError(f"未知 provider: {settings.vision_provider}")
