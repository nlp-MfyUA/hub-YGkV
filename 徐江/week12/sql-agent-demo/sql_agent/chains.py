"""LCEL 链定义：``prompt | chat_model | parser``。

week11 版每个 stage 各自「拼 messages → 调 client.chat → 解析文本」；
week12 版把这三步组合成 LangChain 表达式语言（LCEL）链，四条链对应四个
需要 LLM 的阶段：

    select_tables_chain = SELECT_TABLES_PROMPT | model | parse_tables_output
    generate_sql_chain  = GENERATE_SQL_PROMPT  | model | parse_sql_output
    rewrite_sql_chain   = REWRITE_SQL_PROMPT   | model | parse_sql_output
    summarize_chain     = SUMMARIZE_PROMPT     | model.bind(temperature=0.3)
                                          | parse_text_output

末端的 parser 把 ``AIMessage`` 转成 :class:`LLMOutput`——除解析后的内容外，
还携带模型名与 token 用量（从 ``AIMessage.usage_metadata`` 映射），供各
stage 留痕统计，语义与 week11 的 LLMResponse 一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda

from .models import LLMUsage
from .prompts import (GENERATE_SQL_PROMPT, REWRITE_SQL_PROMPT,
                      SELECT_TABLES_PROMPT, SUMMARIZE_PROMPT, extract_json,
                      extract_sql)

# 汇总阶段的温度（与 week11 的 ResultSummaryStage 一致：结论生成允许一点发散）
SUMMARIZE_TEMPERATURE = 0.3


@dataclass
class LLMOutput:
    """一条 LCEL 链的最终输出。

    - content：模型原始文本（AIMessage.content）
    - parsed：解析后的业务内容（SQL 字符串 / 选表 dict / 总结文本）
    - model：模型名（来自 response_metadata.model_name）
    - usage：本次调用的 token 用量（usage_metadata 映射；调用成功即计 1 次）
    """

    content: str
    parsed: Any = None
    model: str = ""
    usage: LLMUsage = field(default_factory=LLMUsage)


# ------------------------------------------------------------------ parser
def _model_name(message: AIMessage) -> str:
    return str((message.response_metadata or {}).get("model_name", ""))


def _usage_of(message: AIMessage) -> LLMUsage:
    """AIMessage.usage_metadata -> LLMUsage（调用成功即计 1 次，token 缺省为 0）。"""
    meta = message.usage_metadata or {}
    usage = LLMUsage(
        prompt_tokens=int(meta.get("input_tokens", 0) or 0),
        completion_tokens=int(meta.get("output_tokens", 0) or 0),
        total_tokens=int(meta.get("total_tokens", 0) or 0),
        calls=1,
    )
    return usage


def parse_sql_output(message: AIMessage) -> LLMOutput:
    """SQL 生成 / 改写链的末端：提取 ```sql 代码块。"""
    return LLMOutput(
        content=message.content,
        parsed=extract_sql(message.content),
        model=_model_name(message),
        usage=_usage_of(message),
    )


def parse_tables_output(message: AIMessage) -> LLMOutput:
    """Table 选择链的末端：提取 JSON {"tables": [...], "reason": ...}。"""
    return LLMOutput(
        content=message.content,
        parsed=extract_json(message.content) or {},
        model=_model_name(message),
        usage=_usage_of(message),
    )


def parse_text_output(message: AIMessage) -> LLMOutput:
    """结果汇总链的末端：直接取文本。"""
    return LLMOutput(
        content=message.content,
        parsed=(message.content or "").strip(),
        model=_model_name(message),
        usage=_usage_of(message),
    )


# ------------------------------------------------------------------ 链工厂
def build_chains(model: BaseChatModel) -> dict[str, Runnable]:
    """基于同一个 ChatModel 构造四条 LCEL 链。

    链对模型无感知：deepseek 模式是 ChatOpenAI，mock 模式是 MockChatModel，
    两者都是 BaseChatModel，链的定义完全一致。
    """
    return {
        "select_tables": SELECT_TABLES_PROMPT | model | RunnableLambda(parse_tables_output),
        "generate_sql": GENERATE_SQL_PROMPT | model | RunnableLambda(parse_sql_output),
        "rewrite_sql": REWRITE_SQL_PROMPT | model | RunnableLambda(parse_sql_output),
        # 汇总阶段单独绑温度（bind 只影响这一条链，不动模型默认参数）
        "summarize": (SUMMARIZE_PROMPT
                      | model.bind(temperature=SUMMARIZE_TEMPERATURE)
                      | RunnableLambda(parse_text_output)),
    }


__all__ = ["LLMOutput", "build_chains", "parse_sql_output",
           "parse_tables_output", "parse_text_output", "SUMMARIZE_TEMPERATURE"]
