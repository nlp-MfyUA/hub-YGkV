"""Provider 抽象基类与共享实现（技术设计文档 §2.1 / §2.2）。

base.py 除抽象基类外还提供一个 OpenAI 兼容客户端的共享实现，
deepseek / qwen 两个子类只声明自己的默认端点，行为完全一致。
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, AsyncOpenAI
from openai import APITimeoutError as OpenAITimeoutError

from ..errors import ApiError, ModelTimeoutError, ModelUpstreamError


@dataclass
class RawResult:
    """Provider 统一返回：原始文本 + 延迟 + 通道标识。"""

    text: str
    latency_ms: int
    provider: str
    model: str


class VisionProvider(ABC):
    """视觉大模型统一接口：输入 Base64 图片与两段 Prompt，输出原始文本。"""

    name: str
    model: str

    @abstractmethod
    async def analyze(self, image_b64: str, system_prompt: str, user_text: str,
                      *, mime: str = "image/jpeg") -> RawResult:
        """调用一次视觉对话；网络错误 / 5xx 由调用方（main.py）决定是否重试。"""
        ...


def translate_error(exc: Exception) -> ApiError:
    """把 openai SDK 异常翻译成本项目的错误码（供重试逻辑判定是否可重试）。

    可重试：网络连接错误、5xx。不可重试：超时、4xx（如 Key 无效）。
    """
    if isinstance(exc, OpenAITimeoutError):
        return ModelTimeoutError(f"模型调用超时：{exc}")
    if isinstance(exc, APIStatusError):
        if exc.status_code >= 500:
            return ModelUpstreamError(
                f"模型服务异常（HTTP {exc.status_code}），请稍后重试", retryable=True)
        if exc.status_code in (401, 403):
            return ModelUpstreamError(f"API Key 无效或已过期（HTTP {exc.status_code}）")
        return ModelUpstreamError(f"模型接口拒绝请求（HTTP {exc.status_code}）：{exc.body}")
    if isinstance(exc, APIConnectionError):
        return ModelUpstreamError(f"无法连接模型服务：{exc}", retryable=True)
    return ModelUpstreamError(f"模型调用失败：{exc}")


class OpenAICompatProvider(VisionProvider):
    """OpenAI 兼容客户端的共享实现：消息组装 + 计时 + 错误翻译。"""

    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 30.0):
        if not api_key or not base_url:
            raise RuntimeError(f"{self.name} provider 未配置 api_key / base_url")
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    async def analyze(self, image_b64: str, system_prompt: str, user_text: str,
                      *, mime: str = "image/jpeg") -> RawResult:
        t0 = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url",
                         "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    ]},
                ],
                temperature=0.1,
                max_tokens=800,
            )
        except ApiError:
            raise
        except Exception as exc:
            raise translate_error(exc) from exc

        latency = int((time.perf_counter() - t0) * 1000)
        text = resp.choices[0].message.content or ""
        return RawResult(text=text, latency_ms=latency, provider=self.name, model=self.model)
