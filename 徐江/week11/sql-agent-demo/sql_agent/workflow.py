"""固定流程的 SQL Agent 工作流编排。

每次运行都经过同一条固定流水线，唯一的回路是「校验失败 / 执行报错 → 改写 → 重试」：

     ┌──────────────────────────────────────────────────────────────┐
     │                     SqlAgentWorkflow                         │
     ▼                                                              │
 [1]数据库解析 ─► [2]Table选择 ─► [3]SQL生成 ─► [4]SQL校验 ─► [6]SQL执行 ─► [7]结果汇总
                                            │ 失败          │ 报错
                                            ▼               ▼
                                        [5]SQL改写 ◄────────┘
                                            （携带错误信息，最多重试 max_attempts 次）

约定：
- 第 1 次尝试调用「SQL 生成」，第 2 次及以后调用「SQL 改写」；
- 任一阶段产生 LLM 调用都会记录 token 用量；
- 重试耗尽后返回 success=False 与兜底说明，不抛异常。
"""
from __future__ import annotations

import time
from pathlib import Path

from .config import Config
from .db import build_database
from .llm import BaseLLMClient
from .models import (STATUS_ERROR, STATUS_OK, STAGE_SQL_EXECUTE, STAGE_SQL_VALIDATE,
                     LLMUsage, StageTrace, WorkflowResult)
from .stages.db_parser import DatabaseParserStage
from .stages.sql_executor import SqlExecutionStage
from .stages.sql_generator import SqlGenerationStage
from .stages.sql_rewriter import SqlRewriteStage
from .stages.sql_validator import SqlValidationStage
from .stages.summarizer import ResultSummaryStage, skipped_trace
from .stages.table_selector import TableSelectionStage


class SqlAgentWorkflow:
    """固定流程 SQL Agent：七个 stage + 一条改写重试边。"""

    def __init__(self, config: Config, llm: BaseLLMClient):
        self._config = config
        self._llm = llm
        self._db_path = Path(config.db.path)
        self._max_attempts = config.eval.max_attempts

        self._parser = DatabaseParserStage(self._db_path)
        self._selector = TableSelectionStage(llm)
        self._generator = SqlGenerationStage(llm, temperature=config.llm.temperature)
        self._rewriter = SqlRewriteStage(llm, temperature=config.llm.temperature)
        self._validator: SqlValidationStage | None = None  # schema 解析后创建
        self._executor = SqlExecutionStage(
            self._db_path,
            row_limit=config.eval.row_limit,
            timeout_seconds=config.eval.query_timeout_seconds,
        )
        self._summarizer = ResultSummaryStage(llm)
        self._summarize_enabled = config.eval.summarize

        self._schema = None  # 数据库解析结果缓存（批量评测只解析一次）

    # ------------------------------------------------------------------ 准备
    def prepare(self) -> tuple[StageTrace, bool]:
        """解析并缓存 schema。返回 (留痕, 是否为本次新解析)。"""
        if self._schema is not None:
            cached = StageTrace(
                stage=self._parser.name, status=STATUS_OK,
                input_brief=str(self._db_path),
                output_brief=f"{len(self._schema.tables)} 张表（缓存）",
                detail="schema 已在首次查询时解析，批量运行复用",
            )
            return cached, False
        build_database(self._db_path)  # 确保示例库存在
        schema, trace = self._parser.run()
        self._schema = schema
        self._validator = SqlValidationStage(self._db_path, schema=schema)
        return trace, True

    # ------------------------------------------------------------------ 运行
    def run(self, question: str) -> WorkflowResult:
        t0 = time.perf_counter()
        traces: list[StageTrace] = []
        usage = LLMUsage()

        parse_trace, _ = self.prepare()
        traces.append(parse_trace)

        # ---- Stage 2 · Table 选择 -----------------------------------------
        tables, trace = self._selector.run(question, self._schema)
        traces.append(trace)
        usage.add_trace(trace)
        if not tables:
            return self._failure(question, traces, usage, t0,
                                 "Table 选择失败：未能确定相关表")

        # ---- 重试循环：生成 / 改写 → 校验 → 执行 ---------------------------
        last_error = ""
        sql = ""
        execution = None
        exhausted = True
        for attempt in range(1, self._max_attempts + 1):
            if attempt == 1:
                sql, trace = self._generator.run(question, self._schema, tables, attempt)
            else:
                sql, trace = self._rewriter.run(question, self._schema, tables,
                                                sql, last_error, attempt)
            traces.append(trace)
            usage.add_trace(trace)
            if not sql:
                last_error = trace.detail or "模型未返回可解析的 SQL"
                if trace.llm_failed:
                    # LLM 接口本身不可用（鉴权/限流/网络），继续改写只是浪费调用
                    exhausted = False
                    break
                continue

            # ---- Stage 4 · SQL 校验 ---------------------------------------
            validation = self._validator.validate(sql)
            traces.append(StageTrace(
                stage=STAGE_SQL_VALIDATE,
                status=STATUS_OK if validation.ok else STATUS_ERROR,
                input_brief=sql,
                output_brief="通过" if validation.ok else "未通过",
                detail=validation.checks_summary() if validation.ok else validation.error,
                attempt=attempt,
            ))
            if not validation.ok:
                last_error = validation.error
                continue

            # ---- Stage 6 · SQL 执行 ---------------------------------------
            execution, trace = self._executor.run(sql, attempt)
            traces.append(trace)
            if not execution.ok:
                last_error = execution.error
                continue

            # ---- Stage 7 · 结果汇总 ---------------------------------------
            summary = ""
            if self._summarize_enabled:
                summary, trace = self._summarizer.run(question, sql, execution)
                traces.append(trace)
                usage.add_trace(trace)
            else:
                traces.append(skipped_trace())

            return WorkflowResult(
                question=question,
                success=True,
                final_sql=sql,
                attempts=attempt,
                traces=traces,
                execution=execution,
                summary=summary,
                total_duration_ms=(time.perf_counter() - t0) * 1000,
                usage=usage,
            )

        if exhausted:
            error = f"超过最大尝试次数（{self._max_attempts}），最后错误: {last_error}"
        else:
            error = f"LLM 接口不可用，工作流中止: {last_error}"
        return self._failure(
            question, traces, usage, t0, error,
            final_sql=sql, attempts=attempt,
        )

    # ------------------------------------------------------------------ 内部
    def _failure(self, question, traces, usage, t0, error, *,
                 final_sql: str = "", attempts: int = 0) -> WorkflowResult:
        return WorkflowResult(
            question=question,
            success=False,
            final_sql=final_sql,
            attempts=attempts,
            traces=traces,
            error=error,
            total_duration_ms=(time.perf_counter() - t0) * 1000,
            usage=usage,
        )


__all__ = ["SqlAgentWorkflow"]
