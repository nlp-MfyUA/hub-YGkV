from agents import set_default_openai_api, OpenAIChatCompletionsModel, set_tracing_disabled
from openai import AsyncOpenAI
from dotenv import load_dotenv
import os

# 1.加载环境变量
if not load_dotenv(".env"):
    raise FileNotFoundError("环境配置.env不存在")

# 2.读取环境变量
if not (BASE_URL := os.getenv("BASE_URL")):
    raise RuntimeError("BASE_URL不存在，请检查.env文件内容")

if not (API_KEY := os.getenv("API_KEY")):
    raise RuntimeError("API_KEY不存在，请检查.env文件内容")

if not (MODEL := os.getenv("MODEL")):
    raise RuntimeError("MODEL不存在，请检查.env文件内容")

# 3.创建模型对象
client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
model = OpenAIChatCompletionsModel(model=MODEL, openai_client=client)
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# 4. Agent输出结果
from pydantic import BaseModel, Field

class Output(BaseModel):
    query_input: str = Field(description="用户原始输入，原样保留")
    language: str = Field(description="用户输入的语种")
    result: str = Field(description="将query_input翻译成目标语言后的译文，必须是目标语言，不得与query_input相同")

