import asyncio

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from agents import Agent, OpenAIChatCompletionsModel, Runner, set_tracing_disabled

"""语言检测与翻译示例：检测输入文本的语种，中文翻译为英文，其他语种翻译为中文。
使用 DeepSeek API。
"""

# ============================================================
# 配置：请替换为你的 DeepSeek API 信息
# ============================================================
BASE_URL = "https://api.deepseek.com"   # DeepSeek 接口地址
API_KEY = ""                             # 你的 DeepSeek API Key
MODEL_NAME = "deepseek-chat"             # 模型名称

client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
set_tracing_disabled(disabled=True)


class TranslationResult(BaseModel):
    query_input: str = Field(description="用户输入的原始文本")
    language: str = Field(description="检测到的语种")
    result: str = Field(description="翻译结果")


async def main():
    agent = Agent(
        name="语言检测与翻译助手",
        instructions="你是一个语言检测与翻译助手。收到用户输入的文本后："
        "1. 判断文本的语种；"
        "2. 如果文本是中文，翻译为英文；"
        "3. 如果文本不是中文，翻译为中文。",
        output_type=TranslationResult,
        model=OpenAIChatCompletionsModel(model=MODEL_NAME, openai_client=client),
    )

    user_input = input("请输入要翻译的文本：")
    result = await Runner.run(agent, user_input)
    print(result.final_output.model_dump_json(indent=2, ensure_ascii=False))
    # 输入 "Hello, how are you?" 时输出：
    # {
    #   "query_input": "Hello, how are you?",
    #   "language": "English",
    #   "result": "你好，你怎么样？"
    # }
    # 输入 "今天天气很好" 时输出：
    # {
    #   "query_input": "今天天气很好",
    #   "language": "中文",
    #   "result": "The weather is great today."
    # }


if __name__ == "__main__":
    asyncio.run(main())