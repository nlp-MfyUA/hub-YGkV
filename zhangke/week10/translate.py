import os
import asyncio
from agents import Agent, Runner
from agents import set_default_openai_api, set_tracing_disabled
from agents.exceptions import InputGuardrailTripwireTriggered
set_default_openai_api("chat_completions")
set_tracing_disabled(True)
os.environ["OPENAI_API_KEY"] = "sk-eea9470395544764b1de22f427cabdff"
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"


# 守卫检查代理 - 》 本质也是通过大模型调用完成的
distinguish_agent = Agent(
    name="distinguish Agent",
    model="deepseek-flash",
    instructions="判断用户的是什么语言，如果是中文，翻译为英文；如果是其他种类的语言，则翻译为中文，只输出json字符串"
                 "{\"input\": \"你好\", \"language\":\"中文\", \"result\":\"Hello\"} 其中"
                 "input对应的是用户的输入， language对应判断出来的用户输入的语言种类， result是翻译后的结果，不要输出任何其他内容。",
    #output_type=HomeworkOutput, # openai 官方推荐的一个语法，推荐大模型输出的格式类型，国内模型支持的不太好；
)
async def main():
    query = "greate!"
    print(f"**用户提问:** {query}")
    result = await Runner.run(distinguish_agent, query)
    print("\n**✅ 翻译结果:**")
    print(result.final_output)

    query = "机器学习"
    print(f"**用户提问:** {query}")
    result = await Runner.run(distinguish_agent, query)
    print("\n**✅ 翻译结果:**")
    print(result.final_output)

    query = "Bonjour"
    print(f"**用户提问:** {query}")
    result = await Runner.run(distinguish_agent, query)
    print("\n**✅ 翻译结果:**")
    print(result.final_output)

if __name__ == "__main__":
    asyncio.run(main())



