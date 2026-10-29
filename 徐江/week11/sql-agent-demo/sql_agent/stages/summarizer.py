"""Stage 7 · 结果汇总。

职责：把执行结果（列 + 行）转成一段自然语言结论，含关键数字；
结果为空时明确说明「没有符合条件的数据」。
"""
from __future__ import annotations

import time

from ..llm import BaseLLMClient, LLMError
from ..models import (STATUS_ERROR, STATUS_OK, STATUS_SKIPPED, STAGE_SUMMARIZE,
                      LLMUsage, ExecutionResult, StageTrace)
from ..prompts import build_summarize_messages


class ResultSummaryStage:
    name = STAGE_SUMMARIZE

    def __init__(self, llm: BaseLLMClient, *, preview_rows: int = 15):
        self._llm = llm
        self._preview_rows = preview_rows

    def run(self, question: str, sql: str,
            execution: ExecutionResult) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage = LLMUsage()
        try:
            resp = self._llm.chat(
                build_summarize_messages(
                    question, sql,
                    columns=execution.columns,
                    rows=execution.rows,
                    row_count=execution.row_count,
                    truncated=execution.truncated,
                    preview_rows=self._preview_rows,
                ),
                task="summarize",
                temperature=0.3,
            )
            usage.prompt_tokens += resp.prompt_tokens
            usage.completion_tokens += resp.completion_tokens
            usage.total_tokens += resp.total_tokens
            usage.calls += 1
            summary = (resp.content or "").strip() or "（模型未返回总结）"
            status, detail = STATUS_OK, f"模型 {resp.model}"
        except LLMError as exc:
            summary, status, detail = "", STATUS_ERROR, str(exc)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"{execution.row_count} 行结果",
            output_brief=summary or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            usage=usage if usage.calls else None,
        )
        return summary, trace


def skipped_trace(reason: str = "配置关闭") -> StageTrace:
    """汇总阶段被关闭时的留痕。"""
    return StageTrace(stage=STAGE_SUMMARIZE, status=STATUS_SKIPPED,
                      input_brief="（未执行）", detail=reason)


__all__ = ["ResultSummaryStage", "skipped_trace", "STATUS_ERROR", "STATUS_OK", "STATUS_SKIPPED"]
