"""OpenAI Agents SDK 的模型接入。

三点必须交代清楚，否则在非 OpenAI 的模型上跑不起来：

1. `set_default_openai_client` + `OpenAIChatCompletionsModel`：
   Agents SDK 默认走 OpenAI Responses API，DeepSeek 只有 Chat Completions，
   所以显式指定「用这个 client、走 chat completions、模型名是 xxx」。
2. `set_tracing_disabled(True)`：SDK 默认会把 trace 上报到 OpenAI 平台，
   没有 OpenAI Key 时会一直报 401/超时，本地开发必须先关掉。
3. `output_type`（结构化输出）在 Chat Completions 下会被转成
   `response_format={"type":"json_schema"}`，DeepSeek 目前不支持（会 400）。
   所以本作业改用「提交工具 + stop_on_first_tool」拿结构化结果：
   Agent 调 `submit_xxx(...)`，工具返回 JSON 字符串，`final_output` 就是这个字符串。
   —— 这也是对接国产模型时最稳的一种结构化输出写法。
"""

from __future__ import annotations

from agents import ModelSettings, OpenAIChatCompletionsModel, RunConfig, set_tracing_disabled
from openai import AsyncOpenAI

from common import config

set_tracing_disabled(True)

_CLIENT = AsyncOpenAI(
    api_key=config.LLM_API_KEY or "EMPTY",
    base_url=config.LLM_BASE_URL,
    timeout=config.LLM_TIMEOUT,
)

MODEL = OpenAIChatCompletionsModel(model=config.LLM_MODEL, openai_client=_CLIENT)

# 所有 Runner.run 共用：模型 + 关掉 trace 上报
RUN_CONFIG = RunConfig(model=MODEL, tracing_disabled=True, workflow_name="week15-情感陪伴")

COLD = ModelSettings(temperature=0.0)      # 识别 / 调度：要稳定
WARM = ModelSettings(temperature=0.8)      # 写回应：要温度
