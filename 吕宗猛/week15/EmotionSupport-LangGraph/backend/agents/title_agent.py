"""会话标题生成：聊天开始时用 LLM 给会话起一个短标题。"""

from __future__ import annotations

import re

from langchain_openai import ChatOpenAI

import config
from agents.base import build_model

TITLE_PROMPT = """你是会话标题生成器。根据用户的第一句话，生成一个中文标题，概括话题或情绪，控制在 8-16 个汉字。
只输出标题本身，不要引号、不要冒号、不要句号、不要解释、不要加“标题：”前缀。"""


def fallback_title(text: str) -> str:
    compact = " ".join((text or "").split()).strip("。！？!?，,；;：:")
    return compact[:14] if compact else "新的对话"


def clean_title(raw: str) -> str:
    text = re.sub(r"^\s*标题\s*[:：]\s*", "", (raw or "").strip())
    text = text.strip("「」『』\"'“”‘’：:。！？!?，,")
    text = " ".join(text.split())
    return text[:20]


class TitleAgent:
    """独立的小 Agent：只负责会话标题，不参与情绪回应。"""

    def __init__(self) -> None:
        self._model: ChatOpenAI = build_model(config.TITLE_MODEL, temperature=0.2)

    async def generate(self, first_message: str) -> str:
        if config.MOCK_MODE:
            return fallback_title(first_message)
        try:
            response = await self._model.ainvoke(
                [("system", TITLE_PROMPT), ("human", first_message)]
            )
            content = response.content
            if isinstance(content, list):
                content = "".join(str(item) for item in content)
            return clean_title(str(content)) or fallback_title(first_message)
        except Exception:  # noqa: BLE001 - 标题失败不能阻塞聊天
            return fallback_title(first_message)
