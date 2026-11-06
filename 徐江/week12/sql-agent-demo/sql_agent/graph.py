"""LangGraph 编排：七个节点 + 一条改写重试回路。

week11 版是手写 for 循环 + break/continue；week12 版改用 LangGraph 的
StateGraph 把同一条流水线声明式地表达出来——节点即 stage，条件边即
「校验失败 / 执行报错 → 改写 → 重试」回路：

    START ─► db_parser ─► table_selector ─┬─(未选到表)──────────────► END(失败)
                                          └─► sql_generate ─┬─(无SQL)─┐
                                                              │         ▼
                                                    (有SQL)─►│   sql_validate ─┬─(未通过)─► rewrite_router
                                                              │                 │
                                                              │         (通过)─►│ sql_execute ─┬─(报错)─► rewrite_router
                                                              │                 │              │
                                                              │                 │      (成功)─►│ summarize ─► END(成功)
                                                              ▼                 ▼              ▼
                                                    rewrite_router ◄──────────────────────────┘
                                                      ├─(LLM 不可用 / 次数耗尽)──► END(失败)
                                                      └─► sql_rewrite ─► sql_validate（回边）

语义与 week11 逐条对应：
- 第 1 次尝试走「SQL 生成」，第 2 次起走「SQL 改写」（attempt 由节点推进）；
- 模型未返回可解析的 SQL：跳过校验/执行，直接进入改写路由；
- LLM 接口本身失败（鉴权/限流/网络）：立即短路，不再浪费改写调用；
- 重试预算 max_attempts 耗尽：返回失败与兜底说明，不抛异常；
- 每个节点的留痕（StageTrace）通过 ``operator.add`` reducer 汇入 state。
"""
from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Annotated

from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from .models import (STATUS_ERROR, STATUS_OK, STAGE_SQL_VALIDATE, StageTrace)
from .stages.summarizer import skipped_trace

if TYPE_CHECKING:  # 避免循环导入：graph.py 只依赖 SqlAgentWorkflow 的实例
    from langgraph.graph.state import CompiledStateGraph

    from .workflow import SqlAgentWorkflow


# --------------------------------------------------------------- 路由键
ROUTE_GENERATE = "generate"        # 去 SQL 生成
ROUTE_VALIDATE = "validate"        # 去 SQL 校验
ROUTE_EXECUTE = "execute"          # 去 SQL 执行
ROUTE_SUMMARIZE = "summarize"      # 去结果汇总
ROUTE_REWRITE = "rewrite"          # 去 SQL 改写
ROUTE_REWRITE_ROUTER = "router"    # 去改写路由
ROUTE_END = "end"                  # 结束（失败）


class WorkflowState(TypedDict, total=False):
    """工作流状态（LangGraph state schema）。

    除 traces 用 ``operator.add`` reducer 累加外，其余字段都是「后者覆盖前者」
    的直接赋值；schema / execution 等复杂对象直接放内存态（LangGraph 不做拷贝）。
    """

    question: str
    schema: object                          # DatabaseSchema（db_parser 节点产出）
    tables: list[str]
    sql: str
    attempt: int                            # 生成 + 改写的总尝试次数
    last_error: str                         # 最近一次失败原因（喂给改写阶段）
    llm_failed: bool                        # LLM 接口本身失败 → 短路
    success: bool
    error: str                              # 失败时的兜底说明
    execution: object                       # ExecutionResult（成功时）
    summary: str
    route: str                              # 条件边路由键
    traces: Annotated[list[StageTrace], operator.add]


