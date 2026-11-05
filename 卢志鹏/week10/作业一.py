# 作业一：语种检测 + 自动翻译 Agent（结构化 JSON 输出）
# 需求：输入文本 -> 判断语种 -> 非中文翻译为中文，中文翻译为英文
# 最终输出 JSON：{"query_input": "", "language": "", "result": ""}

from pathlib import Path

from dotenv import load_dotenv

# .env 位于项目根目录（本文件的上一级目录），用 __file__ 定位，保证从任意工作目录运行都能找到
# override=True：强制用 .env 的值覆盖已存在的同名环境变量
# （否则系统里若已设置过 OPENAI_API_KEY，会优先使用系统环境变量，.env 反而不生效）
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

import json
import os
import re

import msvcrt  # Windows 标准库：用于逐字符读取键盘输入、捕捉 ESC 键

from pydantic import BaseModel, ValidationError

# load_dotenv 会把 .env 中的键值对写入环境变量 os.environ，这里读取出来
BASE_URL = os.getenv("OPENAI_BASE_URL")
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("MODEL")

# 简单校验：确认配置读取成功（key 只显示前8位，避免泄露）
assert BASE_URL and API_KEY, ".env 读取失败，请检查文件路径和内容"
print(f"已加载配置: BASE_URL={BASE_URL}, API_KEY={API_KEY[:8]}****")

# agents sdk 会自动读取环境变量中的 OPENAI_API_KEY / OPENAI_BASE_URL
# 所以 load_dotenv 之后无需再手动 set，直接使用即可
from agents import Agent, AgentOutputSchemaBase, Runner
from agents import set_default_openai_api, set_tracing_disabled
from agents.exceptions import ModelBehaviorError

set_default_openai_api("chat_completions")  # 国内模型兼容接口使用 chat completions
set_tracing_disabled(True)  # 关闭 OpenAI 云端链路追踪（国内接口不支持）


# 最终输出的 JSON 结构定义（Pydantic 模型 -> JSON Schema 约束大模型输出）
class TranslationOutput(BaseModel):
    query_input: str  # 用户输入的原始文本（原样返回）
    language: str     # 检测到的语种（如：中文、英文、日文）
    result: str       # 翻译结果（非中文->中文，中文->英文）


def clean_model_output(text: str) -> str:
    """清理大模型输出中的杂质：markdown 代码块围栏、围栏外的多余文字。
    国内模型经常返回 ```json {...} ``` 格式，导致 JSON 解析失败。"""
    text = text.strip()
    # 去掉开头的 ```json 或 ``` 围栏、结尾的 ``` 围栏
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    # 兜底：截取第一个 { 到最后一个 } 之间的内容（应对 JSON 前后带解释文字的情况）
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text.strip()


class TranslationOutputSchema(AgentOutputSchemaBase):
    """自定义输出解析器（参考 openai-agent-examples/basic/non_strict_output_type.py 的 CustomOutputSchema）：
    1. 宽松 schema：不用 strict 模式（国内模型对严格 JSON Schema 支持不好）；
    2. 容错解析：validate_json 里先清理 markdown 围栏等杂质，再用 pydantic 校验。"""

    def __init__(self, model_cls: type[BaseModel]):
        self._model_cls = model_cls

    def is_plain_text(self) -> bool:
        return False

    def name(self) -> str:
        return self._model_cls.__name__

    def json_schema(self) -> dict:
        return self._model_cls.model_json_schema()  # pydantic 自带的非严格 schema

    def is_strict_json_schema(self) -> bool:
        return False

    def validate_json(self, json_str: str):
        cleaned = clean_model_output(json_str)
        try:
            return self._model_cls.model_validate_json(cleaned)  # 返回 TranslationOutput 对象
        except ValidationError as e:
            raise ModelBehaviorError(f"Invalid JSON when parsing model output: {cleaned}") from e


# agent 的定义
agent = Agent(
    model=MODEL,  # 模型代号（从 .env 读取）
    name="Translator",  # 给 agent 取的名字（推荐英文，写的有意义）
    instructions=(
        "你是一个高级多国语言翻译专家，请对用户输入的文本完成：\n"
        "1. 识别输入文本的语种，填写到 language 字段；\n"
        "2. 若输入是非中文，翻译为中文；若输入是中文，翻译为英文；译文填写到 result 字段；\n"
        "3. query_input 字段原样保留用户输入；\n"
        "4. 直接输出 JSON 本体，禁止使用 markdown 代码块（```）包裹，禁止输出任何解释文字。"
    ),
    output_type=TranslationOutput,  # 结构化输出：约束模型按该 JSON 结构返回
)

# 宽松模式（参考 openai-agent-examples/basic/non_strict_output_type.py）
# 默认 strict JSON Schema 对国内模型兼容性不好；且国内模型常把 JSON 包在 ```json ``` 里导致解析失败
# 这里换成自定义 Schema：宽松 schema + 自动清理杂质后解析
agent.output_type = TranslationOutputSchema(TranslationOutput)

def input_with_esc(prompt: str) -> str | None:
    """逐字符读取一行输入（Windows）：
    - 按 Enter 返回已输入的内容
    - 按 ESC 立即返回 None（用于退出循环）
    - 支持退格键删除；忽略方向键等特殊按键
    """
    print(prompt, end="", flush=True)
    chars: list[str] = []
    while True:
        ch = msvcrt.getwch()  # 阻塞等待一个按键
        if ch == "\x1b":  # ESC 键
            print()
            return None
        elif ch in ("\r", "\n"):  # Enter 键，输入结束
            print()
            return "".join(chars)
        elif ch in ("\x00", "\xe0"):  # 特殊按键（方向键/F键等）会发送两字节，读掉第二个字节
            msvcrt.getwch()
        elif ch == "\x08":  # 退格键：删除最后一个字符
            if chars:
                chars.pop()
                print("\b \b", end="", flush=True)  # 光标左移一格并清屏该位置
        elif ch == "\x03":  # Ctrl+C 也允许退出
            raise KeyboardInterrupt
        else:
            chars.append(ch)
            print(ch, end="", flush=True)  # 回显用户输入


# while 循环：持续接收用户输入并翻译，按 ESC 键退出
while True:
    text = input_with_esc("请输入要翻译的文本（按 ESC 退出）: ")

    if text is None:  # ESC 被按下
        print("已按 ESC，退出程序。")
        break

    if not text.strip():  # 空输入，跳过本次循环
        continue

    result = Runner.run_sync(agent, text)

    # result.final_output 已经是 TranslationOutput 对象（sdk 自动完成 JSON 解析和校验）
    # model_dump() 转字典后序列化为 JSON 字符串；ensure_ascii=False 保证中文正常显示
    print(json.dumps(result.final_output.model_dump(), ensure_ascii=False, indent=2))

