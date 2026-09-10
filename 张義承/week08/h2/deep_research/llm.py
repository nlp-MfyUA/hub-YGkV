# -*- coding: utf-8 -*-
"""极简 LLM 封装：对 DeepSeek 的 OpenAI 兼容接口发起单次调用。

测试版从简：requests 直连，不做 agent 框架。chat_text 返回纯文本，
chat_json 要求模型输出 JSON（支持 ```json 代码块包裹）并解析成 dict。
"""
from __future__ import annotations

import json
import logging
import re
import time

import requests

from . import config

logger = logging.getLogger(__name__)


def _post(system: str, user: str) -> str:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("未配置 OPENAI_API_KEY，请复制 .env.example 为 .env 并填入密钥")
    url = config.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    last_err: Exception | None = None
    for attempt in range(1, config.LLM_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            msg = (resp.json().get("choices") or [{}])[0].get("message") or {}
            text = (msg.get("content") or "").strip()
            if text:
                return text
            logger.warning("LLM 第 %d/%d 次返回空输出，退避后重试", attempt, config.LLM_RETRIES)
        except Exception as exc:  # noqa: BLE001 - 失败重试
            last_err = exc
            logger.warning("LLM 第 %d/%d 次调用失败: %s", attempt, config.LLM_RETRIES, exc)
        time.sleep(1.0)
    if last_err is not None:
        raise RuntimeError(f"LLM 调用最终失败: {last_err}") from last_err
    raise RuntimeError("LLM 连续返回空输出")


def _extract_json(text: str) -> dict:
    """解析 LLM 输出的 JSON：先试 ```json 代码块内容，再退回原始输出。"""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    for candidate in ([m.group(1)] if m else [None, text]):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"无法把 LLM 输出解析为 JSON，输出片段: {text[:200]!r}")


def chat_text(system: str, user: str) -> str:
    """发起一次纯文本输出调用。"""
    return _post(system, user)


def chat_json(system: str, user: str) -> dict:
    """发起一次调用并把输出解析为 dict（要求模型输出唯一 JSON）。"""
    return _extract_json(_post(system, user))