def build_graph(workflow: "SqlAgentWorkflow") -> "CompiledStateGraph":
    """基于 workflow 持有的各 stage 编译 LangGraph 状态机。"""
    max_attempts = workflow.max_attempts
    summarize_enabled = workflow.summarize_enabled

    # ================================================================ 节点
    def db_parser(state: WorkflowState) -> dict:
        """Stage 1 · 数据库解析（schema 跨次运行缓存）。"""
        schema, trace = workflow.prepare()
        return {"traces": [trace], "schema": schema}

    def table_selector(state: WorkflowState) -> dict:
        """Stage 2 · Table 选择。"""
        tables, trace = workflow.selector.run(state["question"], state["schema"])
        update: dict = {"traces": [trace], "tables": tables}
        if not tables:
            update["error"] = "Table 选择失败：未能确定相关表"
            update["success"] = False
            update["route"] = ROUTE_END
        else:
            update["route"] = ROUTE_GENERATE
        return update

    def sql_generate(state: WorkflowState) -> dict:
        """Stage 3 · SQL 生成（第 1 次尝试）。"""
        attempt = state["attempt"] + 1
        sql, trace = workflow.generator.run(
            state["question"], state["schema"], state["tables"], attempt
        )
        update: dict = {"traces": [trace], "sql": sql, "attempt": attempt}
        if sql:
            update["last_error"] = ""
            update["llm_failed"] = False
            update["route"] = ROUTE_VALIDATE
        else:
            # 模型未返回可解析的 SQL：跳过校验/执行，进入改写路由
            update["last_error"] = trace.detail or "模型未返回可解析的 SQL"
            update["llm_failed"] = trace.llm_failed
            update["route"] = ROUTE_REWRITE_ROUTER
        return update

    def sql_rewrite(state: WorkflowState) -> dict:
        """Stage 5 · SQL 改写（第 2 次及以后的尝试）。"""
        attempt = state["attempt"] + 1
        sql, trace = workflow.rewriter.run(
            state["question"], state["schema"], state["tables"],
            state["sql"], state["last_error"], attempt,
        )
        update: dict = {"traces": [trace], "sql": sql, "attempt": attempt}
        if sql:
            update["last_error"] = ""
            update["llm_failed"] = False
            update["route"] = ROUTE_VALIDATE
        else:
            update["last_error"] = trace.detail or "模型未返回可解析的 SQL"
            update["llm_failed"] = trace.llm_failed
            update["route"] = ROUTE_REWRITE_ROUTER
        return update

    def sql_validate(state: WorkflowState) -> dict:
        """Stage 4 · SQL 校验（纯静态 + 语义预检，不调用 LLM）。"""
        validation = workflow.validator.validate(state["sql"])
        trace = StageTrace(
            stage=STAGE_SQL_VALIDATE,
            status=STATUS_OK if validation.ok else STATUS_ERROR,
            input_brief=state["sql"],
            output_brief="通过" if validation.ok else "未通过",
            detail=validation.checks_summary() if validation.ok else validation.error,
            attempt=state["attempt"],
        )
        update: dict = {"traces": [trace]}
        if validation.ok:
            update["last_error"] = ""
            update["route"] = ROUTE_EXECUTE
        else:
            update["last_error"] = validation.error
            update["route"] = ROUTE_REWRITE_ROUTER
        return update

    def sql_execute(state: WorkflowState) -> dict:
        """Stage 6 · SQL 执行。"""
        execution, trace = workflow.executor.run(state["sql"], state["attempt"])
        update: dict = {"traces": [trace]}
        if execution.ok:
            update["execution"] = execution
            update["route"] = ROUTE_SUMMARIZE
        else:
            update["last_error"] = execution.error
            update["route"] = ROUTE_REWRITE_ROUTER
        return update

    def summarize(state: WorkflowState) -> dict:
        """Stage 7 · 结果汇总（可配置关闭）。"""
        if summarize_enabled:
            summary, trace = workflow.summarizer.run(
                state["question"], state["sql"], state["execution"]
            )
            update: dict = {"traces": [trace], "summary": summary}
        else:
            update = {"traces": [skipped_trace()], "summary": ""}
        update["success"] = True
        update["error"] = ""
        return update

    def rewrite_router(state: WorkflowState) -> dict:
        """改写路由：决定继续改写还是收尾（LLM 不可用 / 次数耗尽）。"""
        if state.get("llm_failed"):
            return {
                "error": f"LLM 接口不可用，工作流中止: {state.get('last_error', '')}",
                "success": False,
                "route": ROUTE_END,
            }
        if state["attempt"] >= max_attempts:
            return {
                "error": (f"超过最大尝试次数（{max_attempts}），"
                          f"最后错误: {state.get('last_error', '')}"),
                "success": False,
                "route": ROUTE_END,
            }
        return {"route": ROUTE_REWRITE}

    # ================================================================ 建图
    graph = StateGraph(WorkflowState)
    graph.add_node("db_parser", db_parser)
    graph.add_node("table_selector", table_selector)
    graph.add_node("sql_generate", sql_generate)
    graph.add_node("sql_rewrite", sql_rewrite)
    graph.add_node("sql_validate", sql_validate)
    graph.add_node("sql_execute", sql_execute)
    graph.add_node("summarize", summarize)
    graph.add_node("rewrite_router", rewrite_router)

    graph.add_edge(START, "db_parser")
    graph.add_edge("db_parser", "table_selector")
    graph.add_conditional_edges(
        "table_selector",
        lambda s: s["route"],
        {ROUTE_GENERATE: "sql_generate", ROUTE_END: END},
    )
    graph.add_conditional_edges(
        "sql_generate",
        lambda s: s["route"],
        {ROUTE_VALIDATE: "sql_validate", ROUTE_REWRITE_ROUTER: "rewrite_router"},
    )
    graph.add_edge("sql_rewrite", "sql_validate")
    graph.add_conditional_edges(
        "sql_validate",
        lambda s: s["route"],
        {ROUTE_EXECUTE: "sql_execute", ROUTE_REWRITE_ROUTER: "rewrite_router"},
    )
    graph.add_conditional_edges(
        "sql_execute",
        lambda s: s["route"],
        {ROUTE_SUMMARIZE: "summarize", ROUTE_REWRITE_ROUTER: "rewrite_router"},
    )
    graph.add_edge("summarize", END)
    graph.add_conditional_edges(
        "rewrite_router",
        lambda s: s["route"],
        {ROUTE_REWRITE: "sql_rewrite", ROUTE_END: END},
    )
    return graph.compile()


__all__ = ["WorkflowState", "build_graph"]
