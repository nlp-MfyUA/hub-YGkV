# -*- coding: utf-8 -*-
"""双 Agent 定义(OpenAI Agents SDK)。

- create_language_agent: 语种检测 Agent(LanguageDetector)
- create_translation_agent: 翻译 Agent(Translator)

两个 Agent 均通过 MCP 协议(mcp_servers)调用 mcp/translation_server.py
暴露的翻译类工具, 即需求二所说的「通过 agent 调用 MCP 工具」。
"""
from agents import Agent

from .language_agent import create_language_agent
from .translation_agent import create_translation_agent

__all__ = ["create_language_agent", "create_translation_agent"]
