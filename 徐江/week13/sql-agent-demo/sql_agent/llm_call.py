"""LangGraph 节点内的 LLM 直接调用（week13 起取代 week12 的 LCEL 链层）。

week12 用 LCEL 把 ``prompt | model | parser`` 预先组装成四条链（chains.py），
stage 持链调用；week13 起编排完全交给 LangGraph，链层随之取消——节点需要
调模型时直接三步走：

    格式化 ChatPromptTemplate -> model.invoke -> 解析输出

调用点与业务节点放在一起，符合「图即框架」的 LangGraph 习惯：
LangChain 只保留模型抽象（BaseChatModel / ChatOpenAI / MockChatModel）与
提示词模板（ChatPromptTemplate），编排、状态、重试全部由 LangGraph 负责。

公共入口 :func:`call_llm`：

    output = call_llm(model, GENERATE_SQL_PROMPT,
                      {"schema_prompt": ..., "question": ...},
                      parser=PARSER_SQL)
    # output.parsed  -> 解析后的业务内容（SQL 字符串 / 选表 dict / 总结文本）
    # output.model   -> 模型名
    # output.usage   -> 本次调用的 token 用量（AIMessage.usage_metadata 映射）

token 统计口径与 week12 完全一致（调用成功即计 1 次，token 缺省为 0），
因此工作流留痕、评测指标与 week12 逐字段对齐。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from .models import LLMUsage
from .prompts import extract_json, extract_sql

# ------------------------------------------------------------------ 解析方式
PARSER_SQL = "sql"      # 提取 ```sql 代码块
PARSER_JSON = "json"    # 提取第一个 JSON 对象
PARSER_TEXT = "text"    # 直接取文本（去首尾空白）

_PARSERS: dict[str, Callable[[str], Any]] = {
    PARSER_SQL: extract_sql,
    PARSER_JSON: extract_json,
    PARSER_TEXT: lambda text: (text or "").strip(),
}


@dataclass
class LLMOutput:
    """一次节点内 LLM 调用的输出。

    - content：模型原始文本（AIMessage.content）
    - parsed：解析后的业务内容（SQL 字符串 / 选表 dict / 总结文本）
    - model：模型名（来自 response_metadata.model_name）
    - usage：本次调用的 token 用量（usage_metadata 映射；调用成功即计 1 次）
    """

    content: str
    parsed: Any = None
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)


# ------------------------------------------------------------------ 内部工具
def _model_name(message: AIMessage) -> str:
    return str((message.response_metadata or {}).get("model_name", ""))


def _usage_of(message: AIMessage) -> LLMUsage:
    """AIMessage.usage_metadata -> LLMUsage（调用成功即计 1 次，token 缺省为 0）。"""
    meta = message.usage_metadata or {}
    return LLMUsage(
        prompt_tokens=int(meta.get("input_tokens", 0) or 0),
        completion_tokens=int(meta.get("output_tokens", 0) or 0),
        total_tokens=int(meta.get("total_tokens", 0) or 0),
        calls=1,
    )


# ------------------------------------------------------------------ 公共入口
def call_llm(
    model: BaseChatModel,
    prompt: ChatPromptTemplate,
    variables: dict,
    *,
    parser: str = PARSER_TEXT,
    temperature: float | None = None,
) -> LLMOutput:
    """在 LangGraph 节点内直接调用一次 LLM。

    参数：
        model:       ChatModel（ChatOpenAI / MockChatModel，均为 BaseChatModel）
        prompt:      ChatPromptTemplate 模板
        variables:   模板变量
        parser:      输出解析方式（PARSER_SQL / PARSER_JSON / PARSER_TEXT）
        temperature: 需要临时覆盖温度时传入（内部用 bind，只影响本次调用）

    异常不在此处捕获——由调用方（stage / 节点）决定降级或短路策略，
    与 week12 中 stage 对链调用的 try/except 语义一致。
    """
    messages = prompt.format_messages(**variables)
    target = model.bind(temperature=temperature) if temperature is not None else model
    message: AIMessage = target.invoke(messages)
    content = message.content if isinstance(message.content, str) else str(message.content)
    parse = _PARSERS.get(parser, _PARSERS[PARSER_TEXT])
    return LLMOutput(
        content=content,
        parsed=parse(content),
        model=_model_name(message),
        usage=_usage_of(message),
    )


__all__ = ["LLMOutput", "call_llm", "PARSER_SQL", "PARSER_JSON", "PARSER_TEXT"]
