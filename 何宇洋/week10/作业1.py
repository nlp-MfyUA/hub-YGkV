import os
import asyncio
import json

from pydantic import BaseModel
from dotenv import load_dotenv
from openai import AsyncOpenAI
from agents import (
    Agent,
    Runner,
    OpenAIChatCompletionsModel,
    set_tracing_disabled,
)

load_dotenv()
set_tracing_disabled(True)


class TranslationResult(BaseModel):
    query_input: str
    language: str
    result: str


client = AsyncOpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), # DeepSeek目前不支持openai-agents的结构化输出，要跑通得换模型
    base_url="https://api.deepseek.com"
)

model = OpenAIChatCompletionsModel(
    model="deepseek-flash",
    openai_client=client
)

agent = Agent(
    name="TranslationAgent",
    instructions="""
    判断用户输入的语言。
    如果是中文，翻译成英文。
    如果不是中文，翻译成简体中文。

    query_input：原始输入文本
    language：识别出的语言名称
    result：翻译结果
    """,
    model=model,
    output_type=TranslationResult,
)


async def main():
    text = input("请输入文本：")

    result = await Runner.run(
        starting_agent=agent,
        input=text
    )

    print(json.dumps(
        result.final_output.model_dump(),
        ensure_ascii=False,
        indent=4
    ))


if __name__ == "__main__":
    asyncio.run(main())