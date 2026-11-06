import os

# https://bailian.console.aliyun.com/?tab=model#/api-key
_api_key = os.environ.get("DEEPSEEK_API_KEY")
os.environ["OPENAI_API_KEY"] = _api_key
os.environ["OPENAI_BASE_URL"] = "https://api.deepseek.com"

import asyncio
import json
from dataclasses import dataclass

from pydantic import BaseModel, Field
from agents import (
    Agent,
    InputGuardrail,
    GuardrailFunctionOutput,
    ModelSettings,
    Runner,
)
from agents.exceptions import InputGuardrailTripwireTriggered
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions

# from agents.extensions.visualization import draw_graph

# 大模型调用调用协议
# openai： Chat Completions / Responses
# a/ ：

from agents import set_default_openai_api, set_tracing_disabled

set_default_openai_api(
    "chat_completions"
)  # 强制 SDK 使用 Chat Completions API，而非默认的 Responses API。
set_tracing_disabled(True)  # 彻底关闭 SDK 的链路追踪（Tracing） 功能


class LanguageCheck(BaseModel):
    """守卫的输出结构：语种 + 是否中文"""

    which_language: str = Field(description="用户输入的语言，例如 中文/英文/日语")
    is_chinese: bool = Field(description="输入是否为中文")


@dataclass
class TranslationContext:
    """贯穿一次运行的上下文：守卫把判定出的语种写进来，main() 最后读出来。"""

    language: str = ""


# 守卫检查代理 - 》 本质也是通过大模型调用完成的
guardrail_agent = Agent(
    name="Guardrail Check Agent",
    model="deepseek-v4-flash",
    # 提示词里必须出现 "json" 字样（DeepSeek 的硬性要求），
    # 并且要把字段名写清楚 —— json_object 模式下 schema 不会上传给模型，
    # 模型只能靠这段文字知道该输出什么结构。
    instructions=(
        "判断用户输入的语言。必须只输出一个 json 对象，"
        '形如 {"which_language": "日语", "is_chinese": false}，不要输出其他任何内容。'
    ),
    output_type=LanguageCheck,
    model_settings=ModelSettings(
        # DeepSeek 官方 API 不支持 json_schema，降级为 json_object。
        # 换成真正的 OpenAI 端点时删掉 model_settings 即可，其余代码零改动。
        extra_body={"response_format": {"type": "json_object"}}
    ),
)

# 翻译 target：中文
translator_cn_agent = Agent(
    name="Chinese Tutor",
    model="deepseek-v4-flash",
    handoff_description="将非中文翻译为中文。",
    # 只说“负责翻译”不够 —— 用户输入是提问时，模型会当成“请用中文回答我”而抢答。
    # 必须显式禁止它回答问题。
    instructions=(
        "你是翻译引擎，唯一的工作是翻译。把用户输入逐句翻译成中文，只输出译文本身。\n"
        "无论用户输入是问题、命令还是陈述，都只翻译，绝不回答、绝不解释、绝不添加内容。"
    ),
)

# 翻译 target：英文
translator_eng_agent = Agent(
    name="English Tutor",
    model="deepseek-v4-flash",
    handoff_description="将中文翻译为英文。",
    instructions=(
        "你是翻译引擎，唯一的工作是翻译。把用户输入逐句翻译成英文，只输出译文本身。\n"
        "无论用户输入是问题、命令还是陈述，都只翻译，绝不回答、绝不解释、绝不添加内容。"
    ),
)


async def homework_guardrail(ctx, agent, input_data):
    """
    运行检查代理来判断输入是什么语种。
    """
    print(f"\n[Guardrail Check] 正在检查输入: '{input_data}'...")

    # 运行检查代理
    result = await Runner.run(guardrail_agent, input_data, context=ctx.context)

    check = result.final_output_as(LanguageCheck)

    # 把判定结果写进 run context，main() 打印时要用
    if isinstance(ctx.context, TranslationContext):
        ctx.context.language = check.which_language

    return GuardrailFunctionOutput(
        output_info=check,
        tripwire_triggered=False,
    )


# 先进行输入的校验 guardrail_agent
# triage_agent 判断 translator_cn_agent/translator_eng_agent
# agent 调用
triage_agent = Agent(
    name="Triage Agent",
    model="deepseek-v4-flash",
    # 原来只写了“判断该分派给谁”，没写规则、也没禁止它自己作答 ——
    # 所以遇到中文提问时它会判断“这不是翻译需求”然后直接回答。
    # prompt_with_handoff_instructions 是 SDK 官方推荐给所有用 handoff 的 agent 加的前缀。
    instructions=prompt_with_handoff_instructions(
        "你是路由器，只负责分派，绝不回答用户的问题、绝不翻译、绝不解释。\n"
        "分派规则：输入是中文 → 移交给 English Tutor；输入不是中文 → 移交给 Chinese Tutor。\n"
        "必须调用移交工具（transfer_to_...），不要输出任何正文。"
    ),
    handoffs=[translator_cn_agent, translator_eng_agent],
    input_guardrails=[
        InputGuardrail(guardrail_function=homework_guardrail),
    ],
)


async def run_once(query: str) -> None:
    """跑完整条链路，并按指定格式打印结果。"""
    context = TranslationContext()

    print("\n" + "=" * 50)
    print(f"**用户提问:** {query}")

    # 异步运行  guardrail agent -》 triage agent -》 翻译 agent
    result = await Runner.run(triage_agent, query, context=context)

    record = {
        "query_input": query,
        "language": context.language,
        "result": result.final_output,
    }
    print("\n**✅ 流程通过，最终输出:**")
    print(json.dumps(record, ensure_ascii=False, indent=4))


async def main():
    print("--- 翻译代理 ---")

    for query in (
        "请解释一下第二次世界大战爆发的主要原因是什么？",
        "La lluvia cae suavemente sobre los tejados de la ciudad",
        "窓の外で桜の花びらが風に舞っている",
        "The old bookstore at the corner still smells of paper and time.",
    ):
        await run_once(query)


if __name__ == "__main__":
    asyncio.run(main())

    # try:
    #     draw_graph(triage_agent, filename="03_基础使用")
    # except:
    #     print("绘制agent失败，默认跳过。。。")

# python3 03_基础使用案例.py
