"""Stage 3 · SQL 生成。

职责：问题 + 选中表的 schema → 一条 SQL。只在工作流的第 1 次尝试调用；
第 2 次及以后由「SQL 改写」阶段负责。
"""
from __future__ import annotations

import time

from ..db import DatabaseSchema
from ..llm import BaseLLMClient, LLMError
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_GENERATE, LLMUsage, StageTrace
from ..prompts import build_generate_messages, extract_sql


class SqlGenerationStage:
    name = STAGE_SQL_GENERATE

    def __init__(self, llm: BaseLLMClient, *, temperature: float | None = None):
        self._llm = llm
        self._temperature = temperature

    def run(self, question: str, schema: DatabaseSchema,
            tables: list[str], attempt: int = 1) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage = LLMUsage()
        llm_failed = False
        try:
            resp = self._llm.chat(
                build_generate_messages(schema.to_prompt(tables), question),
                task="generate_sql",
                temperature=self._temperature,
            )
        except LLMError as exc:
            # LLM 接口本身失败（鉴权 / 限流 / 网络）：重试无意义，交由工作流短路
            sql, status, detail, llm_failed = "", STATUS_ERROR, str(exc), True
        else:
            usage.prompt_tokens += resp.prompt_tokens
            usage.completion_tokens += resp.completion_tokens
            usage.total_tokens += resp.total_tokens
            usage.calls += 1
            sql = extract_sql(resp.content)
            if not sql:
                status, detail = STATUS_ERROR, "模型未返回可解析的 SQL"
            else:
                status, detail = STATUS_OK, f"模型 {resp.model}"

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"问题: {question}｜候选表: {', '.join(tables)}",
            output_brief=sql or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            attempt=attempt,
            usage=usage if usage.calls else None,
            llm_failed=llm_failed,
        )
        return sql, trace


__all__ = ["SqlGenerationStage", "STATUS_ERROR"]
