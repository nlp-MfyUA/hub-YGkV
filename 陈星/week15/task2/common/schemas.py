"""Pydantic data contracts shared across Process 1, Process 2, Backend, and Frontend."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

SentimentType = Literal["positive", "negative"]
StrategyType = Literal["encourage", "comfort"]
NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SentimentRequest(BaseModel):
    """Input payload for Process 1 (sentiment recognition)."""

    text: NonBlankText = Field(..., description="用户输入的原始文本")


class SentimentResult(BaseModel):
    """Structured LLM output for sentiment classification."""

    sentiment: SentimentType = Field(..., description="情感极性：positive(正向) 或 negative(负面)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="置信度 0~1")
    reason: NonBlankText = Field(..., description="判断依据简述")


class SentimentResponse(SentimentResult):
    """Process 1 HTTP response including process identity metadata."""

    framework: str
    process: str = "process1_sentiment"
    pid: int


class RespondRequest(BaseModel):
    """Input payload for Process 2 (conditional encouragement/comfort)."""

    text: NonBlankText = Field(..., description="用户原始输入")
    sentiment: SentimentType = Field(..., description="进程1识别出的情感极性")
    reason: str = Field(default="", description="进程1给出的判断依据")


class RespondResponse(BaseModel):
    """Process 2 HTTP response including routing strategy and reply."""

    sentiment: SentimentType
    strategy: StrategyType
    reply: NonBlankText
    handler: str
    framework: str
    process: str = "process2_responder"
    pid: int


class ChatRequest(BaseModel):
    """Frontend -> Backend request payload."""

    text: NonBlankText = Field(..., description="用户输入")


class ChatResponse(BaseModel):
    """Backend -> Frontend aggregated response chaining Process 1 and Process 2."""

    input_text: str
    sentiment: SentimentResponse
    response: RespondResponse
    framework: str
    backend_pid: int
