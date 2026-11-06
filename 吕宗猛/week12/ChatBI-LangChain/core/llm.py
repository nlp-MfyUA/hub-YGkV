"""模型接入层：langchain ChatOpenAI 封装、Agent 运行与计时/用量采集。

与原 openai-agents 版的对应关系：
- OpenAIChatCompletionsModel          → langchain_openai.ChatOpenAI（同一 OpenAI 兼容网关）
- Agent + Runner.run + StopAtTools    → langchain.agents.create_agent（框架自动调度工具）
- context_wrapper.usage               → 每条 AIMessage.usage_metadata 累加
- RunResult.new_items 工具轨迹        → AIMessage.tool_calls 收集
- RunContextWrapper 收口容器          → 每请求独立的 store dict，由 agent 模块自持
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

import config

_models: dict[tuple, ChatOpenAI] = {}


def model(name: str, *, temperature: float = 0.0, max_tokens: int = 1200) -> ChatOpenAI:
    """按「模型名 + 采样设置」缓存的 ChatOpenAI 实例。"""
    key = (name, temperature, max_tokens)
    if key not in _models:
        _models[key] = ChatOpenAI(
            model=name,
            base_url=config.BASE_URL,
            api_key=config.API_KEY or "EMPTY",
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=config.LLM_TIMEOUT_SECONDS,
            max_retries=1,
        )
    return _models[key]


def usage_dict(usage: Any) -> dict:
    """把 langchain 的 usage_metadata 归一成四键形状（与原版一致）。"""
    if not usage:
        return {}
    if isinstance(usage, dict):
        return {
            "requests": int(usage.get("requests", 1) or 1),
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
        }
    return {
        "requests": getattr(usage, "requests", 1),
        "input_tokens": getattr(usage, "input_tokens", 0),
        "output_tokens": getattr(usage, "output_tokens", 0),
        "total_tokens": getattr(usage, "total_tokens", 0),
    }


def merge_usage(target: dict, extra: dict) -> dict:
    for key in ("requests", "input_tokens", "output_tokens", "total_tokens"):
        target[key] = target.get(key, 0) + int(extra.get(key, 0) or 0)
    return target


def message_text(message: BaseMessage) -> str:
    """AIMessage.content 可能是 str 或多块列表，统一取纯文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)


def tool_trace(result: dict) -> list[dict]:
    """把一次 Agent 运行中的工具调用整理成前端可展示的轨迹。"""
    trace: list[dict] = []
    for message in result.get("messages", []):
        if not isinstance(message, AIMessage):
            continue
        for call in getattr(message, "tool_calls", None) or []:
            args = str(call.get("args", "") or "")
            if len(args) > 240:
                args = args[:240] + "…"
            trace.append({"name": call.get("name") or "tool", "args": args})
    return trace


@dataclass
class AgentRun:
    output: Any
    elapsed_ms: float
    usage: dict = field(default_factory=dict)
    tools: list[dict] = field(default_factory=list)
    error: str | None = None
    state: dict | None = None  # create_agent 终态（含全部消息），供上层做兜底解析

    @property
    def ok(self) -> bool:
        return self.error is None


async def run_agent(
    llm: ChatOpenAI,
    *,
    name: str,
    system_prompt: str,
    user_input: str,
    tools: list[BaseTool],
    max_turns: int = 6,
    retries: int = 1,
    timeout: float | None = None,
) -> AgentRun:
    """运行 langchain Agent 并采集耗时与用量；失败重试一次。

    max_turns 语义与原版一致：允许模型发起的工具调用轮数上限，
    换算成 langgraph 的 recursion_limit（每轮 = 模型 + 工具两条消息）。
    """
    agent = create_agent(llm, tools, system_prompt=system_prompt, name=name)
    recursion_limit = max_turns * 2 + 4
    last_error = ""
    overall_started = time.perf_counter()
    for attempt in range(retries + 1):
        started = time.perf_counter()
        try:
            call = _invoke(agent, user_input, recursion_limit)
            result = await (asyncio.wait_for(call, timeout=timeout) if timeout else call)

            usage = {"requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
            final_text = ""
            for message in result.get("messages", []):
                if not isinstance(message, AIMessage):
                    continue
                merge_usage(usage, usage_dict(getattr(message, "usage_metadata", None)))
                text = message_text(message)
                # 收口工具调用后模型会补一句确认话术；取最后一条纯文本作为最终输出
                if text.strip() and not getattr(message, "tool_calls", None):
                    final_text = text.strip()
            return AgentRun(
                output=final_text,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                usage=usage,
                tools=tool_trace(result),
                state=result,
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


async def _invoke(agent, user_input: str, recursion_limit: int) -> dict:
    return await agent.ainvoke(
        {"messages": [("user", user_input)]},
        config={"recursion_limit": recursion_limit},
    )
