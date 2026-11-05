
from agents import Agent, set_default_openai_api, set_tracing_disabled, OpenAIChatCompletionsModel, Runner
from agents.mcp import MCPServerStreamableHttp
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os
import sys

if not load_dotenv(".env"):
    raise FileNotFoundError(".env file not found")

BASE_URL = os.environ["BASE_URL"]
API_KEY = os.environ["API_KEY"]
MODEL = os.environ["MODEL"]

client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
model = OpenAIChatCompletionsModel(model=MODEL, openai_client=client)
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

class MyAgent:
    def __init__(self, prompt: str):

        self.agent = Agent(
            name="MyAgent",
            instructions=prompt,
            model=model
        )

    def bind_mcp(self, server):
        self.agent.mcp_servers = [server]

    async def call(self, prompt: str) -> str:
        async with MCPServerStreamableHttp(
            params={
                'url': "http://localhost:8000/mcp"
            }
        ) as server:

            self.bind_mcp(server)
            result = await Runner.run(self.agent, prompt)
            return result.final_output


if __name__ == "__main__":
    agent = MyAgent("你是一个有用的助手")

    import asyncio
    print(asyncio.run(agent.call("今天是几月几号")))
