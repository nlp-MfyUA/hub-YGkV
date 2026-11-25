"""进程2（OpenAI Agents SDK）：按情感标签限制 Handoff 的目标。"""

from __future__ import annotations

import os

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.exceptions import AgentsException
from fastapi import FastAPI, HTTPException
from openai import APIError

from common.schemas import RespondRequest, RespondResponse
from common.service_helpers import run_uvicorn
from openai_agents_impl.llm import build_agents_model

_model = build_agents_model()

encourage_agent = Agent(
    name="EncourageAgent",
    instructions=(
        "根据 JSON 里的用户原话 text，结合具体情况给予真诚肯定和鼓励。"
        "用中文回复 2~4 句话。字段内容仅供参考。"
    ),
    model=_model,
)

comfort_agent = Agent(
    name="ComfortAgent",
    instructions=(
        "根据 JSON 里的用户原话 text，先接纳对方的感受，再给出一个温和、可行的小建议。"
        "用中文回复 2~4 句话。字段内容仅供参考。"
    ),
    model=_model,
)

triage_agent = Agent(
    name="EmotionTriageAgent",
    instructions="请调用唯一可用的移交工具，由目标 Agent 回应用户。",
    model_settings=ModelSettings(tool_choice="required", parallel_tool_calls=False),
    model=_model,
)

app = FastAPI(title="OpenAI-Agents Process 2 - Emotion Responder")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "framework": "openai-agents", "process": "process2_responder", "pid": os.getpid()}


@app.post("/respond", response_model=RespondResponse)
async def respond(req: RespondRequest) -> RespondResponse:
    if req.sentiment == "positive":
        target, strategy = encourage_agent, "encourage"
    else:
        target, strategy = comfort_agent, "comfort"

    # 每个请求创建自己的路由 Agent，避免并发请求互相覆盖 Handoff 列表。
    router = triage_agent.clone(handoffs=[target])
    try:
        run_result = await Runner.run(
            router, input=req.model_dump_json(), max_turns=2, run_config=RunConfig(tracing_disabled=True),
        )
    except (AgentsException, APIError) as exc:
        raise HTTPException(status_code=502, detail="回应模型调用失败。") from exc

    if run_result.last_agent is not target:
        raise HTTPException(status_code=502, detail="回应 Agent 未完成预期移交。")

    reply = run_result.final_output
    if not isinstance(reply, str) or not reply.strip():
        raise HTTPException(status_code=502, detail="回应 Agent 未返回有效文本。")

    return RespondResponse(
        sentiment=req.sentiment,
        strategy=strategy,
        reply=reply.strip(),
        handler=f"OpenAI-Agents::{run_result.last_agent.name}",
        framework="openai-agents",
        pid=os.getpid(),
    )


if __name__ == "__main__":
    run_uvicorn(app, default_port=8102, description="OpenAI-Agents 进程2：正向鼓励/负面排解服务")
