import os

# https://bailian.console.aliyun.com/?tab=model#/api-key
os.environ["OPENAI_API_KEY"] = "sk-78cc4e9ac8f44efdb207b7232e1ae6d8"
os.environ["OPENAI_BASE_URL"] = "https://dashscope.aliyuncs.com/compatible-mode/v1"

from agents.mcp.server import MCPServerSse
import asyncio
from agents import Agent, Runner, AsyncOpenAI, OpenAIChatCompletionsModel
from agents.mcp import MCPServer
from agents import set_default_openai_api, set_tracing_disabled
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

async def run(mcp_server: MCPServer):
    external_client = AsyncOpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        base_url=os.environ["OPENAI_BASE_URL"],
    )
    agent = Agent(
        name="Assistant",
        instructions="",
        mcp_servers=[mcp_server],
        model=OpenAIChatCompletionsModel(
            model="qwen-max",
            openai_client=external_client,
        )
    )

    message = "最近有什么新闻？"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)


    message = "摇3次骰子得到结果。"
    print(f"Running: {message}")
    result = await Runner.run(starting_agent=agent, input=message)
    print(result.final_output)



async def main():
    async with MCPServerSse(
            name="SSE Python Server",
            params={
                "url": "http://localhost:8000/sse",
            },
    )as server:
        await run(server)

if __name__ == "__main__":
    asyncio.run(main())
