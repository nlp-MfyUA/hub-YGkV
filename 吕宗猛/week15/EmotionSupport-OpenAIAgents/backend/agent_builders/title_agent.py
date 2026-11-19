"""会话标题生成：聊天开始时用 LLM 给会话起一个短标题。"""

from __future__ import annotations

import re

from agents import Agent, ModelSettings, Runner

import config
from core.llm import model

TITLE_INSTRUCTIONS = """你是会话标题生成器。根据用户的第一句话，生成一个中文标题，概括话题或情绪，控制在 8-16 个汉字。
只输出标题本身，不要引号、不要冒号、不要句号、不要解释、不要加“标题：”前缀。"""


def fallback_title(text: str) -> str:
    compact = " ".join((text or "").split()).strip("。！？!?，,；;：:")
    return compact[:14] if compact else "新的对话"


def clean_title(raw: str) -> str:
    text = re.sub(r"^\s*标题\s*[:：]\s*", "", (raw or "").strip())
    text = text.strip("「」『』\"'“”‘’：:。！？!?，,")
    text = " ".join(text.split())
    return text[:20]


def build_title_agent() -> Agent:
    return Agent(
        name="标题摘要 Agent",
        instructions=TITLE_INSTRUCTIONS,
        model=model(config.TITLE_MODEL),
        model_settings=ModelSettings(temperature=0.2, max_tokens=60),
    )


async def generate_title(first_message: str) -> str:
    if config.MOCK_MODE:
        return fallback_title(first_message)
    try:
        result = await Runner.run(build_title_agent(), first_message, max_turns=1)
        return clean_title(str(result.final_output)) or fallback_title(first_message)
    except Exception:  # noqa: BLE001 - 标题失败不能阻塞聊天
        return fallback_title(first_message)
