"""进程2（LangGraph）：根据情感识别结果条件路由——正向则鼓励，负面则排解。"""

from __future__ import annotations

import json
import os
from typing import Literal, NotRequired, TypedDict

from fastapi import FastAPI, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from openai import APIError

from common.schemas import RespondRequest, RespondResponse, SentimentType, StrategyType
from common.service_helpers import run_uvicorn
from langgraph_impl.llm import build_chat_model


class ResponseState(TypedDict):
    text: str
    sentiment: SentimentType
    reason: str
    strategy: NotRequired[StrategyType]
    reply: NotRequired[str]
    handler: NotRequired[str]


_ENCOURAGE_PROMPT = (
    "你是一位温暖、真诚的鼓励师。用户当前处于正向情绪，请结合用户的具体情况给予肯定、赞美和积极鼓励（2~4句话，中文）。"
)
_COMFORT_PROMPT = (
    "你是一位富有同理心的心理排解伙伴。用户当前处于负面情绪，请先共情接纳他的感受，再温和地给予安抚与可落地的排解建议（2~4句话，中文）。"
)

_llm = build_chat_model()


def route_by_sentiment(state: ResponseState) -> Literal["encourage_node", "comfort_node"]:
    """Conditional edge router: positive -> encourage_node, negative -> comfort_node."""
    return "encourage_node" if state["sentiment"] == "positive" else "comfort_node"


async def encourage_node(state: ResponseState) -> dict:
    user_msg = json.dumps({"text": state["text"], "reason": state["reason"]}, ensure_ascii=False)
    response = await _llm.ainvoke(
        [SystemMessage(content=_ENCOURAGE_PROMPT), HumanMessage(content=user_msg)]
    )
    return {
        "strategy": "encourage",
        "reply": response.text.strip(),
        "handler": "LangGraph::encourage_node",
    }


async def comfort_node(state: ResponseState) -> dict:
    user_msg = json.dumps({"text": state["text"], "reason": state["reason"]}, ensure_ascii=False)
    response = await _llm.ainvoke(
        [SystemMessage(content=_COMFORT_PROMPT), HumanMessage(content=user_msg)]
    )
    return {
        "strategy": "comfort",
        "reply": response.text.strip(),
        "handler": "LangGraph::comfort_node",
    }


def build_response_graph():
    builder = StateGraph(ResponseState)
    builder.add_node("encourage_node", encourage_node)
    builder.add_node("comfort_node", comfort_node)
    builder.add_conditional_edges(
        START,
        route_by_sentiment,
        {
            "encourage_node": "encourage_node",
            "comfort_node": "comfort_node",
        },
    )
    builder.add_edge("encourage_node", END)
    builder.add_edge("comfort_node", END)
    return builder.compile()


response_graph = build_response_graph()
app = FastAPI(title="LangGraph Process 2 - Emotion Responder")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "framework": "langgraph", "process": "process2_responder", "pid": os.getpid()}


@app.post("/respond", response_model=RespondResponse)
async def respond(req: RespondRequest) -> RespondResponse:
    try:
        final_state = await response_graph.ainvoke(req.model_dump())
    except APIError as exc:
        raise HTTPException(status_code=502, detail="回应模型调用失败。") from exc
    if not final_state["reply"]:
        raise HTTPException(status_code=502, detail="回应模型未返回有效文本。")

    return RespondResponse(
        sentiment=req.sentiment,
        strategy=final_state["strategy"],
        reply=final_state["reply"],
        handler=final_state["handler"],
        framework="langgraph",
        pid=os.getpid(),
    )


if __name__ == "__main__":
    run_uvicorn(app, default_port=8002, description="LangGraph 进程2：正向鼓励/负面排解服务")
