"""SqlAgentWorkflow：组装各 stage + 驱动 LangGraph 状态机（week13 · LangGraph 框架版）。

week13 起工作流即「一张带持久化的图」：编译时挂上 checkpointer，
每次运行分配独立 thread_id，因此除 run() 之外还天然获得三个能力：

    workflow = SqlAgentWorkflow(config, chat_model)

    # 1. 一次性运行（与 week11/12 行为一致）
    result = workflow.run("每个城市有多少用户？")

    # 2. 逐节点流式驱动（SSE 实时进度）：产出 (节点名, 增量更新)
    for node, update in workflow.stream("...", thread_id=tid):
        ...

    # 3. 运行后回查某线程的最终状态 / 状态历史（checkpointer 里读）
    state = workflow.get_state(thread_id)
    history = workflow.state_history(thread_id)

    # 4. 导出状态机的 Mermaid 图（图即代码，可读可画）
    mermaid = workflow.mermaid()

调用接口与 week11/12 保持兼容：eval.runner 与 CLI 仍只用 prepare/run。
"""
from __future__ import annotations

import dataclasses
import time
import uuid
from pathlib import Path
from typing import Iterator

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from .checkpoint import create_memory_checkpointer
from .config import Config
from .db import DatabaseSchema, build_database
from .graph import WorkflowState, build_graph, serialize_state, serialize_update
from .llm_call import PARSER_JSON, PARSER_SQL, PARSER_TEXT
from .models import (STATUS_OK, LLMUsage, StageTrace, WorkflowResult)
from .prompts import (GENERATE_SQL_PROMPT, REWRITE_SQL_PROMPT, SELECT_TABLES_PROMPT,
                      SUMMARIZE_PROMPT)
from .stages.db_parser import DatabaseParserStage
from .stages.sql_executor import SqlExecutionStage
from .stages.sql_generator import SqlGenerationStage
from .stages.sql_rewriter import SqlRewriteStage
from .stages.sql_validator import SqlValidationStage
from .stages.summarizer import ResultSummaryStage
from .stages.table_selector import TableSelectionStage

# 汇总阶段的温度（与 week11/12 一致：结论生成允许一点发散）
SUMMARIZE_TEMPERATURE = 0.3


class SqlAgentWorkflow:
    """固定流程 SQL Agent：七个 stage + 一条改写重试边（LangGraph 编排）。"""

    def __init__(self, config: Config, model: BaseChatModel,
                 checkpointer: BaseCheckpointSaver | None = None):
        self._config = config
        self._model = model
        self._db_path = Path(config.db.path)
        self.max_attempts = config.eval.max_attempts
        self.summarize_enabled = config.eval.summarize

        # ---- 七个 stage（LLM stage 持模型 + 模板，节点内直调，见 llm_call.py）----
        self.parser = DatabaseParserStage(self._db_path)
        self.selector = TableSelectionStage(model, SELECT_TABLES_PROMPT)
        self.generator = SqlGenerationStage(model, GENERATE_SQL_PROMPT)
        self.rewriter = SqlRewriteStage(model, REWRITE_SQL_PROMPT)
        self.validator: SqlValidationStage | None = None  # schema 解析后创建
        self.executor = SqlExecutionStage(
            self._db_path,
            row_limit=config.eval.row_limit,
            timeout_seconds=config.eval.query_timeout_seconds,
        )
        self.summarizer = ResultSummaryStage(
            model, SUMMARIZE_PROMPT, temperature=SUMMARIZE_TEMPERATURE
        )

        # ---- LangGraph 状态机（编译一次，每次 run 复用）--------------------
        # checkpointer 让「每次运行 = 一个 thread」可回放、可回查；
        # 缺省用进程内 MemorySaver（含自定义类型序列化白名单），
        # 可通过配置/参数切换到 SqliteSaver 落库（见 checkpoint.py）。
        self._checkpointer: BaseCheckpointSaver = checkpointer or create_memory_checkpointer()
        self._graph = build_graph(self, checkpointer=self._checkpointer)

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
    @staticmethod
    def new_thread_id() -> str:
        """LangGraph 的线程标识：每次运行一个，互不串状态。"""
        return uuid.uuid4().hex

    @staticmethod
    def _thread_config(thread_id: str) -> dict:
        return {"configurable": {"thread_id": thread_id}}

    def _initial_state(self, question: str) -> WorkflowState:
        return {
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

    def run(self, question: str, *, thread_id: str | None = None) -> WorkflowResult:
        """invoke 状态图 → 把最终 state 组装成 WorkflowResult。

        thread_id 缺省自动生成；显式传入同名线程会从上次 checkpoint 续跑
        （traces 通过 operator.add 累加，演示时一般每次都用新线程）。
        """
        t0 = time.perf_counter()
        tid = thread_id or self.new_thread_id()
        final = self._graph.invoke(self._initial_state(question),
                                   config=self._thread_config(tid))
        result = self._to_result(question, final, t0, thread_id=tid)
        return result

    def stream(self, question: str, *,
               thread_id: str | None = None) -> Iterator[tuple[str, dict]]:
        """逐节点流式驱动状态图，产出 (节点名, 序列化后的增量更新)。

        用法（后端 SSE 路由即按此实现）：

            for node, update in workflow.stream(question):
                send_sse({"node": node, "update": update})
            # 循环结束后再取最终结果（见 _finalize）

        末位固定产出 ("__end__", {"thread_id": ..., "result": ...})，
        方便调用方收尾；异常会原样抛出，由调用方转成错误事件。
        """
        t0 = time.perf_counter()
        tid = thread_id or self.new_thread_id()
        config = self._thread_config(tid)
        for chunk in self._graph.stream(self._initial_state(question),
                                        config=config, stream_mode="updates"):
            for node, update in chunk.items():
                yield node, serialize_update(update)
        # 流结束：从 checkpointer 取最终 state，组装完整结果
        snapshot = self._graph.get_state(config)
        values = snapshot.values if snapshot else {}
        result = self._to_result(question, values, t0, thread_id=tid)
        yield "__end__", {"thread_id": tid, "result": dataclasses.asdict(result)}

    # ------------------------------------------------------------------ 回查
    def get_state(self, thread_id: str) -> dict | None:
        """从 checkpointer 读取某线程的最终状态快照（JSON 可序列化）。"""
        snapshot = self._graph.get_state(self._thread_config(thread_id))
        if snapshot is None or not snapshot.values:
            return None
        return serialize_state(snapshot.values)

    def state_history(self, thread_id: str) -> list[dict]:
        """某线程的状态历史（每个 checkpoint 一条，新的在前）。"""
        history = self._graph.get_state_history(self._thread_config(thread_id))
        return [
            {
                "step": h.metadata.get("step"),
                "source": h.metadata.get("source"),
                "next": list(h.next or ()),
                "traces": len(h.values.get("traces") or []) if h.values else 0,
            }
            for h in history
        ]

    def mermaid(self) -> str:
        """导出状态机的 Mermaid 图（图即代码）。"""
        return self._graph.get_graph().draw_mermaid()

    # ------------------------------------------------------------------ 内部
    def _to_result(self, question: str, final: dict, t0: float,
                   *, thread_id: str) -> WorkflowResult:
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
            thread_id=thread_id,
        )


# --------------------------------------------------------------- 序列化助手
__all__ = ["SqlAgentWorkflow", "SUMMARIZE_TEMPERATURE",
           "PARSER_JSON", "PARSER_SQL", "PARSER_TEXT"]
