"""进程2（openai-agents 版）：情绪回应服务。

这一版把「正向鼓励 / 负面排解 / 中性倾听」做成三个**独立的 Agent**，
再用一个 Triage（分诊）Agent 通过 *handoff* 把对话交出去：

    Runner.run(Triage)                    用户原话 + 进程1 的标签
        │
        ├── handoff ──> Encourager   正向：放大好心情
        ├── handoff ──> Soother      负向：先接住情绪再排解
        └── handoff ──> Listener     中性：顺着话题接话
                              │
                            调用 submit_reply(...) 交结构化结果
                              │
                        output_guardrail：说教/套话/越界诊断 -> tripwire

注意两条在工程上必须存在的兜底，否则「让模型自己分流」会变成不可靠：

1. **标签优先**：策略由进程1 的标签确定性算出（crisis 更是直接跳过 Triage，
   交给 CrisisSupporter）。Triage 只是让 handoff 这一步走 SDK 的机制。
2. **分流纠正**：如果 handoff 落到的 Agent 和标签不符，直接用正确的专家重跑一次，
   并把这个纠正记进 notes —— 不把正确性寄托在模型的自觉上。

运行：
    python -m agents_version.reply_service             # 端口 8102
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agents import (
    Agent,
    GuardrailFunctionOutput,
    ModelSettings,
    OutputGuardrailTripwireTriggered,
    RunContextWrapper,
    Runner,
    function_tool,
    output_guardrail,
)
from fastapi import FastAPI
from pydantic import BaseModel

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents_version.model import COLD, MODEL, RUN_CONFIG, WARM  # noqa: E402
from common import config, prompts, rules, service  # noqa: E402
from common.protocol import Label, ReplyResult  # noqa: E402

NAME = "进程2-情绪回应"
MAX_ATTEMPTS = 2


# --------------------------------------------------------------------------- #
# 结构化出口
# --------------------------------------------------------------------------- #
@function_tool(strict_mode=False)
def submit_reply(reply: str, tips: list[str], follow_up: str) -> str:
    """提交最终的回复内容，调用后本轮回复即结束。

    Args:
        reply: 回复正文，60~150 字，先接住情绪再说内容
        tips: 最多 2 条可执行的小建议，没有就给空列表
        follow_up: 一句追问，用于把对话接下去
    """
    return json.dumps({"reply": reply, "tips": tips, "follow_up": follow_up}, ensure_ascii=False)


@output_guardrail
async def tone_guardrail(
    ctx: RunContextWrapper[dict], agent: Agent, output: object
) -> GuardrailFunctionOutput:
    """把「说教 / 套话 / 越界诊断」做成护栏：命中就 tripwire，交给外层重写。"""
    data = ctx.context or {}
    text, label = data.get("text", ""), data.get("label", "neutral")
    body = ""
    try:
        body = str(json.loads(str(output)).get("reply", ""))
    except Exception:  # noqa: BLE001 - 输出不一定是 JSON，退化成整体判断
        body = str(output)
    issue = rules.check_reply_rules(text, label, body) or ""
    return GuardrailFunctionOutput(output_info={"issue": issue, "agent": agent.name},
                                   tripwire_triggered=bool(issue))


# --------------------------------------------------------------------------- #
# 四个 Agent
# --------------------------------------------------------------------------- #
_ENCOURAGER = Agent(
    name="Encourager",
    handoff_description="用户情绪是正向时，接住并放大这份好心情",
    instructions=prompts.ENCOURAGE_SYSTEM + "\n\n必须调用 submit_reply 提交结果。",
    tools=[submit_reply],
    tool_use_behavior="stop_on_first_tool",
    output_guardrails=[tone_guardrail],
    model=MODEL,
    model_settings=WARM,
)

_SOOTHER = Agent(
    name="Soother",
    handoff_description="用户情绪是负向时，先共情再温和排解",
    instructions=prompts.SOOTHE_SYSTEM + "\n\n必须调用 submit_reply 提交结果。",
    tools=[submit_reply],
    tool_use_behavior="stop_on_first_tool",
    output_guardrails=[tone_guardrail],
    model=MODEL,
    model_settings=WARM,
)

_LISTENER = Agent(
    name="Listener",
    handoff_description="用户情绪中性时，顺着话题自然接话",
    instructions=prompts.LISTEN_SYSTEM + "\n\n必须调用 submit_reply 提交结果。",
    tools=[submit_reply],
    tool_use_behavior="stop_on_first_tool",
    output_guardrails=[tone_guardrail],
    model=MODEL,
    model_settings=WARM,
)

_CRISIS = Agent(
    name="CrisisSupporter",
    handoff_description="用户出现自伤/轻生线索时的安全兜底",
    instructions=prompts.CRISIS_SYSTEM + "\n\n必须调用 submit_reply 提交结果。",
    tools=[submit_reply],
    tool_use_behavior="stop_on_first_tool",
    output_guardrails=[tone_guardrail],
    model=MODEL,
    model_settings=ModelSettings(temperature=0.3),
)

TRIAGE = Agent(
    name="Triage",
    handoff_description="按情绪标签把对话交给对应专家",
    instructions="""你是一个分诊员，只负责转交，**不要自己回答问题**。

看输入里的「情感识别结果」：
- positive -> handoff 给 Encourager
- negative -> handoff 给 Soother
- neutral  -> handoff 给 Listener

