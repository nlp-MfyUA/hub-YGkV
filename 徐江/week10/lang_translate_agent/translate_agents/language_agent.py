# -*- coding: utf-8 -*-
"""Agent 1: 语种检测专家 LanguageDetector。

职责: 判断用户输入文本是什么语言。
实现: 通过 MCP 调用 detect_language 工具完成检测, 并将结果整理为
      严格的 JSON 输出, 供主程序解析。
"""
from agents import Agent


def create_language_agent(mcp_server, model: str = "gpt-4o-mini") -> Agent:
    """创建语种检测 Agent。

    参数:
        mcp_server: 已连接(或即将进入 async with)的 MCP Server 实例,
                    OpenAI Agents SDK 会自动把其工具暴露给 Agent。
        model: 使用的对话模型。
    """
    return Agent(
        name="LanguageDetector",
        model=model,
        instructions=(
            "你是语种检测专家，职责是判断用户输入文本是什么语言。\n"
            "工作步骤:\n"
            "1. 调用 detect_language 工具检测文本语种;\n"
            "2. 根据工具返回结果输出最终结论。\n"
            "输出要求(严格遵守): 只输出一个 JSON 对象，不要输出任何其他文字，格式为:\n"
            '{"language": "<ISO 639-1 语言代码, 如 zh/en/ja>", '
            '"language_name": "<中文语言名, 如 中文/英语/日语>"}'
        ),
        mcp_servers=[mcp_server],
    )
