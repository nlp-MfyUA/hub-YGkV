"""LangGraph 编排：七个节点 + 一条改写重试回路（week13 · LangGraph 框架版）。

week12 已引入 LangGraph 的 StateGraph，但链层仍由 LCEL 预先组装（chains.py）；
week13 起 LangGraph 成为唯一编排框架，变化有三：

1. **图带 checkpointer 编译**——每个节点执行后自动落一个状态快照，
   每次运行是一个独立的 ``thread_id``，支持 get_state / get_state_history；
2. **节点内直调模型**——stage 不再持有 LCEL 链，改为在节点里
   ``call_llm(model, prompt, vars)``（见 llm_call.py）；
3. **流式友好**——``graph.stream(..., stream_mode="updates")`` 逐节点产出
   增量更新，经 :func:`serialize_update` 转成 JSON 可序列化事件后由
   SSE 推给前端（节点执行到一半就能看到进度）。

状态机拓扑（与 week11 / week12 逐边一致）：

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

语义约定（与 week11 / week12 一致）：
- 第 1 次尝试走「SQL 生成」，第 2 次起走「SQL 改写」（attempt 由节点推进）；
- 模型未返回可解析的 SQL：跳过校验/执行，直接进入改写路由；
- LLM 接口本身失败（鉴权/限流/网络）：立即短路，不再浪费改写调用；
- 重试预算 max_attempts 耗尽：返回失败与兜底说明，不抛异常；
- 每个节点的留痕（StageTrace）通过 ``operator.add`` reducer 汇入 state。
"""
from __future__ import annotations

import dataclasses
import operator
from typing import TYPE_CHECKING, Annotated, Any

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

# --------------------------------------------------------------- 节点名
NODE_DB_PARSER = "db_parser"
NODE_TABLE_SELECTOR = "table_selector"
NODE_SQL_GENERATE = "sql_generate"
NODE_SQL_REWRITE = "sql_rewrite"
NODE_SQL_VALIDATE = "sql_validate"
NODE_SQL_EXECUTE = "sql_execute"
NODE_SUMMARIZE = "summarize"
NODE_REWRITE_ROUTER = "rewrite_router"


class WorkflowState(TypedDict, total=False):
    """工作流状态（LangGraph state schema）。

    除 traces 用 ``operator.add`` reducer 累加外，其余字段都是「后者覆盖前者」
    的直接赋值；schema / execution 等复杂对象直接放内存态（LangGraph 不做拷贝）。

    每次运行对应一个 ``thread_id``（在 config 里传入），checkpointer 会把
    每个节点后的 state 快照持久化，因此运行结束后仍可回查（见
    :meth:`SqlAgentWorkflow.get_state`）。
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


# --------------------------------------------------------------- 序列化
def serialize_update(update: dict) -> dict:
    """把某节点返回的 state 增量转成 JSON 可序列化 dict（SSE 事件载荷）。

    ``stream_mode="updates"`` 产出的增量里可能带有 StageTrace /
    ExecutionResult / DatabaseSchema 等 dataclass 或自定义对象，
    这里统一降维：traces 逐条 asdict，execution asdict，schema 只留表名摘要。
    """
    payload: dict[str, Any] = {}
    for key, value in update.items():
        if key == "traces":
            payload[key] = [dataclasses.asdict(t) for t in value or []]
        elif key == "execution":
            payload[key] = dataclasses.asdict(value) if value else None
        elif key == "schema":
            payload[key] = ({"tables": list(value.tables)} if value is not None else None)
        else:
            payload[key] = value
    return payload


def serialize_state(values: dict) -> dict:
    """把 checkpointer 中的完整 state 快照转成 JSON 可序列化 dict。"""
    payload = serialize_update(values)
    if payload.get("traces") is None:
        payload["traces"] = []
    return payload


def build_graph(workflow: "SqlAgentWorkflow",
                checkpointer=None) -> "CompiledStateGraph":
    """基于 workflow 持有的各 stage 编译 LangGraph 状态机。

    checkpointer 为空时编译出的图不带持久化（仅适合一次性 invoke）；
    正常路径由 SqlAgentWorkflow 传入 MemorySaver / SqliteSaver。
    """
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
    graph.add_node(NODE_DB_PARSER, db_parser)
    graph.add_node(NODE_TABLE_SELECTOR, table_selector)
    graph.add_node(NODE_SQL_GENERATE, sql_generate)
    graph.add_node(NODE_SQL_REWRITE, sql_rewrite)
    graph.add_node(NODE_SQL_VALIDATE, sql_validate)
    graph.add_node(NODE_SQL_EXECUTE, sql_execute)
    graph.add_node(NODE_SUMMARIZE, summarize)
    graph.add_node(NODE_REWRITE_ROUTER, rewrite_router)

    graph.add_edge(START, NODE_DB_PARSER)
    graph.add_edge(NODE_DB_PARSER, NODE_TABLE_SELECTOR)
    graph.add_conditional_edges(
        NODE_TABLE_SELECTOR,
        lambda s: s["route"],
        {ROUTE_GENERATE: NODE_SQL_GENERATE, ROUTE_END: END},
    )
    graph.add_conditional_edges(
        NODE_SQL_GENERATE,
        lambda s: s["route"],
        {ROUTE_VALIDATE: NODE_SQL_VALIDATE, ROUTE_REWRITE_ROUTER: NODE_REWRITE_ROUTER},
    )
    graph.add_edge(NODE_SQL_REWRITE, NODE_SQL_VALIDATE)
    graph.add_conditional_edges(
        NODE_SQL_VALIDATE,
        lambda s: s["route"],
        {ROUTE_EXECUTE: NODE_SQL_EXECUTE, ROUTE_REWRITE_ROUTER: NODE_REWRITE_ROUTER},
    )
    graph.add_conditional_edges(
        NODE_SQL_EXECUTE,
        lambda s: s["route"],
        {ROUTE_SUMMARIZE: NODE_SUMMARIZE, ROUTE_REWRITE_ROUTER: NODE_REWRITE_ROUTER},
    )
    graph.add_edge(NODE_SUMMARIZE, END)
    graph.add_conditional_edges(
        NODE_REWRITE_ROUTER,
        lambda s: s["route"],
        {ROUTE_REWRITE: NODE_SQL_REWRITE, ROUTE_END: END},
    )
    return graph.compile(checkpointer=checkpointer)


__all__ = ["WorkflowState", "build_graph", "serialize_update", "serialize_state",
           "ROUTE_GENERATE", "ROUTE_VALIDATE", "ROUTE_EXECUTE", "ROUTE_SUMMARIZE",
           "ROUTE_REWRITE", "ROUTE_REWRITE_ROUTER", "ROUTE_END"]
