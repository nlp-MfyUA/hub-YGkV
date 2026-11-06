"""Stage 7 · 结果汇总。

职责：把执行结果（列 + 行）转成一段自然语言结论，含关键数字；
结果为空时明确说明「没有符合条件的数据」。

week13 起在 LangGraph 节点内经 :func:`~sql_agent.llm_call.call_llm`
直调模型（SUMMARIZE_PROMPT + temperature=0.3 + PARSER_TEXT），
取代 week12 的 LCEL 链。
"""
from __future__ import annotations

import time

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate

from ..llm_call import PARSER_TEXT, call_llm
from ..models import (STATUS_ERROR, STATUS_OK, STATUS_SKIPPED, STAGE_SUMMARIZE,
                      LLMUsage, ExecutionResult, StageTrace)
from ..prompts import SUMMARIZE_PROMPT, build_summarize_input

# 汇总阶段的温度（与 week11/12 一致：结论生成允许一点发散）
SUMMARIZE_TEMPERATURE = 0.3


class ResultSummaryStage:
    name = STAGE_SUMMARIZE

    def __init__(self, model: BaseChatModel,
                 prompt: ChatPromptTemplate = SUMMARIZE_PROMPT, *,
                 preview_rows: int = 15, temperature: float = SUMMARIZE_TEMPERATURE):
        # 节点内直调：call_llm(model, prompt, vars, parser=PARSER_TEXT,
        #                    temperature=temperature)
        self._model = model
        self._prompt = prompt
        self._preview_rows = preview_rows
        self._temperature = temperature

    def run(self, question: str, sql: str,
            execution: ExecutionResult) -> tuple[str, StageTrace]:
        start = time.perf_counter()
        usage: LLMUsage | None = None
        try:
            output = call_llm(
                self._model, self._prompt,
                build_summarize_input(question, sql, execution,
                                      preview_rows=self._preview_rows),
                parser=PARSER_TEXT,
                temperature=self._temperature,
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


__all__ = ["ResultSummaryStage", "skipped_trace", "SUMMARIZE_TEMPERATURE"]
