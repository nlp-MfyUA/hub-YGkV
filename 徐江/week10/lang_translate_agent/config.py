# -*- coding: utf-8 -*-
"""
全局配置: 从环境变量 / 项目根目录 .env 读取大模型接入配置。

.env 示例见 .env.example, 至少需要配置 OPENAI_API_KEY。
OpenAI Agents SDK 与 MCP 翻译工具均通过以下环境变量接入
OpenAI 兼容接口(可指向 OpenAI 官方或任何兼容代理, 如 OneAPI/vLLM 等)。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings:
    """应用配置(全部支持用环境变量覆盖)。"""

    def __init__(self) -> None:
        self.openai_api_key: str = os.environ.get("OPENAI_API_KEY", "").strip()
        self.openai_base_url: str = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip()
        # 两个 Agent 使用的对话模型
        self.agent_model: str = os.environ.get("AGENT_MODEL", "gpt-4o-mini").strip()
        # MCP translate_text 工具内部使用的翻译模型
        self.translate_model: str = os.environ.get("TRANSLATE_MODEL", "gpt-4o-mini").strip()

    @property
    def llm_ready(self) -> bool:
        """是否已具备调用大模型的必要条件。"""
        return bool(self.openai_api_key)


settings = Settings()
