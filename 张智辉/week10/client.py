import os
from dotenv import load_dotenv

load_dotenv()
os.environ["OPENAI_BASE_URL"] = os.getenv("OPENAI_API_URL", "")

import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel, ModelSettings
from agents.mcp import MCPServer
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# 关闭推理模型的思考过程（DeepSeek 风格）
NO_THINKING_SETTINGS = ModelSettings(extra_body={"thinking": {"type": "disabled"}})

async def run(mcp_server: MCPServer):
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )

    # openai agent
    agent = Agent(
        name="Assistant",
        instructions="",
        mcp_servers=[mcp_server], # tools
        model=OpenAIChatCompletionsModel(
            model="MiniMax-M3",
            openai_client=external_client,
        ),
        model_settings=NO_THINKING_SETTINGS,
    )

    # 人传入tool，function call execute tool
    message = "最近有什么新闻？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)
    # 等同于：工具选择、工具调用、工具回答的总结

    """
    step1，通过mcp client mcp list tool，得到mcp server 可选的工具、工具的参数、返回格式
    step2， 工具、工具的参数、返回格式 汇总为 tools / function call 的格式 通过大模型 选择一个工具 -》 传入参数
    step3, 通过mcp client 调用execute tool 在mcp server 执行这个工具 -》 返回结果
    step4， 返回结果汇总在提示词，调用大模型得到结果
    """


    # tool 11 17 13
    message = "摇3次骰子得到结果。"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)


    # ── 新增 3 个工具调用测试 ──
    # 1) 股价查询
    message = "帮我查一下苹果公司（代码 AAPL）的股价，再看看贵州茅台 600519 现在多少钱。"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    # 2) 天气查询
    message = "今天北京和深圳的天气怎么样？"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)

    # 3) 随机数生成
    message = "在 1 到 100 之间给我随机抽一个幸运数字。"
    print(f"\nRunning: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)


async def main():
    # 定义了远程 mcp server 链接方式
    async with MCPServerSse(
            name="SSE Python Server",
            params={
                "url": "http://localhost:8000/sse", # mcp server 通过http 方式沟通
            },
    ) as server:
        await run(server)

if __name__ == "__main__":
    asyncio.run(main())
