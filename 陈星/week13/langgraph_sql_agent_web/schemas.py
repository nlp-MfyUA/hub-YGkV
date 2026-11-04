"""Pydantic 定义每个 LLM 节点的输出契约。"""
from pydantic import BaseModel, Field


class TableSelection(BaseModel):
    tables: list[str] = Field(description="回答问题需要的全部真实表名，包括 JOIN 中间表")
    reason: str = Field(description="选表的原因")
    needs_clarification: bool = False
    clarification_question: str | None = None


class SQLDraft(BaseModel):
    sql: str = Field(description="一条合法 SQLite SELECT 查询")
    explanation: str = Field(description="SQL 为什么能回答用户问题")


class AnswerSummary(BaseModel):
    answer: str = Field(description="只依据提供的 SQL 查询数据生成的中文回答")
