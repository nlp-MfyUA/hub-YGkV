"""Stage 3 · SQL 生成。

职责：问题 + 选中表的 schema → 一条 SQL。只在工作流的第 1 次尝试调用；
第 2 次及以后由「SQL 改写」阶段负责。

week12 起改走 LCEL 链：``GENERATE_SQL_PROMPT | model | parse_sql_output``。
"""
from __future__ import annotations

import time

from langchain_core.runnables import Runnable

from ..db import DatabaseSchema
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_GENERATE, LLMUsage, StageTrace


class SqlGenerationStage:
    name = STAGE_SQL_GENERATE

    def __init__(self, chain: Runnable):
        # generate_sql_chain = GENERATE_SQL_PROMPT | model | parse_sql_output
        self._chain = chain

    def run(self, question: str, schema: DatabaseSchema,
            tables: list[str], attempt: int = 1) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage: LLMUsage | None = None
        llm_failed = False
        try:
            output = self._chain.invoke(
                {"schema_prompt": schema.to_prompt(tables), "question": question}
            )
            usage = output.usage
            sql = output.parsed if isinstance(output.parsed, str) else ""
            if not sql:
                status, detail = STATUS_ERROR, "模型未返回可解析的 SQL"
            else:
                status, detail = STATUS_OK, f"模型 {output.model}"
        except Exception as exc:  # noqa: BLE001 - 统一转成失败留痕，交由工作流短路
            # LLM 接口本身失败（鉴权 / 限流 / 网络）：重试无意义
            sql, status, detail, llm_failed = "", STATUS_ERROR, str(exc), True

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"问题: {question}｜候选表: {', '.join(tables)}",
            output_brief=sql or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            attempt=attempt,
            usage=usage,
            llm_failed=llm_failed,
        )
        return sql, trace


__all__ = ["SqlGenerationStage"]
