import os

# https://bailian.console.aliyun.com/?tab=model#/api-key
os.environ["OPENAI_API_KEY"] = "sk-a581e3621c3c4f5d9429f8a2de31b860"
os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents.mcp.server import MCPServerSse
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

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
            model="qwen-max",
            openai_client=external_client,
        )
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
