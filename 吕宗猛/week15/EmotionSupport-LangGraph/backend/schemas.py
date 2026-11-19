"""跨 Agent 共享的数据结构。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EmotionLabel = Literal["positive", "negative", "neutral"]

LABEL_ZH: dict[str, str] = {
    "positive": "正向",
    "negative": "负面",
    "neutral": "中性",
}

# 情绪标签 -> 负责回应的 Agent 节点
ROUTES: dict[str, str] = {
    "positive": "encourage",
    "negative": "comfort",
    "neutral": "neutral",
}

AGENT_NAMES: dict[str, str] = {
    "encourage": "正向鼓励 Agent",
    "comfort": "负面排解 Agent",
    "neutral": "中性回应（规则兜底）",
}


class ChatTurn(BaseModel):
    """一轮历史对话中的一条消息。"""

    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=8000)


class EmotionResult(BaseModel):
    """情感识别 Agent 的结构化输出。"""

    label: EmotionLabel = "neutral"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    intensity: int = Field(default=3, ge=1, le=5)
    reason: str = ""
    keywords: list[str] = Field(default_factory=list)

    @property
    def label_zh(self) -> str:
        return LABEL_ZH.get(self.label, "中性")
