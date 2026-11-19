"""进程1（LangGraph 版）：情感识别服务。

本进程对外只有一个接口 POST /analyze，内部是一张 LangGraph 图：

    START
      │
   precheck          词典粗筛 + 数据清洗（空文本 / 超长 / 危机词）
      │
      ├── 空文本 ──────────────────────────────┐
      │                                        │
   classify          LLM 出 JSON（三分类 + 强度 + 依据）
      │                                        │
   verify            字段校验 / 复核词典线索 / 置信度判断
      │                                        │
      ├── 置信度低 且 还有次数 ──> refine ──┐   │
      │                                    │   │
      └── 通过 或 次数用尽 ────────────────┴──>│
                                              ▼
                                           finish ──> END

为什么值得用图：verify -> refine 这个回环就是「一次判不准就换个问法再判」，
用条件边表达比在函数里写 if/else 更清楚，也方便单独观察每一步。

运行：
    python -m langgraph_version.sentiment_service          # 端口 8101
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from fastapi import FastAPI
from pydantic import BaseModel

if __package__ in (None, ""):  # 允许 `python sentiment_service.py` 直接跑
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.graph import END, START, StateGraph  # noqa: E402

from common import config, llm, prompts, rules, service  # noqa: E402
from common.protocol import SentimentResult  # noqa: E402

NAME = "进程1-情感识别"
MAX_ATTEMPTS = 2          # 首判 + 1 次复核
LOW_CONFIDENCE = 0.55     # 低于这个值就复核一次


class State(TypedDict, total=False):
    text: str
    hint: dict[str, Any]
    attempts: int
    draft: dict[str, Any]
    result: dict[str, Any]
    notes: list[str]


def _note(state: State, msg: str) -> list[str]:
    return list(state.get("notes") or []) + [msg]


# --------------------------------------------------------------------------- #
# 节点
# --------------------------------------------------------------------------- #
def precheck(state: State) -> dict:
    """清洗 + 词典粗筛，给模型一点线索。"""
    started = time.perf_counter()
    text = (state.get("text") or "").strip()
    if len(text) > config.MAX_INPUT_CHARS:
        text = text[: config.MAX_INPUT_CHARS]
    hint = rules.lexicon_hint(text)
    ms = (time.perf_counter() - started) * 1000
    return {
        "text": text,
        "hint": hint,
        "attempts": 0,
        "notes": _note(state, f"precheck 清洗+粗筛({ms:.0f}ms) 正{len(hint['pos'])} 负{len(hint['neg'])} 危机={hint['crisis']}"),
    }


def classify(state: State) -> dict:
    """LLM 三分类。失败就退到词典，别让整个服务挂掉。"""
    started = time.perf_counter()
    hint = state.get("hint") or {}
    extra = prompts.SENTIMENT_HINT.format(
        pos="、".join(hint.get("pos") or []) or "（无）",
        neg="、".join(hint.get("neg") or []) or "（无）",
        crisis="是" if hint.get("crisis") else "否",
    )
    user = prompts.SENTIMENT_USER.format(text=state["text"], extra=extra)
    try:
        draft = llm.chat_json(prompts.SENTIMENT_SYSTEM, user, temperature=0.0, max_tokens=400)
        ms = (time.perf_counter() - started) * 1000
        return {"draft": draft, "attempts": 1, "notes": _note(state, f"classify 调用模型({ms:.0f}ms) label={draft.get('label')}")}
    except llm.LLMError as exc:
        ms = (time.perf_counter() - started) * 1000
        result = rules.rule_sentiment(state["text"]).model_dump()
        result["notes"] = _note(state, f"classify 模型失败({ms:.0f}ms)，规则兜底：{exc}")
        return {"result": result, "attempts": 99, "notes": result["notes"]}


def verify(state: State) -> dict:
    """把模型输出规范化，并用确定性规则做一次压制。"""
    if state.get("result"):  # 已经走兜底，无需校验
        return {}
    started = time.perf_counter()
    draft = state.get("draft") or {}
    result = SentimentResult.from_raw(draft, source="llm" if state.get("attempts", 1) <= 1 else "refine")

    notes = list(state.get("notes") or [])
    # 危机词优先级最高：只要命中就按负向处理，宁可误报；与词典冲突时下调置信度触发复核
    result, extra = rules.post_verify(result, state.get("hint") or {})
    notes.extend(extra)

    ms = (time.perf_counter() - started) * 1000
    notes.append(f"verify 规范化({ms:.0f}ms) label={result.label} conf={result.confidence:.2f}")
    return {"result": result.model_dump(), "notes": notes}


def refine(state: State) -> dict:
    """复核：把上一轮的结论和疑问一起给模型，让它重新判一次。"""
    started = time.perf_counter()
    prev = state.get("result") or {}
    conf = float(prev.get("confidence") or 0)
    user = prompts.SENTIMENT_USER.format(
        text=state["text"],
        extra=prompts.SENTIMENT_REFINE.format(
            prev=f'{prev.get("label")}/{prev.get("emotion")}', conf=conf
        ) + "\n",
    )
    attempts = int(state.get("attempts") or 1) + 1
    try:
        draft = llm.chat_json(prompts.SENTIMENT_SYSTEM, user, temperature=0.0, max_tokens=400)
        ms = (time.perf_counter() - started) * 1000
        return {"draft": draft, "attempts": attempts, "result": {}, "notes": _note(state, f"refine 第{attempts}次复核({ms:.0f}ms) label={draft.get('label')}")}
    except llm.LLMError as exc:
        ms = (time.perf_counter() - started) * 1000
        return {"attempts": attempts, "notes": _note(state, f"refine 失败({ms:.0f}ms)，沿用上一轮结果：{exc}")}


def finish(state: State) -> dict:
    if not state.get("result"):
        result = SentimentResult.from_raw(state.get("draft") or {}, source="llm").model_dump()
        return {"result": result, "notes": _note(state, "finish 直接收敛")}
    return {}


def route_after_precheck(state: State) -> str:
    return "finish" if not state.get("text") else "classify"


def route_after_verify(state: State) -> str:
    result = state.get("result") or {}
    low = float(result.get("confidence") or 0) < LOW_CONFIDENCE
    if low and int(state.get("attempts") or 0) < MAX_ATTEMPTS:
        return "refine"
    return "finish"


def build_graph():
    graph = StateGraph(State)
    graph.add_node("precheck", precheck)
    graph.add_node("classify", classify)
    graph.add_node("verify", verify)
    graph.add_node("refine", refine)
    graph.add_node("finish", finish)

    graph.add_edge(START, "precheck")
    graph.add_conditional_edges("precheck", route_after_precheck, {"classify": "classify", "finish": "finish"})
    graph.add_edge("classify", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"refine": "refine", "finish": "finish"})
    graph.add_edge("refine", "verify")
    graph.add_edge("finish", END)
    return graph.compile()


GRAPH = build_graph()


# --------------------------------------------------------------------------- #
# HTTP 外壳
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    text: str = ""
    session_id: str = "default"


app = service.create_app(NAME, "进程1 · 情感识别（LangGraph）")


@app.post("/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    started = time.perf_counter()
    final_state = GRAPH.invoke({"text": req.text, "notes": []})
    result = final_state.get("result") or rules.rule_sentiment(req.text).model_dump()
    result["notes"] = final_state.get("notes") or []
    ms = int((time.perf_counter() - started) * 1000)
    service.log(NAME, f'analyze "{req.text[:18]}" -> {result["label"]} ({ms}ms)')
    return {"ok": True, "data": result, "ms": ms}


@app.get("/graph")
def graph_spec() -> dict:
    """把图结构以 mermaid 形式吐出来，方便贴到文档里。"""
    return {"mermaid": GRAPH.get_graph().draw_mermaid()}


if __name__ == "__main__":
    service.serve(app, config.SENTIMENT_PORT, NAME, "进程1：情感识别（LangGraph）")
