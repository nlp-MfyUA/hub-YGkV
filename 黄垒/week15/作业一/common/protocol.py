"""进程之间传的数据结构（HTTP JSON 契约）。

链路：前端 --text--> 后端 --text--> 进程1 --SentimentResult--> 后端
                          --text+SentimentResult--> 进程2 --ReplyResult--> 后端 --> 前端
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Label = Literal["positive", "negative", "neutral"]
Strategy = Literal["encourage", "soothe", "listen", "crisis"]

_LABEL_ALIAS = {
    "positive": "positive", "pos": "positive", "积极": "positive",
    "正向": "positive", "正面": "positive", "开心": "positive",
    "negative": "negative", "neg": "negative", "消极": "negative",
    "负向": "negative", "负面": "negative", "难过": "negative",
    "neutral": "neutral", "neu": "neutral", "中性": "neutral", "中立": "neutral",
}


def norm_label(value: Any, default: Label = "neutral") -> Label:
    """模型偶尔会返回「积极 / POSITIVE / 2」之类，统一收敛到三分类。"""
    if isinstance(value, str):
        return _LABEL_ALIAS.get(value.strip().lower(), _LABEL_ALIAS.get(value.strip(), default))  # type: ignore[return-value]
    return default


def clamp(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.5) -> float:
    """把 0~1 的分数夹紧；模型有时会给 85、0.85、"0.8" 甚至 "85%" 。"""
    if isinstance(value, str):
        value = value.strip().rstrip("%")
        try:
            value = float(value) / (100.0 if float(value) > 1.0 else 1.0)
        except ValueError:
            return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    if num > 1.0:            # 85 -> 0.85；1.5 -> 1.0
        num = num / 100.0 if num > 1.5 else 1.0
    return max(low, min(high, num))


class SentimentResult(BaseModel):
    """进程1 输出。"""

    label: Label = "neutral"
    emotion: str = "平静"
    confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
    keywords: list[str] = Field(default_factory=list)
    source: str = "llm"          # llm / refine / rule
    notes: list[str] = Field(default_factory=list)   # 图/Agent 内部执行轨迹

    @classmethod
    def from_raw(cls, raw: dict, source: str = "llm") -> "SentimentResult":
        keywords = raw.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.replace("，", ",").split(",") if k.strip()]
        return cls(
            label=norm_label(raw.get("label")),
            emotion=str(raw.get("emotion") or "平静")[:20],
            confidence=clamp(raw.get("confidence"), default=0.6),
            intensity=clamp(raw.get("intensity"), default=0.5),
            reason=str(raw.get("reason") or "")[:200],
            keywords=[str(k)[:20] for k in keywords][:6],
            source=source,
        )


class ReplyResult(BaseModel):
    """进程2 输出。"""

    strategy: Strategy = "listen"
    reply: str = ""
    tips: list[str] = Field(default_factory=list)
    follow_up: str = ""
    source: str = "llm"
    notes: list[str] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict, strategy: Strategy, source: str = "llm") -> "ReplyResult":
        tips = raw.get("tips") or []
        if isinstance(tips, str):
            tips = [t.strip() for t in tips.replace("，", "、").split("、") if t.strip()]
        if not isinstance(tips, list):
            tips = []
        return cls(
            strategy=strategy,
            reply=str(raw.get("reply") or "").strip()[:600],
            tips=[str(t)[:40] for t in tips][:3],
            follow_up=str(raw.get("follow_up") or "").strip()[:60],
            source=source,
        )


class TraceStep(BaseModel):
    """链路轨迹：前端/后端/进程1/进程2 各做了一步什么。"""

    stage: str
    node: str
    detail: str = ""
    ms: int = 0


class ChatRequest(BaseModel):
    text: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    session_id: str
    text: str
    sentiment: SentimentResult
    reply: ReplyResult
    trace: list[TraceStep] = Field(default_factory=list)
    elapsed_ms: int = 0
    degraded: bool = False
