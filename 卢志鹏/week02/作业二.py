"""
llm_client.py
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


"""
emotional_analysis_agent.py
情感分析智能体封装。
"""

import json
from openai import OpenAI
from llm_client import LLMClient


def safe_json_parse(text: str) -> dict | list | None:
    """安全解析 JSON，处理可能的空 content 和格式异常。"""
    if not text or not text.strip():
        print("    ⚠️  模型返回了空 content（JSON 模式偶发问题）")
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"    ⚠️  JSON 解析失败: {e}")
        # 尝试修复常见问题：删除 markdown 代码块标记
        cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            print(f"    原始内容: {text[:200]}")
            return None


def analysis_agent(user_prompt: str) -> dict | None:
    system_prompt = """
用户会提供一些情感问题或者关于自身情感的内容。请从中分析问题或内容的情感脉络，并将情感脉络中的关系以 JSON 格式输出。

输入示例：
小明喜欢小姚，但是小姚喜欢小王。

JSON 输出示例：
[
    {
        "source": "小明",
        "relation": "爱慕",
        "target": "小姚"
    },
    {
        "source": "小姚",
        "relation": "爱慕",
        "target": "小王"
    }
]
"""
    llm_client = LLMClient()
    messages = [{"role": "system", "content": system_prompt}]
    list_dict:list[dict] = llm_client._make_messages(user_prompt)

    if list_dict and len(list_dict) > 0:
        messages.append(list_dict[0])

    content = llm_client.chat_v2(messages=messages)
    result = safe_json_parse(content)

    return result

if __name__ == "__main__":
    user_prompt = "小李对小张有好感，小张不喜欢小李，但是暗恋小陈"
    result = analysis_agent(user_prompt=user_prompt)

    if result and len(result) > 0:
        print(f"  解析结果:")
        for item in result:
            print(f"    source:  {item['source']}")
            print(f"    relation: {item['relation']}")
            print(f"    target:   {item['target']}")



