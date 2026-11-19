"""进程1（openai-agents 版）：情感识别服务。

和 LangGraph 版做同一件事，但组织方式完全不同：
不再是「节点 + 条件边」，而是**一个带工具的 Agent**：

    Runner.run(sentiment_agent)
        │
        ├── input_guardrail   空输入直接拦掉（tripwire）
        ├── 工具 submit_sentiment(...)   结构化输出（stop_on_first_tool）
        └── final_output = 工具返回的 JSON

外层仍然是 FastAPI，因为「进程」之间的边界必须是 HTTP，而不是函数调用。

运行：
    python -m agents_version.sentiment_service          # 端口 8101
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Literal

from agents import (
    Agent,
    GuardrailFunctionOutput,
    InputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    function_tool,
    input_guardrail,
)
from fastapi import FastAPI
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents_version.model import COLD, MODEL, RUN_CONFIG  # noqa: E402
from common import config, prompts, rules, service  # noqa: E402
from common.protocol import SentimentResult  # noqa: E402

NAME = "进程1-情感识别"
LOW_CONFIDENCE = 0.55


# --------------------------------------------------------------------------- #
# 工具：Agent 唯一的「出口」，用来交结构化结果
# --------------------------------------------------------------------------- #
@function_tool(strict_mode=False)
def submit_sentiment(
    label: Literal["positive", "negative", "neutral"],
    emotion: str,
    confidence: float,
    intensity: float,
    reason: str,
    keywords: list[str],
) -> str:
    """提交情感识别的最终结论。六个参数都必须填，调用后本次分析即结束。

    Args:
        label: 只能是 positive / negative / neutral
        emotion: 一个中文情绪词，如 焦虑、喜悦、平静
        confidence: 你对 label 的把握，0~1
        intensity: 情绪强度，0~1
        reason: 判断依据，20 字以内
        keywords: 原文里带情绪的 1~3 个片段
    """
    return json.dumps(
        {
            "label": label,
            "emotion": emotion,
            "confidence": confidence,
            "intensity": intensity,
            "reason": reason,
            "keywords": keywords,
        },
        ensure_ascii=False,
    )


# --------------------------------------------------------------------------- #
# 输入护栏：空输入不进模型，省一次调用
# --------------------------------------------------------------------------- #
@input_guardrail
async def non_empty_guardrail(
    ctx: RunContextWrapper[None], agent: Agent, user_input: object
) -> GuardrailFunctionOutput:
    text = user_input if isinstance(user_input, str) else str(user_input)
    empty = not text.strip()
    return GuardrailFunctionOutput(
        output_info={"empty": empty, "chars": len(text)},
        tripwire_triggered=empty,
    )


SENTIMENT_AGENT = Agent(
    name="SentimentAnalyst",
    handoff_description="判断一句话的情绪倾向",
    instructions=prompts.SENTIMENT_SYSTEM
    + """

你必须调用 submit_sentiment 工具提交结论，不要直接回复文字。
调用工具之前不要输出任何解释。""",
    tools=[submit_sentiment],
    tool_use_behavior="stop_on_first_tool",
    input_guardrails=[non_empty_guardrail],
    model=MODEL,
    model_settings=COLD,
)


def _prompt(text: str, hint: dict) -> str:
    extra = prompts.SENTIMENT_HINT.format(
        pos="、".join(hint.get("pos") or []) or "（无）",
        neg="、".join(hint.get("neg") or []) or "（无）",
        crisis="是" if hint.get("crisis") else "否",
    )
    return prompts.SENTIMENT_USER.format(text=text, extra=extra)


async def analyze(text: str) -> tuple[SentimentResult, list[str], int]:
    """返回 (结果, 轨迹, 耗时ms)。任何异常都要落成「有结果」，不能让进程1 挂。"""
    started = time.perf_counter()
    notes: list[str] = []
    hint = rules.lexicon_hint(text)
    notes.append(f"词典粗筛：正{len(hint['pos'])} 负{len(hint['neg'])} 危机={hint['crisis']}")

    try:
        run = await Runner.run(SENTIMENT_AGENT, _prompt(text, hint), run_config=RUN_CONFIG, max_turns=4)
        notes.append(f"Runner.run 结束：末位 Agent={run.last_agent.name}，共 {len(run.new_items)} 个 item")
        result = SentimentResult.from_raw(json.loads(run.final_output), source="llm")
        result, extra = rules.post_verify(result, hint)
        notes.extend(extra)

        if result.confidence < LOW_CONFIDENCE:
            notes.append(f"置信度 {result.confidence:.2f} 偏低，带上一轮结论复核一次")
            refine_prompt = _prompt(text, hint) + "\n\n" + prompts.SENTIMENT_REFINE.format(
                prev=f"{result.label}/{result.emotion}", conf=result.confidence
            )
            run2 = await Runner.run(SENTIMENT_AGENT, refine_prompt, run_config=RUN_CONFIG, max_turns=4)
            refined = SentimentResult.from_raw(json.loads(run2.final_output), source="refine")
            refined, extra2 = rules.post_verify(refined, hint)
            notes.extend(["复核：" + n for n in extra2])
            result = refined
    except InputGuardrailTripwireTriggered:
        result = SentimentResult(label="neutral", emotion="平静", confidence=1.0, intensity=0.0,
                                 reason="输入为空，被 input guardrail 拦截", source="guardrail")
        notes.append("input guardrail 触发 tripwire，直接返回中性")
    except Exception as exc:  # noqa: BLE001 - 模型/网络问题一律降级
        result = rules.rule_sentiment(text)
        notes.append(f"Agent 运行失败，规则兜底：{type(exc).__name__}: {exc}")

    result.notes = notes
    return result, notes, int((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------- #
# HTTP 外壳
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    text: str = ""
    session_id: str = "default"


app = service.create_app(NAME, "进程1 · 情感识别（openai-agents）")


@app.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest) -> dict:
    text = req.text.strip()[: config.MAX_INPUT_CHARS]
    result, _notes, ms = await analyze(text)
    service.log(NAME, f'analyze "{text[:18]}" -> {result.label} ({ms}ms, {result.source})')
    return {"ok": True, "data": result.model_dump(), "ms": ms}


@app.get("/agents")
def describe() -> dict:
    """把 Agent 的组成吐出来，方便对照 langgraph 版的 /graph。"""
    return {
        "agents": [
            {
                "name": SENTIMENT_AGENT.name,
                "tools": [t.name for t in SENTIMENT_AGENT.tools],
                "guardrails": ["non_empty_guardrail"],
                "tool_use_behavior": str(SENTIMENT_AGENT.tool_use_behavior),
                "model": config.LLM_MODEL,
            }
        ]
    }


if __name__ == "__main__":
    service.serve(app, config.SENTIMENT_PORT, NAME, "进程1：情感识别（openai-agents）")
