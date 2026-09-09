# -*- coding: utf-8 -*-
"""规划模块：把研究主题拆成可检索的关键词（角色 agent：keyword/规划）。"""
from __future__ import annotations

import logging

from . import config, llm

logger = logging.getLogger(__name__)

_SYSTEM = """你是研究规划员。请把给定的研究主题拆解为 3~5 个彼此独立、可直接用于网页搜索的关键词，
尽量覆盖主题的不同侧面（定义/现状/对比/趋势/案例等）。只输出一个 JSON 对象，用 ```json 包裹：
{"keywords": ["关键词1", "关键词2"]}"""


def plan(topic: str) -> list[str]:
    """返回 3~5 个初始检索关键词；失败时退回 [topic] 保底。"""
    user = f"今天日期：{config.today_str()}。研究主题：{topic}"
    try:
        out = llm.chat_json(_SYSTEM, user)
        keywords = [str(k).strip() for k in (out.get("keywords") or []) if str(k).strip()]
        logger.info("规划完成，关键词 %d 个: %s", len(keywords), keywords)
        return keywords or [topic]
    except Exception:  # noqa: BLE001 - LLM 失败也要能跑下去
        logger.exception("关键词规划失败，退回主题本身")
        return [topic]
