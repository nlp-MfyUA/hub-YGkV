"""显式 LangGraph SQL 图：确定性流水线和自主工具循环两种模式。

数据库、安全执行器、模型链和工具上下文来自 sql_agent_core。
pipeline: 选表 -> 生成 -> 校验 -> 执行 -> 总结，失败时有界重写。
agent: 模型 -> 工具 -> 模型，直到模型不再请求工具。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal, TypedDict

from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import ValidationError

from sql_agent_core import (
    AGENT_SYSTEM,
    Catalog,
    SQLToolContext,
    SQLWorkflow,
    SafeSQLite,
    SQLRejected,
    WorkflowError,
    build_chat_model,
)


class SQLState(TypedDict, total=False):
    question: str
    tables: list[str]
    sql: str
    result: dict[str, Any]
    answer: str
    attempt: int
    error: str | None
    trace: list[dict[str, Any]]


class LangGraphSQLAgent(SQLWorkflow):
    """校验、执行、重试和终止均由 StateGraph 编排。"""

    def __init__(self, db_path: str | Path, model: Any = None, *,
                 max_rewrites: int = 2, max_rows: int = 25,
                 timeout_seconds: float = 3.0):
        if max_rewrites < 0:
            raise ValueError("max_rewrites 不能小于 0")
        super().__init__(db_path, model=model, max_rewrites=max_rewrites,
                         max_rows=max_rows, timeout_seconds=timeout_seconds)
        self.graph = self._build_graph()

    @staticmethod
    def _trace(state: SQLState, event: dict[str, Any]) -> list[dict[str, Any]]:
        # 返回新列表，避免原地修改图状态。
        return [*state.get("trace", []), event]

    def _select_node(self, state: SQLState) -> dict[str, Any]:
        tables = self.select_tables(state["question"])
        return {"tables": tables,
                "trace": self._trace(state, {"stage": "table_select", "tables": tables})}

    def _generate_node(self, state: SQLState) -> dict[str, Any]:
        sql = self.generate_sql(state["question"], state["tables"])
        return {"sql": sql, "attempt": 1, "error": None,
                "trace": self._trace(state, {"stage": "sql_generate", "sql": sql})}

    def _failed(self, state: SQLState, exc: SQLRejected) -> dict[str, Any]:
        return {"error": str(exc), "trace": self._trace(state, {
            "stage": "sql_validate_or_execute_failed", "attempt": state["attempt"],
            "sql": state["sql"], "error": str(exc),
        })}

    def _validate_node(self, state: SQLState) -> dict[str, Any]:
        try:
            sql = self.sql_engine.validate(state["sql"], state["tables"])
        except SQLRejected as exc:
            return self._failed(state, exc)
        return {"sql": sql, "error": None, "trace": self._trace(state, {
            "stage": "sql_validate", "attempt": state["attempt"],
            "valid": True, "sql": sql,
        })}

    def _execute_node(self, state: SQLState) -> dict[str, Any]:
        try:
            result = self.sql_engine.execute(state["sql"], state["tables"])
        except SQLRejected as exc:
            return self._failed(state, exc)
        return {"result": result, "error": None, "trace": self._trace(state, {
            "stage": "sql_execute", "rows": len(result["rows"]),
            "truncated": result["truncated"],
        })}

    def _after_validate(self, state: SQLState) -> Literal["execute", "rewrite", "fail"]:
        return self._after_error(state) if state["error"] is not None else "execute"

    def _after_execute(self, state: SQLState) -> Literal["summarize", "rewrite", "fail"]:
        return self._after_error(state) if state["error"] is not None else "summarize"

    def _after_error(self, state: SQLState) -> Literal["rewrite", "fail"]:
        return "rewrite" if state["attempt"] <= self.max_rewrites else "fail"

    def _rewrite_node(self, state: SQLState) -> dict[str, Any]:
        sql = self.rewrite_sql(state["question"], state["tables"],
                               state["sql"], state["error"] or "")
        return {"sql": sql, "attempt": state["attempt"] + 1, "error": None,
                "trace": self._trace(state, {"stage": "sql_rewrite", "sql": sql})}

    def _fail_node(self, state: SQLState) -> dict[str, Any]:
        raise WorkflowError(
            f"SQL 在 {state['attempt']} 次尝试后仍未通过检查：{state['error']}"
        )

    def _summarize_node(self, state: SQLState) -> dict[str, Any]:
        return {"answer": self.summarize(state["question"], state["sql"], state["result"]),
                "trace": self._trace(state, {"stage": "result_summarize"})}

    def _build_graph(self):
        builder = StateGraph(SQLState)
        for name, node in {
            "select_tables": self._select_node, "generate": self._generate_node,
            "validate": self._validate_node, "execute": self._execute_node,
            "rewrite": self._rewrite_node, "fail": self._fail_node,
            "summarize": self._summarize_node,
        }.items():
            builder.add_node(name, node)
        builder.add_edge(START, "select_tables")
        builder.add_edge("select_tables", "generate")
        builder.add_edge("generate", "validate")
        builder.add_conditional_edges("validate", self._after_validate)
        builder.add_conditional_edges("execute", self._after_execute)
        builder.add_edge("rewrite", "validate")
        builder.add_edge("summarize", END)
        builder.add_edge("fail", END)
        return builder.compile()

    def run(self, question: str) -> dict[str, Any]:
        if not question or not question.strip():
            raise ValueError("问题不能为空")
        state = self.graph.invoke({"question": question, "trace": [{
            "stage": "database_parse", "tables_available": len(self.catalog.tables),
            "foreign_keys": len(self.catalog.fks),
        }]}, config={"recursion_limit": 10 + 3 * self.max_rewrites})
        return {key: state[key] for key in (
            "question", "tables", "sql", "result", "answer", "trace"
        )}


class LangGraphChinookAgent(SQLToolContext):
    """显式模型/工具循环，使用受限 SQL 工具和结构化输出。

    工具上下文保存在实例上；同一实例应串行调用 run()。
    工具按模型给出的顺序执行，保证同批 describe_tables 先于 run_sql 生效。
    """

    def __init__(self, db_path: str | Path, model: Any = None, *,
                 max_rows: int = 25, timeout_seconds: float = 3.0,
                 max_sql_calls: int = 6):
        self.catalog = Catalog(db_path)
        self.sql_engine = SafeSQLite(self.catalog, max_rows=max_rows,
                                     timeout_seconds=timeout_seconds)
        self.max_sql_calls = max_sql_calls
        self._reset()
        tools = self._build_tools()
        self._tools = {tool.name: tool for tool in tools}
        self.model = (model if model is not None else build_chat_model()).bind_tools(tools)
        builder = StateGraph(MessagesState)
        builder.add_node("model", self._model_node)
        builder.add_node("tools", self._tools_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", self._route, {"tools": "tools", "end": END})
        builder.add_edge("tools", "model")
        self.graph = builder.compile()
        self.agent = self.graph  # SQLToolContext.run() 使用此图，recursion_limit=30。

    def _model_node(self, state: MessagesState) -> dict[str, Any]:
        return {"messages": [self.model.invoke([
            SystemMessage(content=AGENT_SYSTEM), *state["messages"],
        ])]}

    @staticmethod
    def _route(state: MessagesState) -> Literal["tools", "end"]:
        return "tools" if state["messages"][-1].tool_calls else "end"

    def _tools_node(self, state: MessagesState) -> dict[str, Any]:
        messages = []
        for call in state["messages"][-1].tool_calls:
            tool = self._tools.get(call["name"])
            if tool is None:
                output = f"错误：未知工具 {call['name']}"
            else:
                try:
                    output = tool.invoke(call["args"])
                except ValidationError as exc:
                    output = f"错误：工具参数无效：{exc}"
            messages.append(ToolMessage(content=output, name=call["name"],
                                        tool_call_id=call["id"]))
        return {"messages": messages}


def main() -> None:
    parser = argparse.ArgumentParser(description="Chinook 文本转 SQL 智能体（LangGraph 版）")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--db", default=str(Path(__file__).parent / "chinook.db"))
    parser.add_argument("--max-rewrites", type=int, default=2)
    parser.add_argument("--mode", choices=("pipeline", "agent"), default="pipeline")
    args = parser.parse_args()
    question = args.question or input("请输入查询请求：")
    if args.mode == "agent":
        agent = LangGraphChinookAgent(args.db)
    else:
        agent = LangGraphSQLAgent(args.db, max_rewrites=args.max_rewrites)
    print(json.dumps(agent.run(question), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
