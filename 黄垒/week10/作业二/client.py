"""
作业二 · MCP Client（OpenAI Agents SDK 调用 MCP 工具）

基于课堂代码 `2-fastmcp使用/2-兼容OpenAI-Agent/client.py`，做了两处增强：
    1. 启动后先 `list_tools()` 打印 mcp server 暴露的全部工具（名字 / 参数 / 说明）；
    2. 每次运行后打印 Agent 的执行链路（选了哪个工具、传了什么参数、工具返回了什么），
       直观看到 step1~step4 的过程。

先启动 server，再运行 client：
    python server.py
    python client.py                  # 跑内置的 5 个用例
    python client.py -q "现在东京几点？"   # 单条提问
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from agents import (  # noqa: E402
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    Runner,
    set_default_openai_api,
    set_tracing_disabled,
)
from agents.items import ToolCallItem, ToolCallOutputItem  # noqa: E402
from agents.mcp import MCPServer, MCPServerSse  # noqa: E402

set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# Windows 下 stdout 被重定向（管道 / 写文件）时默认用 GBK，中文会乱码，这里统一成 UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

INSTRUCTIONS = """你是一个助手，可以调用工具回答问题。

工具使用原则：
- 问现在几点、日期、某时区时间 -> 用 get_current_time
- 需要做数学计算 -> 用 calculate，不要自己心算
- 问某个城市天气 -> 用 get_weather
- 问最新消息 / 新闻 -> 用 get_news
- 让摇骰子 -> 用 roll_dice
工具返回结果后，用简洁的中文回答用户，不要编造工具没有返回的信息。
"""

# 每条消息分别命中一个工具，方便观察 agent 的工具选择能力
DEMO_QUESTIONS = [
    "最近有什么新闻？",                     # get_news
    "摇3次骰子得到结果。",                   # roll_dice
    "现在北京时间几点？",                    # get_current_time
    "(123 + 456) * 2 / 3 等于多少？",        # calculate
    "深圳今天天气怎么样？",                   # get_weather
]


def build_model() -> OpenAIChatCompletionsModel:
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        sys.exit("缺少 LLM_API_KEY，请先把 .env.example 复制为 .env 并填入自己的 Key。")
    return OpenAIChatCompletionsModel(
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        openai_client=AsyncOpenAI(
            api_key=api_key,
            base_url=os.environ.get("LLM_BASE_URL"),
        ),
    )


def print_trace(result) -> None:
    """打印一次 Runner.run 的执行链路：工具调用 -> 工具返回 -> 最终回答。"""
    for item in result.new_items:
        if isinstance(item, ToolCallItem):
            raw = item.raw_item
            print(f"    [tool call]   {raw.name}({raw.arguments})")
        elif isinstance(item, ToolCallOutputItem):
            print(f"    [tool result] {item.output}")


async def ask(agent: Agent, message: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"用户: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print_trace(result)
    print(f"Agent: {result.final_output}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 调用 MCP 工具")
    parser.add_argument("-q", "--query", help="单条提问；不传则跑内置用例")
    parser.add_argument("--url", default="http://localhost:8000/sse", help="MCP server 的 SSE 地址")
    args = parser.parse_args()

    async with MCPServerSse(name="SSE Python Server", params={"url": args.url}) as server:
        # step1: 通过 mcp client list_tools，拿到 server 提供的工具清单
        tools = await server.list_tools()
        print(f"已连接 MCP Server：{args.url}")
        print(f"可用工具共 {len(tools)} 个：")
        for tool in tools:
            params = list((tool.input_schema or {}).get("properties", {})) or ["-"]

            # 说明只取第一行，避免刷屏
            desc = (tool.description or "").strip().splitlines()[0] if tool.description else "-"
            print(f"  - {tool.name}({', '.join(params)}) : {desc}")

        agent = Agent(
            name="Assistant",
            instructions=INSTRUCTIONS,
            mcp_servers=[server],  # tools：MCP server 托管的工具
            model=build_model(),
        )

        for question in [args.query] if args.query else DEMO_QUESTIONS:
            await ask(agent, question)


if __name__ == "__main__":
    asyncio.run(main())
