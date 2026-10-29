"""Pydantic 请求模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, description="自然语言问题")
    max_attempts: int | None = Field(
        None, ge=1, le=5, description="覆盖工作流重试上限（1-5）")
    summarize: bool | None = Field(
        None, description="是否执行「结果汇总」阶段")


class EvalRequest(BaseModel):
    ids: str | None = Field(
        None, description="测试问题子集，如 '1,5,8' 或 '1-5'；留空跑全部 15 条")
