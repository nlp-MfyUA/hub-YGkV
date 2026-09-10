# -*- coding: utf-8 -*-
"""综合生成模块：确定性算置信度 + 让 LLM 生成报告元信息（角色 agent：report）。

正文分节由草稿段落直接映射（heading=关键词），不交给 LLM 重新组织，
保证正文与来源一一对应、可追溯。
"""
from __future__ import annotations

import logging
import re

from . import config, llm
from .models import Confidence, ReportSection, Source

logger = logging.getLogger(__name__)

_SYSTEM = """你是报告撰写员。根据给出的研究主题与各段正文草稿，生成报告元信息。
只输出一个 JSON 对象，用 ```json 包裹：
{"title": "报告标题", "summary": "100~200字摘要", "key_conclusions": ["关键结论1", ...],
 "open_questions": ["遗留问题1", ...]}"""


def compute_confidence(sources: list[Source], section_count: int) -> Confidence:
    """确定性置信度：按来源数量分级，信息截止取来源最新日期（缺省今天）。"""
    n = len(sources)
    if n >= 12:
        overall = "high"
    elif n >= 5:
        overall = "medium"
    else:
        overall = "low"
    dates = [s.date[:10] for s in sources if s.date and re.match(r"\d{4}-\d{2}-\d{2}", s.date)]
    info_cutoff = max(dates) if dates else config.today_str()
    notes = [
        f"正文共 {section_count} 节，引用 {n} 个来源。",
        f"信息截止时间取检索来源的最新资料日期（{info_cutoff}）。",
        "无来源支撑的分节已标注为模型推断。",
    ]
    return Confidence(overall=overall, info_cutoff=info_cutoff, notes=notes)


def _sections_from_draft(draft: list) -> list[ReportSection]:
    """草稿段落 → 报告分节（heading=关键词）。"""
    sections = []
    for block in draft:
        if not (block.text or "").strip():
            continue
        sections.append(
            ReportSection(
                heading=block.keyword,
                body=block.text,
                inferred=not block.had_results,
            )
        )
    return sections


def build_report_meta(topic: str, sections: list[ReportSection]) -> dict:
    """让 LLM 产出报告元信息（标题/摘要/关键结论/遗留问题）；失败时用主题兜底。"""
    body = "\n\n".join(f"【{s.heading}】\n{s.body}" for s in sections)
    user = f"研究主题：{topic}\n\n正文草稿：\n{body[:8000] if body else '（草稿为空）'}"
    try:
        meta = llm.chat_json(_SYSTEM, user)
        meta.setdefault("title", topic)
        meta.setdefault("summary", "")
        meta.setdefault("key_conclusions", [])
        meta.setdefault("open_questions", [])
        return meta
    except Exception:  # noqa: BLE001
        logger.exception("报告元信息生成失败，使用兜底标题")
        return {"title": topic, "summary": "", "key_conclusions": [], "open_questions": []}


def synthesize(topic: str, draft: list, sources: list[Source]) -> tuple[dict, Confidence, list[ReportSection]]:
    """综合：返回 (report_meta, confidence, sections)。"""
    sections = _sections_from_draft(draft)
    confidence = compute_confidence(sources, len(sections))
    meta = build_report_meta(topic, sections)
    return meta, confidence, sections
