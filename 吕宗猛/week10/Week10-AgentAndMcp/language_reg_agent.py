from os import getenv
from dotenv import load_dotenv
from agents import Agent, Runner
from agents import set_default_openai_api, set_tracing_disabled
from pydantic import BaseModel, Field
from typing import Literal

# 使用env文件中的环境变量，覆盖系统本身的同名环境变量
load_dotenv(override=True)

MODEL_NAME = getenv("MODEL_NAME")

# 设置默认的api为chat
set_default_openai_api("chat_completions")
# 关闭trace链路追踪
set_tracing_disabled(True)


# class TranslationModel(BaseModel):
#     query_input: str = Field(description="用户的输入")
#     language: str = Field(description="语种")
#     result: str = Field(description="翻译结果")


propmt = """
你是一个专业的语言专家，判断用户输入文本的语种，并进行翻译。
如果语种为中文，则翻译为英语；语种为非中文，则翻译为中文。
并使用json输出，json输出格式为：
{
    "query_input": "",
    "language": "",
    "result": ""
}
"""

# 未使用output_type
# 使用后，会自动转换为对象，输出时调用对象默认的str函数
agent = Agent(
    model=MODEL_NAME,
    name="TranslateAssistant",
    instructions=propmt
)

print("*" * 10 + "语种识别Agent测试" + "*" * 10)
while True:
    user_input = input("请输入您要识别的文本(q为退出)：")
    if user_input != "q":
        result = Runner.run_sync(agent, user_input)
        print(f'识别结果:\n{result.final_output}')
    else:
        print("系统即将退出......")
        break
