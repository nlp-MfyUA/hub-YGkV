from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResearchRequest(StrictModel):
    topic: str = Field(min_length=2, max_length=1000)
    max_rounds: int = Field(default=2, ge=1, le=2, strict=True)
    max_pages: int = Field(default=8, ge=1, le=8, strict=True)
    timeout_seconds: int = Field(default=300, ge=10, le=300, strict=True)

    @field_validator("topic", mode="before")
    @classmethod
    def strip_topic(cls, value):
        return value.strip() if isinstance(value, str) else value


class Plan(StrictModel):
    subquestions: list[str] = Field(min_length=1, max_length=3)
    queries: list[str] = Field(min_length=1, max_length=3)


class EvidenceDraft(StrictModel):
    statement: str = Field(min_length=1, max_length=1500)
    quote: str = Field(min_length=10, max_length=1500)


class Extraction(StrictModel):
    evidence: list[EvidenceDraft] = Field(max_length=4)


class Review(StrictModel):
    sufficient: bool
    reason: str = Field(min_length=1, max_length=2000)
    queries: list[str] = Field(max_length=3)
    unresolved_questions: list[str] = Field(max_length=10)


class DraftClaim(StrictModel):
    text: str = Field(min_length=1, max_length=2500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["高", "中", "低"] = "低"
    confidence_reason: str = Field(min_length=1, max_length=1000)


class DraftSection(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    claims: list[DraftClaim] = Field(min_length=1, max_length=8)


class DraftReport(StrictModel):
    summary: list[DraftClaim] = Field(min_length=1, max_length=5)
    sections: list[DraftSection] = Field(min_length=1, max_length=8)
    key_conclusions: list[DraftClaim] = Field(min_length=1, max_length=8)
    unresolved_questions: list[str] = Field(max_length=15)
    conflicts: list[str] = Field(default_factory=list, max_length=10)


class Source(StrictModel):
    id: str
    url: str
    title: str
    publisher: str
    published_at: str | None = None
    fetched_at: str


class Evidence(StrictModel):
    id: str
    source_id: str
    statement: str
    quote: str


class Usage(StrictModel):
    model_calls: int = 0
    calls_with_usage: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
