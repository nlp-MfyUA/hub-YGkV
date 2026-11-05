# 作业：自己增加三个 MCP 工具，并由 Agent 调用。
# 这是一个文件，里面有两个角色：
#   python task2.py --server    只启动工具服务器
#   python task2.py             启动服务器，再让 Agent 提问
#
# 运行前先准备密钥，写法和课程 client.py 一样：
#   os.environ["OPENAI_API_KEY"] = "你的密钥"
#   os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

import asyncio
import os
import socket
import subprocess
import sys
import time

from fastmcp import FastMCP
from agents import Agent, AsyncOpenAI, OpenAIChatCompletionsModel, Runner
from agents import set_default_openai_api, set_tracing_disabled
from agents.mcp.server import MCPServerSse

# 国内兼容接口走 Chat Completions，并关掉追踪上报。
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

PORT = 8765
SERVER_URL = f"http://127.0.0.1:{PORT}/sse"

# ---------------------------------------------------------------------------
# 三个 MCP 工具。模型靠函数名、参数类型、返回类型和英文说明来选择。
# ---------------------------------------------------------------------------

mcp = FastMCP(name="Homework Tools")


@mcp.tool
def get_weather(city: str) -> str:
    """Get today's weather for a city. Use this when the user asks about weather."""
    table = {
        "北京": "晴，26摄氏度",
        "上海": "多云，24摄氏度",
        "深圳": "阵雨，29摄氏度",
    }
    return f"{city}：{table.get(city, '晴，25摄氏度')}"


@mcp.tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the sum. Use this when the user asks to add numbers."""
    return a + b


@mcp.tool
def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit. Use this when the user asks to convert temperature."""
    return celsius * 9 / 5 + 32


def run_server() -> None:
    """启动 MCP 服务器。Agent 通过 SERVER_URL 来拿工具名单并执行工具。"""
    mcp.run(transport="sse", port=PORT, show_banner=False)


def wait_until_ready() -> None:
    """等端口打开。服务器刚启动时，客户端立刻连接会失败。"""
    for _ in range(50):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", PORT)) == 0:
                return
        time.sleep(0.1)
    raise SystemExit("MCP 服务器没有在 8765 端口启动。")


async def ask_agent() -> None:
    """连上本机 MCP 服务器，让 Agent 自己选择三个工具。"""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("请先设置 OPENAI_API_KEY。写法见本文件最上面的注释。")
    base_url = os.environ.get(
        "OPENAI_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    model_name = os.environ.get("OPENAI_MODEL", "qwen-max")

    external_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    async with MCPServerSse(
        name="Homework Tools",
        params={"url": SERVER_URL},
    ) as server:
        agent = Agent(
            name="Assistant",
            instructions="Use a tool when it matches the question. Answer in Chinese.",
            mcp_servers=[server],
            model=OpenAIChatCompletionsModel(
                model=model_name,
                openai_client=external_client,
            ),
        )
        questions = [
            "北京今天天气怎么样？",
            "请计算 17 加 25。",
            "20 摄氏度是多少华氏度？",
        ]
        for message in questions:
            print(f"Running: {message}")
            result = await Runner.run(starting_agent=agent, input=message)
            print(result.final_output)
            print("-" * 40)


def main() -> None:
    # 同一个文件被再次启动时，只负责当服务器。
    if "--server" in sys.argv:
        run_server()
        return

    # 再开一个进程跑本文件的服务器角色，然后本进程当 Agent 客户端。
    server_process = subprocess.Popen([sys.executable, __file__, "--server"])
    try:
        wait_until_ready()
        asyncio.run(ask_agent())
    finally:
        server_process.terminate()
        server_process.wait(timeout=5)


if __name__ == "__main__":
    main()
