# -*- coding: utf-8 -*-
"""Agent 2: 翻译专家 Translator。

职责: 按既定规则翻译文本 —— 源语言为中文时翻译成英文;
      源语言为其他语言时翻译成中文。
实现: 通过 MCP 调用 translate_text 工具完成翻译(工具内部再调用
      OpenAI 兼容大模型接口), 最终只输出译文本身。
"""
from agents import Agent


def create_translation_agent(mcp_server, model: str = "gpt-4o-mini") -> Agent:
    """创建翻译 Agent。

    参数:
        mcp_server: 已连接(或即将进入 async with)的 MCP Server 实例。
        model: 使用的对话模型。
    """
    return Agent(
        name="Translator",
        model=model,
        instructions=(
            "你是翻译专家。翻译规则: 源语言为中文时翻译成英文; "
            "源语言为其他语言时翻译成中文。\n"
            "工作步骤:\n"
            "1. 从输入中解析出待翻译文本、源语言与目标语言;\n"
            "2. 调用 translate_text 工具完成翻译(text / source_language / "
            "target_language 必须按输入原样传入);\n"
            "3. 将工具返回的 translated_text 作为最终结果。\n"
            "输出要求(严格遵守): 最终只输出译文本身，不要输出解释、引号、JSON 或任何额外格式。"
        ),
        mcp_servers=[mcp_server],
    )
