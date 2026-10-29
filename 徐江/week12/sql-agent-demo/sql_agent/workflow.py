"""SqlAgentWorkflow：组装各 stage + LangGraph 状态机，对外保持与 week11
一致的调用接口（prepare / run），内部编排改为 LangGraph 驱动。

    workflow = SqlAgentWorkflow(config, chat_model)
    result = workflow.run("每个城市有多少用户？")

- __init__：建链（LCEL）→ 建七个 stage → 编译 LangGraph（只编译一次）；
- prepare：解析并缓存 schema（批量评测只解析一次）；
- run：invoke 状态图 → 把最终 state 组装成 WorkflowResult。
"""
from __future__ import annotations

import time
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel

from .chains import build_chains
from .config import Config
from .db import DatabaseSchema, build_database
from .graph import WorkflowState, build_graph
from .models import (STATUS_OK, LLMUsage, StageTrace, WorkflowResult)
from .stages.db_parser import DatabaseParserStage
from .stages.sql_executor import SqlExecutionStage
from .stages.sql_generator import SqlGenerationStage
from .stages.sql_rewriter import SqlRewriteStage
from .stages.sql_validator import SqlValidationStage
from .stages.summarizer import ResultSummaryStage
from .stages.table_selector import TableSelectionStage


class SqlAgentWorkflow:
    """固定流程 SQL Agent：七个 stage + 一条改写重试边（LangGraph 编排）。"""

    def __init__(self, config: Config, model: BaseChatModel):
        self._config = config
        self._model = model
        self._db_path = Path(config.db.path)
        self.max_attempts = config.eval.max_attempts
        self.summarize_enabled = config.eval.summarize

        # ---- LCEL 链（prompt | model | parser），四条 ----------------------
        chains = build_chains(model)

        # ---- 七个 stage ----------------------------------------------------
        self.parser = DatabaseParserStage(self._db_path)
        self.selector = TableSelectionStage(chains["select_tables"])
        self.generator = SqlGenerationStage(chains["generate_sql"])
        self.rewriter = SqlRewriteStage(chains["rewrite_sql"])
        self.validator: SqlValidationStage | None = None  # schema 解析后创建
        self.executor = SqlExecutionStage(
            self._db_path,
            row_limit=config.eval.row_limit,
            timeout_seconds=config.eval.query_timeout_seconds,
        )
        self.summarizer = ResultSummaryStage(chains["summarize"])

        # ---- LangGraph 状态机（编译一次，每次 run 复用）--------------------
        self._graph = build_graph(self)

        self._schema: DatabaseSchema | None = None  # schema 缓存（批量评测只解析一次）

    # ------------------------------------------------------------------ 准备
    def prepare(self) -> tuple[DatabaseSchema, StageTrace]:
        """解析并缓存 schema，返回 (schema, 留痕)。

        缓存命中时不重复解析（批量评测 15 条问题只解析一次库结构），
        并顺带确保校验 stage 就绪。
        """
        if self._schema is not None:
            cached = StageTrace(
                stage=self.parser.name, status=STATUS_OK,
                input_brief=str(self._db_path),
                output_brief=f"{len(self._schema.tables)} 张表（缓存）",
                detail="schema 已在首次查询时解析，批量运行复用",
            )
            return self._schema, cached
        build_database(self._db_path)  # 确保示例库存在
        schema, trace = self.parser.run()
        self._schema = schema
        self.validator = SqlValidationStage(self._db_path, schema=schema)
        return schema, trace

    # ------------------------------------------------------------------ 运行
    def run(self, question: str) -> WorkflowResult:
        t0 = time.perf_counter()
        initial: WorkflowState = {
            "question": question,
            "attempt": 0,
            "sql": "",
            "tables": [],
            "last_error": "",
            "llm_failed": False,
            "success": False,
            "error": "",
            "summary": "",
            "route": "",
            "traces": [],
        }
        final = self._graph.invoke(initial)

        traces = final.get("traces") or []
        usage = LLMUsage()
        for trace in traces:
            usage.add_trace(trace)
        return WorkflowResult(
            question=question,
            success=bool(final.get("success")),
            final_sql=final.get("sql", ""),
            attempts=final.get("attempt", 0),
            traces=traces,
            execution=final.get("execution"),
            summary=final.get("summary", ""),
            error=final.get("error", ""),
            total_duration_ms=(time.perf_counter() - t0) * 1000,
            usage=usage,
        )


__all__ = ["SqlAgentWorkflow"]
