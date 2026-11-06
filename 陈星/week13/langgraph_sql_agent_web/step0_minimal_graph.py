"""先学一个没有 LLM、没有数据库的最小 LangGraph：只认识 State / Node / Edge。"""
from typing import TypedDict
from langgraph.graph import StateGraph, START, END


class State(TypedDict):
    question: str
    answer: str


def understand(state: State) -> dict:
    return {"answer": f"收到问题：{state['question']}"}


def add_suffix(state: State) -> dict:
    return {"answer": state["answer"] + "；我已经处理完成。"}


builder = StateGraph(State)
builder.add_node("understand", understand)
builder.add_node("add_suffix", add_suffix)
builder.add_edge(START, "understand")
builder.add_edge("understand", "add_suffix")
builder.add_edge("add_suffix", END)

graph = builder.compile()
print(graph.invoke({"question": "什么是 LangGraph？", "answer": ""}))
