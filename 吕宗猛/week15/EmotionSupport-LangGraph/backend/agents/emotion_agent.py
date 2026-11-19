"""情感识别 Agent：只判断情绪，不负责安慰。"""

from __future__ import annotations

import config
from agents.base import build_model, mock_analyze, parse_emotion
from schemas import EmotionResult

SYSTEM_PROMPT = """你是一名专业的情感识别 Agent，只负责判断用户话语中的情绪倾向，不做安慰、不建议、不说教。

判断标准：
- positive：喜悦、放松、期待、自豪、感激、被理解等正向情绪。
- negative：焦虑、悲伤、愤怒、压力、自责、孤独、无助等负向情绪。
- neutral：信息陈述、情绪不明显，或正负情绪大致相当且没有明显倾向。

强度 intensity 取 1-5：1 很轻微，5 非常强烈。
置信度 confidence 取 0-1。

只输出一个 JSON 对象，不要输出 Markdown 代码块、解释或任何多余文字：
{"label": "positive|negative|neutral", "confidence": 0.0, "intensity": 1, "reason": "40 字以内的中文判断依据", "keywords": ["情绪线索词"]}"""


class EmotionAgent:
    """Agent 1：情感识别。"""

    name = "情感识别 Agent"
    key = "emotion"

    def __init__(self) -> None:
        self._model = build_model(config.EMOTION_MODEL, temperature=0.0)

    async def analyze(self, text: str, history_text: str = "") -> EmotionResult:
        if config.MOCK_MODE:
            return mock_analyze(text)

        human = text
        if history_text:
            human = history_text + "\n\n当前用户输入：\n" + text

        try:
            response = await self._model.ainvoke(
                [("system", SYSTEM_PROMPT), ("human", human)]
            )
        except Exception as exc:  # noqa: BLE001 - 统一转换成可展示错误
            raise RuntimeError(f"情感识别 Agent 调用失败：{type(exc).__name__}: {exc}") from exc

        content = response.content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            content = "".join(parts)

        return parse_emotion(str(content))
