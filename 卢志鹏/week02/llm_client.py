"""
OpenAI 兼容客户端封装。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)

# D:\MyTasks\报班\课程\课程\第二周\第二周作业-卢志鹏\.env

class LLMClient:
    """OpenAI 兼容的 LLM 客户端。
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None
    ):
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.model = model or os.getenv("LLM_MODEL", "gpt-4o")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def _make_messages(self, prompt: str | list[dict]) -> list[dict]:
        """统一将用户输入转为 messages 列表。"""
        if isinstance(prompt, str):
            return [{"role": "user", "content": prompt}]
        return prompt

    def chat(
        self,
        prompt: str | list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """同步 chat 调用。

        Args:
            prompt: 字符串（单轮）或 messages 列表（多轮/系统消息）。
            model: 覆盖默认模型名。
            max_tokens: 覆盖默认 max_tokens。
            temperature: 覆盖默认 temperature。

        Returns:
            模型回复文本。
        """
        resp = self.client.chat.completions.create(
            model=model or self.model,
            messages=self._make_messages(prompt),
        )
        return resp.choices[0].message.content or ""

    def chat_v2(
            self,
            messages: list[dict],
            *,
            model: str | None = None,
            max_tokens: int | None = None,
            temperature: float | None = None,
        ) -> str:
            """同步 chat 调用。
    
            Args:
                prompt: 字符串（单轮）或 messages 列表（多轮/系统消息）。
                model: 覆盖默认模型名。
                max_tokens: 覆盖默认 max_tokens。
                temperature: 覆盖默认 temperature。
    
            Returns:
                模型回复文本。
            """
            resp = self.client.chat.completions.create(
                model=model or self.model,
                messages=messages,
            )
            return resp.choices[0].message.content or ""

    def chat_stream(
        self,
        prompt: str | list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ):
        """流式 chat 调用（返回生成器，逐 chunk 产出文本）。"""
        stream = self.client.chat.completions.create(
            model=model or self.model,
            messages=self._make_messages(prompt),
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield delta.content

if __name__ == "__main__":
    llm = LLMClient()

    print(f"模型: {llm.model}")
    print(f"Base: {llm.base_url}")
    print(f"Key:  {llm.api_key[:12]}...")

    # 检测占位 key，跳过实际调用
    if "sk-your" in llm.api_key:
        print("\n⚠️  检测到占位 API key，请修改 asserts/llm.env 中的 LLM_API_KEY 后重试。")
    else:
        reply = llm.chat("用一句话介绍倒排索引")
        print(f"\n回复: {reply}")
