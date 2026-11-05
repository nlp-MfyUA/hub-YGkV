"""大模型调用封装（OpenAI 兼容协议，默认 DeepSeek）。

工作流里每个阶段都是一次独立的 LLM 调用，所以这里只做三件事：
    1. 从环境变量读配置；
    2. 统一重试 / 超时；
    3. json_mode 时用 response_format=json_object（DeepSeek、Qwen 都支持）。
"""
from __future__ import annotations

import json
import os
import re
import time

from openai import OpenAI


class LLMError(RuntimeError):
    """大模型调用失败（重试后仍然失败）。"""


class LLMClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        if not self.api_key:
            raise LLMError("缺少 LLM_API_KEY，请先把 .env.example 复制为 .env 并填入自己的 Key。")

        self.model = model or os.environ.get("LLM_MODEL", "deepseek-chat")
        self.base_url = base_url or os.environ.get("LLM_BASE_URL")
        self.max_retries = max_retries
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        json_mode: bool = False,
    ) -> str:
        """发起一次对话，返回模型输出的纯文本。"""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kwargs: dict = {"model": self.model, "messages": messages, "temperature": temperature}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:  # 网络抖动、限流、5xx 都重试
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise LLMError(f"大模型调用失败（已重试 {self.max_retries} 次）：{last_error}")


# --------------------------------------------------------------------------- #
# 输出清洗工具
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"```(?:json|sql)?\s*(.*?)```", re.S)


def strip_fence(text: str) -> str:
    """去掉 markdown 代码块围栏（模型经常不听话地加上）。"""
    match = _FENCE.search(text or "")
    return match.group(1).strip() if match else (text or "").strip()


def extract_json(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象，解析失败抛 ValueError。"""
    raw = strip_fence(text)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"模型输出里没有 JSON 对象：{text[:200]!r}")
    return json.loads(raw[start : end + 1])
