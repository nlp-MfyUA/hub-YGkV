"""后端编排：把前端输入与最近 5 轮上下文送进 LangGraph，并输出阶段事件。"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

import config
from graph import get_graph
from schemas import AGENT_NAMES, ROUTES, EmotionResult


def trim_history(history: list[Any] | None) -> list[dict[str, str]]:
    """只保留最近 MAX_HISTORY_ROUNDS 轮（一轮 = 一条 user + 一条 assistant）。

    前端可能传入任意长度的历史；这里以后端为准再截断一次，避免上下文无限增长。
    """
    turns: list[dict[str, str]] = []
    for item in history or []:
        if isinstance(item, dict):
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
        else:
            role = str(getattr(item, "role", "")).strip()
            content = str(getattr(item, "content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        turns.append({"role": role, "content": content[:4000]})

    user_positions = [index for index, turn in enumerate(turns) if turn["role"] == "user"]
    if len(user_positions) > config.MAX_HISTORY_ROUNDS:
        turns = turns[user_positions[-config.MAX_HISTORY_ROUNDS]:]
    return turns


def history_to_text(history: list[dict[str, str]]) -> str:
    if not history:
        return ""
    lines = ["以下是最近的对话（从旧到新），仅用于理解当前语境："]
    for turn in history:
        speaker = "用户" if turn["role"] == "user" else "助手"
        lines.append(f"{speaker}：{turn['content']}")
    return "\n".join(lines)


def _emotion_payload(emotion: EmotionResult, route: str) -> dict:
    return {
        "label": emotion.label,
        "label_zh": emotion.label_zh,
        "confidence": round(emotion.confidence, 3),
        "intensity": emotion.intensity,
        "reason": emotion.reason,
        "keywords": emotion.keywords,
        "agent": route,
        "agent_name": AGENT_NAMES.get(route, "中性回应（规则兜底）"),
    }


async def run_pipeline(user_input: str, history: list[Any] | None = None) -> AsyncIterator[dict]:
    """执行 情感识别 -> 条件路由 -> 对应回应 Agent 的完整链路。"""
    trimmed = trim_history(history)
    started = time.perf_counter()
    yield {
        "type": "stage",
        "stage": "emotion",
        "status": "running",
        "text": "情感识别 Agent 正在分析这句话…",
        "history_rounds": len([turn for turn in trimmed if turn["role"] == "user"]),
    }

    state: dict = {}
    initial_state = {
        "user_input": user_input,
        "history": trimmed,
        "history_text": history_to_text(trimmed),
    }
    async for update in get_graph().astream(initial_state, stream_mode="updates"):
        for node, delta in (update or {}).items():
            if not delta:
                continue
            state.update(delta)

            if node == "emotion":
                emotion = EmotionResult.model_validate(state["emotion"])
                route = state.get("route") or ROUTES[emotion.label]
                yield {"type": "emotion", **_emotion_payload(emotion, route)}
                yield {
                    "type": "stage",
                    "stage": "reply",
                    "status": "running",
                    "agent": route,
                    "agent_name": AGENT_NAMES.get(route, "中性回应（规则兜底）"),
                    "text": f"{AGENT_NAMES.get(route, '回应 Agent')} 正在组织回应…",
                }
            elif node in AGENT_NAMES:
                yield {
                    "type": "reply",
                    "text": state.get("reply", ""),
                    "agent": node,
                    "agent_name": state.get("agent_name", AGENT_NAMES.get(node, "回应 Agent")),
                }

    emotion = EmotionResult.model_validate(state.get("emotion", {}))
    route = state.get("route") or ROUTES[emotion.label]
    yield {
        "type": "done",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "emotion_ms": state.get("emotion_ms", 0),
        "reply_ms": state.get("reply_ms", 0),
        "emotion": _emotion_payload(emotion, route),
        "reply": state.get("reply", ""),
        "agent": route,
        "agent_name": state.get("agent_name", AGENT_NAMES.get(route, "回应 Agent")),
        "history_rounds": len([turn for turn in trimmed if turn["role"] == "user"]),
    }
