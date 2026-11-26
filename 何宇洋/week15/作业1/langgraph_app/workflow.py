"""后端：START → 进程1 → 条件边 → 进程2(鼓励/排解) → END。"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    text: str
    analysis: dict
    strategy: str
    reply: str


def build_workflow(rpc):
    async def classify(state):
        analysis = await rpc("sentiment", "/classify", {"text": state["text"]})
        return {"analysis": analysis}

    async def respond(state, strategy):
        result = await rpc("response", "/respond", {
            "text": state["text"], "analysis": state["analysis"],
        })
        return {"reply": result["reply"], "strategy": strategy}

    async def encourage(state):
        return await respond(state, "encourage")

    async def comfort(state):
        return await respond(state, "comfort")

    builder = StateGraph(State)
    builder.add_node("classify", classify)
    builder.add_node("encourage", encourage)
    builder.add_node("comfort", comfort)
    builder.add_edge(START, "classify")
    builder.add_conditional_edges("classify", lambda state: state["analysis"]["sentiment"],
                                  {"positive": "encourage", "negative": "comfort"})
    builder.add_edge("encourage", END)
    builder.add_edge("comfort", END)
    return builder.compile()


async def run_pipeline(text, rpc):
    graph = build_workflow(rpc)
    return await graph.ainvoke({"text": text})