立刻 handoff，不要输出任何解释。""",
    handoffs=[_ENCOURAGER, _SOOTHER, _LISTENER],
    model=MODEL,
    model_settings=COLD,
)

SPECIALISTS: dict[str, Agent] = {
    "encourage": _ENCOURAGER,
    "soothe": _SOOTHER,
    "listen": _LISTENER,
    "crisis": _CRISIS,
}


# --------------------------------------------------------------------------- #
# 一轮回复
# --------------------------------------------------------------------------- #
def _prompt(text: str, sentiment: dict) -> str:
    return (
        f"用户原话：「{text}」\n"
        f"情感识别结果：{sentiment.get('label')} / {sentiment.get('emotion')}"
        f"（强度 {sentiment.get('intensity')}，把握 {sentiment.get('confidence')}）\n"
        f"识别依据：{sentiment.get('reason') or '（无）'}"
    )


def _issue_of(exc: OutputGuardrailTripwireTriggered) -> str:
    try:
        info = exc.guardrail_result.output.output_info or {}
        return str(info.get("issue") or "output guardrail 拦截")
    except Exception:  # noqa: BLE001
        return "output guardrail 拦截"


async def _run(agent: Agent, prompt: str, context: dict) -> tuple[dict, str]:
    run = await Runner.run(agent, prompt, context=context, run_config=RUN_CONFIG, max_turns=5)
    return json.loads(run.final_output), run.last_agent.name


async def respond(text: str, sentiment: dict) -> tuple[ReplyResult, list[str], int]:
    started = time.perf_counter()
    notes: list[str] = []
    label: Label = sentiment.get("label", "neutral")  # type: ignore[assignment]
    strategy = rules.pick_strategy(label, text)
    notes.append(f"策略由标签确定：{label} -> {strategy}")
    context = {"text": text, "label": label}

    prompt = _prompt(text, sentiment)
    issue = ""
    result: ReplyResult | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        # 第一轮走 Triage（让 handoff 真的发生），之后直接找对应专家
        agent = TRIAGE if (strategy != "crisis" and attempt == 1) else SPECIALISTS[strategy]
        try:
            data, last = await _run(agent, prompt, context)
            notes.append(f"第{attempt}轮：{agent.name} -> 末位 Agent={last}")
            if agent is TRIAGE and last != SPECIALISTS[strategy].name:
                notes.append(f"handoff 落到 {last}，与标签不一致，改用 {SPECIALISTS[strategy].name} 重跑")
                data, last = await _run(SPECIALISTS[strategy], prompt, context)
                notes.append(f"纠正后末位 Agent={last}")
            result = ReplyResult.from_raw(data, strategy=strategy)  # type: ignore[arg-type]
        except OutputGuardrailTripwireTriggered as exc:
            issue = _issue_of(exc)
            notes.append(f"第{attempt}轮 output guardrail 拦截：{issue}")
            prompt = prompt + "\n\n" + prompts.REPLY_REGENERATE.format(issue=issue)
            continue
        except Exception as exc:  # noqa: BLE001
            notes.append(f"第{attempt}轮 Agent 失败，规则兜底：{type(exc).__name__}: {exc}")
            result = rules.rule_reply(label, text, strategy)
            break

        issue = rules.check_reply_rules(text, label, result.reply) or ""
        if not issue:
            notes.append(f"第{attempt}轮质检通过")
            break
        notes.append(f"第{attempt}轮质检不通过：{issue}")
        prompt = prompt + "\n\n" + prompts.REPLY_REGENERATE.format(issue=issue)

    if result is None:
        result = rules.rule_reply(label, text, strategy)
        notes.append("两轮都没拿到可用结果，用固定话术兜底")
    elif issue:
        notes.append(f"重写次数用尽，保留最后一版（仍有问题：{issue}）")

    if strategy == "crisis":
        hotline = "全国 24 小时心理援助热线 400-161-9995"
        if hotline not in result.reply:
            result.tips = list(dict.fromkeys([hotline, *(result.tips or [])]))[:3]
            notes.append("危机兜底：补上热线提示")

    result.notes = notes
    return result, notes, int((time.perf_counter() - started) * 1000)


# --------------------------------------------------------------------------- #
# HTTP 外壳
# --------------------------------------------------------------------------- #
class RespondRequest(BaseModel):
    text: str = ""
    sentiment: dict = {}
    session_id: str = "default"


app = service.create_app(NAME, "进程2 · 情绪回应（openai-agents）")


@app.post("/respond")
async def respond_endpoint(req: RespondRequest) -> dict:
    text = req.text.strip()[: config.MAX_INPUT_CHARS]
    result, _notes, ms = await respond(text, req.sentiment or {})
    service.log(NAME, f'respond "{text[:14]}" -> {result.strategy} ({ms}ms, {result.source})')
    return {"ok": True, "data": result.model_dump(), "ms": ms}


@app.get("/agents")
def describe() -> dict:
    def brief(agent: Agent) -> dict:
        return {
            "name": agent.name,
            "handoffs": [h.name for h in (agent.handoffs or [])],
            "tools": [t.name for t in (agent.tools or [])],
            "guardrails": ["tone_guardrail"] if agent.output_guardrails else [],
        }

    return {"agents": [brief(a) for a in (TRIAGE, _ENCOURAGER, _SOOTHER, _LISTENER, _CRISIS)]}


if __name__ == "__main__":
    service.serve(app, config.REPLY_PORT, NAME, "进程2：情绪回应（openai-agents）")
