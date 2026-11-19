"""用 LangGraph StateGraph 编排三个 Agent（外加中性兜底节点）。

图结构：
    START -> 情感识别 Agent -> 条件路由 -> 正向鼓励 / 负面排解 / 中性规则兜底 -> END
"""

from __future__ import annotations

import time
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.emotion_agent import EmotionAgent
from agents.base import mock_reply
from agents.support_agents import BaseSupportAgent, ComfortAgent, EncourageAgent
from schemas import ROUTES, EmotionResult


class EmotionState(TypedDict, total=False):
    """在节点之间流转的状态。"""

    user_input: str
    history: list[dict[str, str]]
    history_text: str
    emotion: dict[str, Any]
    route: str
    reply: str
    agent: str
    agent_name: str
    emotion_ms: float
    reply_ms: float


_EMOTION_AGENT = EmotionAgent()
_ENCOURAGE_AGENT = EncourageAgent()
_COMFORT_AGENT = ComfortAgent()


async def emotion_node(state: EmotionState) -> dict[str, Any]:
    """节点 1：情感识别，输出标签、置信度、强度与依据。"""
    started = time.perf_counter()
    result = await _EMOTION_AGENT.analyze(
        state.get("user_input", ""), state.get("history_text", "")
    )
    return {
        "emotion": result.model_dump(),
        "route": ROUTES[result.label],
        "emotion_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def _run_support(state: EmotionState, agent: BaseSupportAgent) -> dict[str, Any]:
    emotion = EmotionResult.model_validate(state.get("emotion", {}))
    started = time.perf_counter()
    reply = await agent.respond(
        state.get("user_input", ""), emotion, state.get("history_text", "")
    )
    return {
        "reply": reply,
        "agent": agent.key,
        "agent_name": agent.name,
        "reply_ms": round((time.perf_counter() - started) * 1000, 1),
    }


async def encourage_node(state: EmotionState) -> dict[str, Any]:
    return await _run_support(state, _ENCOURAGE_AGENT)


async def comfort_node(state: EmotionState) -> dict[str, Any]:
    return await _run_support(state, _COMFORT_AGENT)


async def neutral_node(state: EmotionState) -> dict[str, Any]:
    """中性兜底：不额外调用模型，用稳定的模板接住用户。"""
    started = time.perf_counter()
    emotion = EmotionResult.model_validate(state.get("emotion", {}))
    reply = mock_reply("neutral", state.get("user_input", ""), emotion)
    return {
        "reply": reply,
        "agent": "neutral",
        "agent_name": "中性回应（规则兜底）",
        "reply_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def route_after_emotion(state: EmotionState) -> str:
    """条件边：正向去鼓励，负面去排解，中性去规则兜底。"""
    return state.get("route", "neutral")


def build_graph():
    builder = StateGraph(EmotionState)

    # 三个 Agent 各自是图里的一个节点；neutral 是规则兜底节点
    builder.add_node("emotion", emotion_node)
    builder.add_node("encourage", encourage_node)
    builder.add_node("comfort", comfort_node)
    builder.add_node("neutral", neutral_node)

    builder.add_edge(START, "emotion")
    builder.add_conditional_edges(
        "emotion",
        route_after_emotion,
        {
            "encourage": "encourage",
            "comfort": "comfort",
            "neutral": "neutral",
        },
    )
    builder.add_edge("encourage", END)
    builder.add_edge("comfort", END)
    builder.add_edge("neutral", END)

    return builder.compile()


_GRAPH = None


def get_graph():
    """编译一次，进程内复用。"""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH
