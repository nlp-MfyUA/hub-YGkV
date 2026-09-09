# -*- coding: utf-8 -*-
"""补检判断模块：基于累积草稿判断信息是否足够，不足则给新关键词（角色 agent：judge）。"""
from __future__ import annotations

import logging

from . import llm

logger = logging.getLogger(__name__)

_SYSTEM = """你是研究评审员。判断目前已积累的研究草稿对研究主题是否已足够支撑一份报告。
只输出一个 JSON 对象，用 ```json 包裹：
{"sufficient": true/false, "reason": "简要理由", "new_keywords": ["补充检索用关键词"]}
若 sufficient 为 false，new_keywords 给出 2~3 个尚未检索、能补足缺口的新关键词；
若已足够，new_keywords 给空数组。"""


def judge(topic: str, draft_text: str, searched: list[str]) -> dict:
    """返回 {sufficient, reason, new_keywords}；失败时保守地按“已足够”处理以免死循环。"""
    user = (
        f"研究主题：{topic}\n"
        f"已检索过的关键词：{', '.join(searched) or '无'}\n\n"
        f"当前研究草稿：\n{draft_text[:6000] if draft_text else '（草稿为空）'}"
    )
    try:
        decision = llm.chat_json(_SYSTEM, user)
    except Exception:  # noqa: BLE001 - 判断失败不应阻断，默认视为足够
        logger.exception("补检判断失败，默认视为已足够")
        return {"sufficient": True, "reason": "判断调用失败，保守收尾", "new_keywords": []}
    logger.info(
        "判断结果: sufficient=%s new_keywords=%s",
        decision.get("sufficient"),
        decision.get("new_keywords"),
    )
    return decision
