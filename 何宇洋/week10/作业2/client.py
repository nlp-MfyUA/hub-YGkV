import os
import asyncio

from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import (
    Agent,
    Runner,
    ModelSettings,
    OpenAIChatCompletionsModel,
    set_tracing_disabled,
)
from agents.mcp.server import MCPServerSse

load_dotenv()
set_tracing_disabled(True)


async def main():

    # 初始化模型客户端
    external_client = AsyncOpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )

    model = OpenAIChatCompletionsModel(
        model=os.getenv("OPENAI_MODEL", "qwen-max"),
        openai_client=external_client,
    )

    # 连接 MCP Server
    async with MCPServerSse(
        name="Homework MCP Server",
        params={
            "url": "http://127.0.0.1:8000/sse"
        },
    ) as server:

        # 创建 Agent
        agent = Agent(
            name="MCP Assistant",
            instructions="""
            你是一个能够使用 MCP 工具的助手。

            根据用户的问题选择合适的工具：

            1. 数学运算使用 calculate。
            2. 文本统计使用 text_statistics。
            3. 温度转换使用 convert_temperature。
            4. 掷骰子使用 roll_dice。
            5. 获取示例新闻使用 get_news。

            对涉及工具功能的问题，必须调用工具，
            不要自行计算并冒充工具调用。
            使用中文回答用户。
            """,
            mcp_servers=[server],
            model=model,
            model_settings=ModelSettings(
                tool_choice="required"
            ),
        )

        # 分别测试三个新增工具
        messages = [
            "请使用计算器工具，计算 12.5 × 8。",
            "请使用文本统计工具，统计 Hello 中国 abc123",
            "请使用温度转换工具，将 30 摄氏度转换为华氏度。",
        ]

        for message in messages:

            print(f"\n用户：{message}")

            result = await Runner.run(
                starting_agent=agent,
                input=message,
            )

            # 查看 Agent 实际进行了哪些工具调用
            called_tools = [
                getattr(item.raw_item, "name", None)
                for item in result.new_items
                if item.type == "tool_call_item"
            ]

            print("调用工具：", called_tools)
            print("Agent：", result.final_output)


if __name__ == "__main__":
    asyncio.run(main())