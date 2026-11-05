"""批量评测执行器：逐条跑工作流，与 gold SQL 的执行结果比对，计算指标。

指标定义：
- 执行成功率：工作流在重试预算内产出并成功执行 SQL 的比例；
- 结果正确率：执行结果与 gold SQL 结果一致的比例
  （exact = 列序敏感完全一致；loose = 忽略列内顺序后一致；两者都算正确）；
- 平均尝试次数 / 平均耗时 / token 用量 / 触发改写重试的条数。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from langchain_core.language_models.chat_models import BaseChatModel

from sql_agent.config import Config
from sql_agent.llm import chat_model_name
from sql_agent.models import WorkflowResult
from sql_agent.stages.sql_executor import execute_readonly
from sql_agent.workflow import SqlAgentWorkflow

from .test_queries import TestQuery

MATCH_EXACT = "exact"
MATCH_LOOSE = "loose"
MATCH_MISMATCH = "mismatch"
MATCH_GOLD_ERROR = "gold_error"


@dataclass
class QueryOutcome:
    query: TestQuery
    result: WorkflowResult
    gold_columns: list[str] = field(default_factory=list)
    gold_rows: list[tuple] = field(default_factory=list)
    gold_error: str = ""
    match: str = MATCH_MISMATCH
    match_detail: str = ""


@dataclass
class EvalMetrics:
    total: int = 0
    exec_success: int = 0
    exact_match: int = 0
    loose_match: int = 0
    avg_attempts: float = 0.0
    avg_duration_ms: float = 0.0
    total_tokens: int = 0
    retried: int = 0                     # 触发改写重试（attempts > 1）的条数
    stage_error_counts: Counter = field(default_factory=Counter)

    @property
    def correct(self) -> int:
        return self.exact_match + self.loose_match

    @property
    def exec_rate(self) -> float:
        return self.exec_success / self.total if self.total else 0.0

    @property
    def correct_rate(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass
class EvalReport:
    started_at: datetime
    finished_at: datetime
    provider: str
    model: str
    max_attempts: int
    outcomes: list[QueryOutcome]
    metrics: EvalMetrics


def _norm_value(value):
    if isinstance(value, float):
        return round(value, 2)
    return value


def _sort_key(value):
    """把单元格值转成可跨行 / 跨类型安全比较的规范键。

    - None / 数值 / 文本各归一类，避免 int 与 str 直接比较报 TypeError；
    - 数值统一格式化为字符串，使 int 3 与 float 3.0 视为相等；
    - float 先四舍五入到 2 位，容忍 SUM/AVG 的浮点尾差。
    """
    v = _norm_value(value)
    if v is None:
        return (0, "")
    if isinstance(v, bool):
        return (1, "1" if v else "0")
    if isinstance(v, (int, float)):
        return (2, f"{float(v):.4f}")
    return (3, str(v))


def _norm_rows(rows: list[tuple]) -> list[tuple]:
    return sorted(tuple(_sort_key(v) for v in row) for row in rows)


def _norm_rows_loose(rows: list[tuple]) -> list[tuple]:
    """忽略同一行内列顺序的归一化（容忍模型调整输出列顺序）。"""
    return sorted(tuple(sorted(_sort_key(v) for v in row)) for row in rows)


def compare_results(gold_columns, gold_rows, gold_error,
                    result: WorkflowResult | None) -> tuple[str, str]:
    if gold_error:
        return MATCH_GOLD_ERROR, f"gold SQL 执行失败: {gold_error}"
    if result is None or not result.success or result.execution is None:
        reason = result.error if result else "无结果"
        return MATCH_MISMATCH, f"工作流未产出可执行结果（{reason}）"
    actual = result.execution
    if _norm_rows(gold_rows) == _norm_rows(actual.rows):
        return MATCH_EXACT, f"结果集完全一致（{len(gold_rows)} 行，列序敏感）"
    if _norm_rows_loose(gold_rows) == _norm_rows_loose(actual.rows):
        return MATCH_LOOSE, f"结果集一致（{len(gold_rows)} 行，忽略列内顺序）"
    return MATCH_MISMATCH, (
        f"gold {len(gold_rows)} 行 vs 实际 {actual.row_count} 行，内容不一致"
    )


def run_eval(config: Config, llm: BaseChatModel, queries: list[TestQuery],
             *, on_progress=None) -> EvalReport:
    workflow = SqlAgentWorkflow(config, llm)
    started_at = datetime.now()
    outcomes: list[QueryOutcome] = []

    for index, query in enumerate(queries, start=1):
        result = workflow.run(query.question)

        gold = execute_readonly(
            config.db.path, query.gold_sql,
            row_limit=config.eval.row_limit,
            timeout_seconds=config.eval.query_timeout_seconds,
        )
        outcome = QueryOutcome(query=query, result=result)
        if gold.ok:
            outcome.gold_columns = gold.columns
            outcome.gold_rows = gold.rows
        else:
            outcome.gold_error = gold.error
        outcome.match, outcome.match_detail = compare_results(
            outcome.gold_columns, outcome.gold_rows, outcome.gold_error, result
        )
        outcomes.append(outcome)
        if on_progress:
            on_progress(index, len(queries), outcome)

    metrics = _compute_metrics(outcomes)
    return EvalReport(
        started_at=started_at,
        finished_at=datetime.now(),
        provider=config.llm.provider,
        model=chat_model_name(llm),
        max_attempts=config.eval.max_attempts,
        outcomes=outcomes,
        metrics=metrics,
    )


def _compute_metrics(outcomes: list[QueryOutcome]) -> EvalMetrics:
    metrics = EvalMetrics(total=len(outcomes))
    durations: list[float] = []
    attempts: list[int] = []
    for outcome in outcomes:
        result = outcome.result
        if result.success:
            metrics.exec_success += 1
        if result.attempts > 1:
            metrics.retried += 1
        attempts.append(result.attempts)
        durations.append(result.total_duration_ms)
        metrics.total_tokens += result.usage.total_tokens
        if outcome.match == MATCH_EXACT:
            metrics.exact_match += 1
        elif outcome.match == MATCH_LOOSE:
            metrics.loose_match += 1
        for trace in result.traces:
            if trace.status == "error":
                metrics.stage_error_counts[trace.stage] += 1
    metrics.avg_attempts = sum(attempts) / len(attempts) if attempts else 0.0
    metrics.avg_duration_ms = sum(durations) / len(durations) if durations else 0.0
    return metrics


__all__ = ["EvalReport", "EvalMetrics", "QueryOutcome", "run_eval",
           "compare_results", "MATCH_EXACT", "MATCH_LOOSE", "MATCH_MISMATCH"]
