# -*- coding: utf-8 -*-
"""集中配置：从项目根 .env 读取密钥与运行参数。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# deep_research/ 的上一级即项目根（week08/h2）
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"

load_dotenv(BASE_DIR / ".env")

# --- LLM（DeepSeek，OpenAI 兼容 chat_completions）---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com")
MODEL_NAME = os.environ.get("MODEL_NAME", "deepseek-v4-flash")

# --- Bocha 网页搜索 ---
BOCHA_API_KEY = os.environ.get("BOCHA_API_KEY", "")
BOCHA_URL = os.environ.get("BOCHA_URL", "https://api.bocha.cn/v1/web-search")
BOCHA_SEARCH_COUNT = int(os.environ.get("BOCHA_SEARCH_COUNT", "10"))

# --- 研究循环 / LLM 重试 ---
MAX_ROUNDS = int(os.environ.get("RESEARCH_MAX_ROUNDS", "3"))
LLM_RETRIES = int(os.environ.get("LLM_RETRIES", "3"))


def today_str() -> str:
    from datetime import date

    return date.today().isoformat()
