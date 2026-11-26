from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请输入非空内容")
        return value.strip()


class Sentiment(BaseModel):
    sentiment: Literal["positive", "negative"]
    reason: str = Field(min_length=1, max_length=500)


class ReplyInput(UserInput):
    analysis: Sentiment


class Reply(BaseModel):
    reply: str = Field(min_length=1)


class ChatResult(ReplyInput, Reply):
    framework: str
    strategy: Literal["encourage", "comfort"]
