# -*- coding: utf-8 -*-
"""llm —— 统一的 LLM 调用入口。

所有需要调用大模型的地方（生成关键词 / 总结 / 判断补检 / 写报告）
都通过本文件的 `chat` / `chat_json` 函数完成，不各自创建客户端。

使用 DeepSeek 的 OpenAI 兼容接口，密钥从项目根 .env 读取。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
import os

# 加载项目根 .env（幂等，重复调用无副作用）
load_dotenv(Path(__file__).resolve().parent / ".env")

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/")
MODEL = os.environ.get("MODEL_NAME", "deepseek-v4-flash")
RETRIES = int(os.environ.get("LLM_RETRIES", "3"))

client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

logger = logging.getLogger(__name__)


async def chat(system: str, user: str) -> str:
    """一次对话调用，返回模型输出文本。空输出自动重试（最多 RETRIES 次）。"""
    for attempt in range(1, RETRIES + 1):
        resp = await client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        if text:
            return text
        logger.warning("LLM 第 %d/%d 次返回空输出，重试", attempt, RETRIES)
        await asyncio.sleep(1)
    return ""


async def chat_json(system: str, user: str) -> dict:
    """一次对话调用并要求 JSON 输出，返回解析后的 dict。

    先尝试从 ```json``` 代码块提取，失败再回退解析原始文本。
    """
    text = await chat(system, user)
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    candidate = m.group(1) if m else text
    return json.loads(candidate)
