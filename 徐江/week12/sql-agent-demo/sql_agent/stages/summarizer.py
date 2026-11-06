"""Stage 7 · 结果汇总。

职责：把执行结果（列 + 行）转成一段自然语言结论，含关键数字；
结果为空时明确说明「没有符合条件的数据」。

week12 起改走 LCEL 链：
``SUMMARIZE_PROMPT | model.bind(temperature=0.3) | parse_text_output``。
"""
from __future__ import annotations

import time

from langchain_core.runnables import Runnable

from ..models import (STATUS_ERROR, STATUS_OK, STATUS_SKIPPED, STAGE_SUMMARIZE,
                      LLMUsage, ExecutionResult, StageTrace)
from ..prompts import build_summarize_input


class ResultSummaryStage:
    name = STAGE_SUMMARIZE

    def __init__(self, chain: Runnable, *, preview_rows: int = 15):
        # summarize_chain = SUMMARIZE_PROMPT | model.bind(temperature=0.3)
        #                 | parse_text_output
        self._chain = chain
        self._preview_rows = preview_rows

    def run(self, question: str, sql: str,
            execution: ExecutionResult) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage: LLMUsage | None = None
        try:
            output = self._chain.invoke(
                build_summarize_input(question, sql, execution,
                                      preview_rows=self._preview_rows)
            )
            usage = output.usage
            summary = (output.parsed or "").strip() or "（模型未返回总结）"
            status, detail = STATUS_OK, f"模型 {output.model}"
        except Exception as exc:  # noqa: BLE001 - 汇总失败不影响工作流成功判定
            summary, status, detail = "", STATUS_ERROR, str(exc)

        duration_ms = (time.perf_counter() - start) * 1000
        trace = StageTrace(
            stage=self.name,
            status=status,
            input_brief=f"{execution.row_count} 行结果",
            output_brief=summary or "（无）",
            detail=detail,
            duration_ms=duration_ms,
            usage=usage,
        )
        return summary, trace


def skipped_trace(reason: str = "配置关闭") -> StageTrace:
    """汇总阶段被关闭时的留痕。"""
    return StageTrace(stage=STAGE_SUMMARIZE, status=STATUS_SKIPPED,
                      input_brief="（未执行）", detail=reason)


__all__ = ["ResultSummaryStage", "skipped_trace"]
