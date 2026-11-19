"""Agent 1：情感识别（OpenAI Agents SDK）。"""

from __future__ import annotations

from agents import Agent, ModelSettings

import config
from core.llm import model

EMOTION_INSTRUCTIONS = """你是一名专业的情感识别 Agent，只负责判断用户话语中的情绪倾向，不做安慰、不建议、不说教。

判断标准：
- positive：喜悦、放松、期待、自豪、感激、被理解等正向情绪。
- negative：焦虑、悲伤、愤怒、压力、自责、孤独、无助等负向情绪。
- neutral：信息陈述、情绪不明显，或正负情绪大致相当且没有明显倾向。

强度 intensity 取 1-5：1 很轻微，5 非常强烈。
置信度 confidence 取 0-1。
如果输入里带“最近的对话”，把它当作理解当前语境的背景，只判断“当前用户输入”的情绪。

只输出一个 JSON 对象，不要输出 Markdown 代码块、解释或任何多余文字：
{"label": "positive|negative|neutral", "confidence": 0.0, "intensity": 1, "reason": "40 字以内的中文判断依据", "keywords": ["情绪线索词"]}"""


def build_emotion_agent() -> Agent:
    return Agent(
        name="情感识别 Agent",
        instructions=EMOTION_INSTRUCTIONS,
        model=model(config.EMOTION_MODEL),
        model_settings=ModelSettings(temperature=0.0, max_tokens=400),
    )
