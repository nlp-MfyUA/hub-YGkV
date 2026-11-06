"""Stage 5 · SQL 改写。

职责：校验失败或执行报错时，携带「原 SQL + 错误信息」让 LLM 修复，
产出新 SQL 后重新进入校验 → 执行。只在第 2 次及以后的尝试调用。
"""
from __future__ import annotations

import time

from ..db import DatabaseSchema
from ..llm import BaseLLMClient, LLMError
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_REWRITE, LLMUsage, StageTrace
from ..prompts import build_rewrite_messages, extract_sql


class SqlRewriteStage:
    name = STAGE_SQL_REWRITE

    def __init__(self, llm: BaseLLMClient, *, temperature: float | None = None):
        self._llm = llm
        self._temperature = temperature

    def run(self, question: str, schema: DatabaseSchema, tables: list[str],
            failed_sql: str, error: str, attempt: int) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage = LLMUsage()
        llm_failed = False
        try:
            resp = self._llm.chat(
                build_rewrite_messages(schema.to_prompt(tables), question,
                                       failed_sql, error, attempt),
                task="rewrite_sql",
                temperature=self._temperature,
            )
        except LLMError as exc:
            # LLM 接口本身失败：重试无意义，交由工作流短路
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
                status, detail = STATUS_OK, f"依据错误信息改写: {error}"

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"错误: {error}｜原 SQL: {failed_sql}",
            output_brief=sql or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            attempt=attempt,
            usage=usage if usage.calls else None,
            llm_failed=llm_failed,
        )
        return sql, trace


__all__ = ["SqlRewriteStage", "STATUS_ERROR"]
