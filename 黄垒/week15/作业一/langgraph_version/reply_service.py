"""进程2（LangGraph 版）：情绪回应服务。

输入是「用户原话 + 进程1 的识别结果」，输出一句回应。内部是一张图：

    START
      │
    route            按标签选策略：正向→鼓励  负向→排解  中性→倾听  危机词→兜底
      │
      ├── crisis ─────────────────> generate_crisis ──> finish ──> END
      │
    generate         按策略选提示词，生成 JSON（正文 + 小建议 + 追问）
      │
    quality          规则质检：说教词 / 套话 / 情绪方向相反 / 越界诊断
      │
      ├── 不合格 且 还有次数 ──> regenerate ──┐
      │                                       │
      └── 合格 或 次数用尽 ───────────────────┴──> finish ──> END

「生成 → 质检 → 重写」这个回环是图里最值钱的部分：
它让「模型自己写」这件事多了一道确定性把关，而不是写完就发。

运行：
    python -m langgraph_version.reply_service             # 端口 8102
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from fastapi import FastAPI
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from common import config, llm, prompts, rules, service  # noqa: E402
from common.protocol import Label, ReplyResult, SentimentResult  # noqa: E402

NAME = "进程2-情绪回应"
MAX_ATTEMPTS = 2          # 首写 + 1 次重写

SYSTEM_BY_STRATEGY = {
    "encourage": prompts.ENCOURAGE_SYSTEM,
    "soothe": prompts.SOOTHE_SYSTEM,
    "listen": prompts.LISTEN_SYSTEM,
    "crisis": prompts.CRISIS_SYSTEM,
}


class State(TypedDict, total=False):
    text: str
    sentiment: dict[str, Any]
    strategy: str
    attempts: int
    issue: str
    result: dict[str, Any]
    notes: list[str]


def _note(state: State, msg: str) -> list[str]:
    return list(state.get("notes") or []) + [msg]


def _user_prompt(state: State, issue: str = "") -> str:
    s = state.get("sentiment") or {}
    body = (
        f"用户原话：「{state['text']}」\n"
        f"情感识别结果：{s.get('label')} / {s.get('emotion')}（强度 {s.get('intensity')}，把握 {s.get('confidence')}）\n"
        f"识别依据：{s.get('reason') or '（无）'}"
    )
    if issue:
        body += "\n\n" + prompts.REPLY_REGENERATE.format(issue=issue)
    return body


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def route(state: State) -> dict:
    """策略选择是确定性的：情绪方向决定回应方式，不交给模型自由发挥。"""
    started = time.perf_counter()
    sentiment = SentimentResult.model_validate(state.get("sentiment") or {})
    strategy = rules.pick_strategy(sentiment.label, state["text"])
    ms = (time.perf_counter() - started) * 1000
    return {
        "strategy": strategy,
        "attempts": 0,
        "notes": _note(state, f'route {sentiment.label} -> {strategy}({ms:.0f}ms)'),
    }


def generate(state: State) -> dict:
    strategy = state["strategy"]
    started = time.perf_counter()
    try:
        raw = llm.chat_json(SYSTEM_BY_STRATEGY[strategy], _user_prompt(state), temperature=0.7, max_tokens=600)
        result = ReplyResult.from_raw(raw, strategy=strategy)  # type: ignore[arg-type]
        ms = (time.perf_counter() - started) * 1000
        return {
            "result": result.model_dump(),
            "attempts": int(state.get("attempts") or 0) + 1,
            "issue": "",
            "notes": _note(state, f"generate[{strategy}] 调用模型({ms:.0f}ms) {len(result.reply)}字"),
        }
    except llm.LLMError as exc:
        ms = (time.perf_counter() - started) * 1000
        label: Label = (state.get("sentiment") or {}).get("label", "neutral")
        fallback = rules.rule_reply(label, state["text"], strategy).model_dump()
        fallback["notes"] = _note(state, f"generate 模型失败({ms:.0f}ms)，规则兜底：{exc}")
        return {"result": fallback, "attempts": 99, "issue": "", "notes": fallback["notes"]}


def generate_crisis(state: State) -> dict:
    """危机分支：先给固定的安全话术，模型只用来润色语气。"""
    started = time.perf_counter()
    base = rules.rule_reply("negative", state["text"], "crisis")
    try:
        raw = llm.chat_json(prompts.CRISIS_SYSTEM, _user_prompt(state), temperature=0.3, max_tokens=400)
        result = ReplyResult.from_raw(raw, strategy="crisis")
        if not result.tips:
            result.tips = base.tips
        source = "llm"
    except llm.LLMError:
        result, source = base, "rule"
    result.tips = result.tips or base.tips
    ms = (time.perf_counter() - started) * 1000
    return {
        "result": result.model_dump(),
        "attempts": 99,                      # 危机话术不再进重写循环，直接收尾
        "notes": _note(state, f"generate_crisis 安全兜底({ms:.0f}ms) 来源={source}"),
    }


def quality(state: State) -> dict:
    """确定性质检。不合格时把原因写进 state，交给 regenerate。"""
    started = time.perf_counter()
    result = ReplyResult.model_validate(state.get("result") or {})
    label: Label = (state.get("sentiment") or {}).get("label", "neutral")
    issue = rules.check_reply_rules(state["text"], label, result.reply) or ""
    ms = (time.perf_counter() - started) * 1000
    detail = issue or "通过"
    return {"issue": issue, "notes": _note(state, f"quality 规则质检({ms:.0f}ms) {detail}")}


def regenerate(state: State) -> dict:
    started = time.perf_counter()
    strategy = state["strategy"]
    try:
        raw = llm.chat_json(SYSTEM_BY_STRATEGY[strategy], _user_prompt(state, state.get("issue", "")),
                            temperature=0.8, max_tokens=600)
        result = ReplyResult.from_raw(raw, strategy=strategy)  # type: ignore[arg-type]
    except llm.LLMError as exc:
        ms = (time.perf_counter() - started) * 1000
        return {"attempts": MAX_ATTEMPTS, "notes": _note(state, f"regenerate 失败({ms:.0f}ms)：{exc}")}
    ms = (time.perf_counter() - started) * 1000
    return {
        "result": result.model_dump(),
        "attempts": int(state.get("attempts") or 1) + 1,
        "issue": "",
        "notes": _note(state, f"regenerate 第{int(state.get('attempts') or 1) + 1}版({ms:.0f}ms) {len(result.reply)}字"),
    }


def finish(state: State) -> dict:
    if state.get("result"):
        return {}
    label: Label = (state.get("sentiment") or {}).get("label", "neutral")
    return {"result": rules.rule_reply(label, state["text"], state.get("strategy")).model_dump()}


def route_after_route(state: State) -> str:
    return "generate_crisis" if state.get("strategy") == "crisis" else "generate"


def route_after_quality(state: State) -> str:
    if state.get("issue") and int(state.get("attempts") or 0) < MAX_ATTEMPTS:
        return "regenerate"
    return "finish"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("route", route)
    graph.add_node("generate", generate)
    graph.add_node("generate_crisis", generate_crisis)
    graph.add_node("quality", quality)
    graph.add_node("regenerate", regenerate)
    graph.add_node("finish", finish)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", route_after_route, {"generate": "generate", "generate_crisis": "generate_crisis"})
    graph.add_edge("generate", "quality")
    graph.add_conditional_edges("quality", route_after_quality, {"regenerate": "regenerate", "finish": "finish"})
    graph.add_edge("regenerate", "quality")
    graph.add_edge("generate_crisis", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


GRAPH = build_graph()


# --------------------------------------------------------------------------- #
# HTTP 外壳
# --------------------------------------------------------------------------- #
class RespondRequest(BaseModel):
    text: str = ""
    sentiment: dict[str, Any] = {}
    session_id: str = "default"


app = service.create_app(NAME, "进程2 · 情绪回应（LangGraph）")


@app.post("/respond")
def respond(req: RespondRequest) -> dict:
    started = time.perf_counter()
    final_state = GRAPH.invoke({"text": req.text, "sentiment": req.sentiment, "notes": []})
    result = final_state.get("result") or rules.rule_reply(
        (req.sentiment or {}).get("label", "neutral"), req.text
    ).model_dump()
    result["notes"] = final_state.get("notes") or []
    ms = int((time.perf_counter() - started) * 1000)
    service.log(NAME, f'respond "{req.text[:14]}" -> {result["strategy"]} ({ms}ms)')
    return {"ok": True, "data": result, "ms": ms}


@app.get("/graph")
def graph_spec() -> dict:
    return {"mermaid": GRAPH.get_graph().draw_mermaid()}


if __name__ == "__main__":
    service.serve(app, config.REPLY_PORT, NAME, "进程2：情绪回应（LangGraph）")
