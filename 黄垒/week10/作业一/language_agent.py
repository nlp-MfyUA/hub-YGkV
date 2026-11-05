"""
作业一：语种识别 + 双向翻译 Agent（OpenAI Agents SDK）

需求：
    用户输入一段文本 -> 判断文本的语种；
    非中文 -> 翻译为中文；中文 -> 翻译为英文；
    最终输出固定 JSON：
    {
        "query_input": "",
        "language": "",
        "result": ""
    }

实现说明：
    openai-agents 官方推荐用 Agent(output_type=PydanticModel) 约束模型输出，
    但国内模型（DeepSeek / Qwen 等）走 chat_completions 协议时不支持
    response_format=json_schema（实测 DeepSeek 直接返回 400：
    "This response_format type is unavailable now"）。
    所以这里采用课堂上讲的做法：让 agent 直接输出 JSON 文本，
    拿到 final_output 后自己解析 + Pydantic 校验，解析失败则让模型修正后重试。

运行：
    python language_agent.py "Hello, how are you?"     # 单条文本
    python language_agent.py                          # 跑内置的多语种演示用例
    python language_agent.py -q "こんにちは、元気ですか？"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# 从同目录 .env 读取大模型配置（LLM_API_KEY / LLM_BASE_URL / LLM_MODEL）
load_dotenv(Path(__file__).with_name(".env"))

from pydantic import BaseModel, Field, ValidationError  # noqa: E402
from agents import (  # noqa: E402
    Agent,
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    Runner,
    set_default_openai_api,
    set_tracing_disabled,
)

# 国内模型走 chat completions 协议，并关闭官方 tracing（需要 OpenAI 平台 Key）
set_default_openai_api("chat_completions")
set_tracing_disabled(True)

# Windows 下 stdout 被重定向（管道 / 写文件）时默认用 GBK，中文会乱码，这里统一成 UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 输出结构：最终必须落成这个 JSON
# --------------------------------------------------------------------------- #
class TranslationResult(BaseModel):
    """最终输出结构，字段顺序即 JSON 的输出顺序。"""

    query_input: str = Field(description="用户的原始输入文本")
    language: str = Field(description="原始输入文本的语种，用中文表示，如：中文 / 英语 / 日语")
    result: str = Field(description="翻译结果：非中文翻译成中文，中文翻译成英文")


# --------------------------------------------------------------------------- #
# 2. Agent 定义
# --------------------------------------------------------------------------- #
INSTRUCTIONS = """你是一个语种识别与翻译助手，负责把用户输入的文本整理成固定 JSON。

处理步骤：
1. 识别用户输入文本的语种（按主要语种判断），语种名称用中文表示：
   中文、英语、日语、韩语、法语、德语、西班牙语、俄语、阿拉伯语……
2. 根据语种决定翻译方向：
   - 语种是中文  -> 翻译成英文（English）
   - 语种不是中文 -> 翻译成中文（简体中文）
   翻译要求：忠实原意、通顺自然，不要增删内容，不要加解释。
3. 只输出下面这个 JSON，不要输出任何解释文字，不要使用 markdown 代码块：

{"query_input": "用户的原始输入文本", "language": "识别出的语种", "result": "翻译结果"}

其中 query_input 必须是用户原封不动输入的原文。
"""


def build_model() -> OpenAIChatCompletionsModel:
    """按 .env 里的配置构造 OpenAI 兼容模型（默认 DeepSeek）。"""
    api_key = os.environ.get("LLM_API_KEY")
    base_url = os.environ.get("LLM_BASE_URL")
    model_name = os.environ.get("LLM_MODEL", "deepseek-chat")
    if not api_key:
        sys.exit("缺少 LLM_API_KEY，请先把 .env.example 复制为 .env 并填入自己的 Key。")

    external_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return OpenAIChatCompletionsModel(model=model_name, openai_client=external_client)


def build_agent() -> Agent:
    return Agent(
        name="Language Translator",
        instructions=INSTRUCTIONS,
        model=build_model(),
    )


# --------------------------------------------------------------------------- #
# 3. 解析 + 校验：模型输出 -> Pydantic 模型
# --------------------------------------------------------------------------- #
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_result(raw: str) -> TranslationResult:
    """从模型输出里抠出 JSON 并校验成 TranslationResult。

    兼容三种常见的“脏”输出：markdown 代码块、JSON 前后带解释文字、首尾空白。
    """
    text = (raw or "").strip()

    block = _JSON_BLOCK.search(text)
    if block:
        text = block.group(1).strip()

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]

    data = json.loads(text)  # 不是合法 JSON 会抛 JSONDecodeError
    return TranslationResult.model_validate(data)  # 缺字段/类型不对会抛 ValidationError


async def run_agent(agent: Agent, text: str, max_attempts: int = 3) -> TranslationResult:
    """调用 agent 并保证拿到结构化结果；解析失败时把模型上一轮输出回喂让它修正。"""
    messages: object = text
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        result = await Runner.run(starting_agent=agent, input=messages)
        raw = str(result.final_output)

        try:
            parsed = parse_result(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            print(f"  [warn] 第 {attempt} 次输出不是合法 JSON，让模型修正：{exc}", file=sys.stderr)
            messages = [
                {"role": "user", "content": text},
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "上面的输出不是合法 JSON。请只重新输出一个合法的 JSON 对象，"
                        "字段为 query_input、language、result，不要任何其它文字。"
                    ),
                },
            ]
            continue

        # query_input 以用户真实输入为准，避免模型复述时改动原文
        parsed.query_input = text
        return parsed

    raise RuntimeError(f"连续 {max_attempts} 次都没能拿到合法 JSON，最后一次错误：{last_error}")


# --------------------------------------------------------------------------- #
# 4. 入口：命令行
# --------------------------------------------------------------------------- #
DEMO_CASES = [
    "人工智能正在改变我们的生活方式。",                       # 中文 -> 英文
    "Hello, how are you today?",                              # 英语 -> 中文
    "こんにちは、今日はいい天気ですね。",                       # 日语 -> 中文
    "Bonjour, je m'appelle Marie, enchanté.",                 # 法语 -> 中文
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="语种识别 + 双向翻译 Agent")
    parser.add_argument("text", nargs="?", help="待处理的文本；不传则跑内置演示用例")
    parser.add_argument("-q", "--query", help="同 text，显式指定待处理文本")
    args = parser.parse_args()

    text = args.query or args.text
    cases = [text] if text else DEMO_CASES

    agent = build_agent()

    for case in cases:
        print(f"\n{'=' * 60}")
        print(f"输入: {case}")
        result = await run_agent(agent, case)
        # 最终输出：题目要求的 JSON 格式
        print(json.dumps(result.model_dump(), ensure_ascii=False, indent=4))


if __name__ == "__main__":
    asyncio.run(main())
