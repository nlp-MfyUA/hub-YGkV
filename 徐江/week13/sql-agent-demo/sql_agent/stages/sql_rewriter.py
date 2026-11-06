"""Stage 5 · SQL 改写。

职责：校验失败或执行报错时，携带「原 SQL + 错误信息」让 LLM 修复，
产出新 SQL 后重新进入校验 → 执行。只在第 2 次及以后的尝试调用。

week13 起在 LangGraph 节点内经 :func:`~sql_agent.llm_call.call_llm`
直调模型（REWRITE_SQL_PROMPT + PARSER_SQL），取代 week12 的 LCEL 链。
"""
from __future__ import annotations

import time

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from ..db import DatabaseSchema
from ..llm_call import PARSER_SQL, call_llm
from ..models import STATUS_ERROR, STATUS_OK, STAGE_SQL_REWRITE, LLMUsage, StageTrace
from ..prompts import REWRITE_SQL_PROMPT


class SqlRewriteStage:
    name = STAGE_SQL_REWRITE

    def __init__(self, model: BaseChatModel,
                 prompt: ChatPromptTemplate = REWRITE_SQL_PROMPT):
        # 节点内直调：call_llm(model, prompt, vars, parser=PARSER_SQL)
        self._model = model
        self._prompt = prompt

    def run(self, question: str, schema: DatabaseSchema, tables: list[str],
            failed_sql: str, error: str, attempt: int) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage: LLMUsage | None = None
        llm_failed = False
        try:
            output = call_llm(
                self._model, self._prompt, {
                    "schema_prompt": schema.to_prompt(tables),
                    "question": question,
                    "failed_sql": failed_sql,
                    "error": error,
                    "attempt": attempt,
                },
                parser=PARSER_SQL,
            )
            usage = output.usage
            sql = output.parsed if isinstance(output.parsed, str) else ""
            if not sql:
                status, detail = STATUS_ERROR, "模型未返回可解析的 SQL"
            else:
                status, detail = STATUS_OK, f"依据错误信息改写: {error}"
        except Exception as exc:  # noqa: BLE001 - 统一转成失败留痕，交由工作流短路
            # LLM 接口本身失败：重试无意义
            sql, status, detail, llm_failed = "", STATUS_ERROR, str(exc), True

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"错误: {error}｜原 SQL: {failed_sql}",
            output_brief=sql or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            attempt=attempt,
            usage=usage,
            llm_failed=llm_failed,
        )
        return sql, trace


__all__ = ["SqlRewriteStage"]
