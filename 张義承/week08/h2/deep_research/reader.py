# -*- coding: utf-8 -*-
"""阅读抽取模块：把一次检索的结果总结成一段正文（角色 agent：summary）。"""
from __future__ import annotations

import logging

from . import llm

logger = logging.getLogger(__name__)

_SYSTEM = """你是资料阅读员。下面是一次关于某个关键词的网页搜索结果。请通读后，用中文写出一段
200~400 字的正文段落，归纳该关键词之下的关键事实与要点。只依据给出的结果撰写，不要编造结果里
没有的内容；若结果列表为空，请如实说明没有检索到资料。直接输出正文文字即可，不要用 JSON、不要加标题。"""


def _format_results(results: list[dict]) -> str:
    if not results:
        return "（本次检索无结果）"
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r.get('title') or ''}\n"
            f"   来源: {r.get('url') or ''}\n"
            f"   摘要: {(r.get('snippet') or '')[:500]}"
        )
    return "\n\n".join(lines)


def summarize(topic: str, keyword: str, results: list[dict]) -> str:
    """把 keyword 的一次检索结果总结成一段正文；失败/空时返回空串由上层兜底。"""
    user = f"研究主题：{topic}\n检索关键词：{keyword}\n\n搜索结果：\n{_format_results(results)}"
    try:
        text = llm.chat_text(_SYSTEM, user).strip()
    except Exception:  # noqa: BLE001
        logger.exception("总结关键词「%s」失败", keyword)
        return ""
    logger.info("关键词「%s」总结完成，正文 %d 字", keyword, len(text))
    return text
