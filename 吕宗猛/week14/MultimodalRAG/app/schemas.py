"""Pydantic response models."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    file_size: int
    status: str
    tier: str
    page_count: int | None
    chunk_count: int
    image_count: int
    error_msg: str | None
    created_at: datetime
    updated_at: datetime
    parsed_at: datetime | None


class ChatSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    updated_at: datetime


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    image_path: str | None
    image_ids: list[int] | None
    created_at: datetime


class AskResponse(BaseModel):
    session_id: int
    session_title: str | None = None
    answer: str
    references: list[dict[str, Any]]
    images: list[dict[str, Any]]
