"""后端编排：情感识别 Agent -> 选择回应 Agent -> 生成回应。"""

from __future__ import annotations

import time
from typing import Any, AsyncIterator

from agents import Runner

import config
from agent_builders.base import mock_analyze, mock_reply, parse_emotion
from agent_builders.emotion_agent import build_emotion_agent
from agent_builders.support_agents import build_comfort_agent, build_encourage_agent
from core.llm import usage_dict
from schemas import AGENT_NAMES, ROUTES, EmotionResult


def trim_history(history: list[Any] | None) -> list[dict[str, str]]:
    """只保留最近 MAX_HISTORY_ROUNDS 轮（一轮 = 一条 user + 一条 assistant）。"""
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


def _merge_usage(first: dict, second: dict) -> dict:
    merged: dict[str, int] = {}
    for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
        merged[key] = int(first.get(key, 0) or 0) + int(second.get(key, 0) or 0)
    return merged


def _reply_input(user_input: str, emotion: EmotionResult, history_text: str) -> str:
    history_block = (history_text + "\n\n") if history_text else ""
    return (
        history_block
        + "用户原话：\n" + user_input + "\n\n"
        + "情感识别结果：\n"
        + f"- 标签：{emotion.label_zh}\n"
        + f"- 置信度：{emotion.confidence:.0%}\n"
        + f"- 强度：{emotion.intensity}/5\n"
        + f"- 依据：{emotion.reason or '无'}\n\n"
        + "请依据以上信息，直接给用户一段回应。"
    )


async def run_pipeline(user_input: str, history: list[Any] | None = None) -> AsyncIterator[dict]:
    emotion_agent = build_emotion_agent()
    encourage_agent = build_encourage_agent()
    comfort_agent = build_comfort_agent()
    trimmed = trim_history(history)
    history_text = history_to_text(trimmed)
    started = time.perf_counter()
    yield {
        "type": "stage",
        "stage": "emotion",
        "status": "running",
        "text": "情感识别 Agent 正在分析这句话…",
        "history_rounds": len([turn for turn in trimmed if turn["role"] == "user"]),
    }

    # ---- Agent 1：情感识别 ----
    emotion_usage: dict = {}
    if config.MOCK_MODE:
        emotion = mock_analyze(user_input)
    else:
        emotion_input = user_input
        if history_text:
            emotion_input = history_text + "\n\n当前用户输入：\n" + user_input
        try:
            emotion_result = await Runner.run(emotion_agent, emotion_input, max_turns=2)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"情感识别 Agent 调用失败：{type(exc).__name__}: {exc}") from exc
        emotion = parse_emotion(str(emotion_result.final_output))
        emotion_usage = usage_dict(emotion_result)

    route = ROUTES[emotion.label]
    yield {"type": "emotion", **_emotion_payload(emotion, route)}
    yield {
        "type": "stage",
        "stage": "reply",
        "status": "running",
        "agent": route,
        "agent_name": AGENT_NAMES.get(route, "中性回应（规则兜底）"),
        "text": f"{AGENT_NAMES.get(route, '回应 Agent')} 正在组织回应…",
    }

    # ---- Agent 2/3：按情绪结果选择回应者；中性走规则兜底（不额外调用模型）----
    reply_usage: dict = {}
    if route == "neutral":
        reply = mock_reply("neutral", user_input, emotion)
    elif config.MOCK_MODE:
        reply = mock_reply(route, user_input, emotion)
    else:
        agent = encourage_agent if route == "encourage" else comfort_agent
        try:
            reply_result = await Runner.run(
                agent,
                _reply_input(user_input, emotion, history_text),
                max_turns=2,
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"{agent.name} 调用失败：{type(exc).__name__}: {exc}") from exc
        reply = str(reply_result.final_output).strip()
        reply_usage = usage_dict(reply_result)

    yield {
        "type": "reply",
        "text": reply,
        "agent": route,
        "agent_name": AGENT_NAMES.get(route, "中性回应（规则兜底）"),
    }
    yield {
        "type": "done",
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "emotion": _emotion_payload(emotion, route),
        "reply": reply,
        "agent": route,
        "agent_name": AGENT_NAMES.get(route, "中性回应（规则兜底）"),
        "history_rounds": len([turn for turn in trimmed if turn["role"] == "user"]),
        "usage": _merge_usage(emotion_usage, reply_usage),
    }
