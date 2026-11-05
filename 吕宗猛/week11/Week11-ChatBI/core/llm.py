"""模型接入层：统一的 AsyncOpenAI 客户端、Agent 运行封装与计时/用量采集。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from agents import Runner, RunResult, set_tracing_disabled
from agents.items import ToolCallItem
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

import config

# 不使用 OpenAI 官方 trace 上传（网关无此能力）
set_tracing_disabled(True)

_client: AsyncOpenAI | None = None
_models: dict[str, OpenAIChatCompletionsModel] = {}


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url=config.BASE_URL,
            api_key=config.API_KEY or "EMPTY",
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _client


def model(name: str) -> OpenAIChatCompletionsModel:
    if name not in _models:
        _models[name] = OpenAIChatCompletionsModel(model=name, openai_client=client())
    return _models[name]


def usage_dict(usage: Any) -> dict:
    if usage is None:
        return {}
    return {
        "requests": getattr(usage, "requests", 0),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


def merge_usage(target: dict, extra: dict) -> dict:
    for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
        target[key] = target.get(key, 0) + int(extra.get(key, 0) or 0)
    return target


def tool_trace(result: RunResult) -> list[dict]:
    """把一次 Agent 运行中的工具调用整理成前端可展示的轨迹。"""
    trace: list[dict] = []
    for item in result.new_items:
        if not isinstance(item, ToolCallItem):
            continue
        raw = item.raw_item
        name = (
            getattr(item, "_resolved_tool_name", None)
            or getattr(raw, "name", None)
            or "tool"
        )
        args = getattr(raw, "arguments", "") or ""
        if len(args) > 240:
            args = args[:240] + "…"
        trace.append({"name": name, "args": args})
    return trace


@dataclass
class AgentRun:
    output: Any
    elapsed_ms: float
    usage: dict = field(default_factory=dict)
    tools: list[dict] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


async def run_agent(
    agent,
    user_input: str | list,
    *,
    context: Any,
    max_turns: int = 8,
    retries: int = 1,
    timeout: float | None = None,
) -> AgentRun:
    """运行 Agent 并采集耗时与用量；失败重试一次，仍失败则返回结构化错误。"""
    last_error = ""
    overall_started = time.perf_counter()
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            call = Runner.run(agent, user_input, context=context, max_turns=max_turns)
            result = await (asyncio.wait_for(call, timeout=timeout) if timeout else call)
            return AgentRun(
                output=result.final_output,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                usage=usage_dict(result.context_wrapper.usage),
                tools=tool_trace(result),
            )
        except asyncio.TimeoutError:
            last_error = f"模型 {timeout:g}s 内未返回（超时）"
        except Exception as exc:  # noqa: BLE001 - 网关异常需要转成可展示信息
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            await asyncio.sleep(0.6)
    return AgentRun(
        output=None,
        # 失败也要如实记录墙钟耗时，避免页面上把超时显示成几毫秒
        elapsed_ms=(time.perf_counter() - overall_started) * 1000,
        usage={},
        tools=[],
        error=last_error or "未知错误",
    )
