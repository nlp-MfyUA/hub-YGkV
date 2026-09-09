# -*- coding: utf-8 -*-
"""编排模块：确定性控制流，串起各角色 agent 的完整研究循环。

engine 不做任何 LLM 判断逻辑，只负责：规划 → 多轮（检索→总结累积→判断补检）
→ 直到 sufficient 或 max_rounds → 综合出报告。搜索为普通函数直接调用。
"""
from __future__ import annotations

import logging

from . import config, gap_detector, planner, reader, searcher, synthesizer
from .models import DraftBlock, ResearchProcess, ResearchResult, Source

logger = logging.getLogger(__name__)


def _collect_sources(results: list[dict], sources: list, reviewed: set[str], process: ResearchProcess) -> None:
    """把一次搜索结果收进来源列表（按 URL 去重），并记录已读 URL 到过程。"""
    for r in results:
        url = (r.get("url") or "").strip()
        if url and url not in reviewed:
            reviewed.add(url)
            process.reviewed_urls.append(url)
            sources.append(
                Source(
                    url=url,
                    title=r.get("title") or "",
                    site_name=r.get("site_name") or "",
                    snippet=r.get("snippet") or "",
                    date=r.get("date") or "",
                    accessed_at=config.today_str(),
                )
            )


def _join_draft(draft: list[DraftBlock]) -> str:
    return "\n\n".join(
        f"【关键词：{b.keyword}】\n{b.text}" for b in draft if (b.text or "").strip()
    )


def run(topic: str, max_rounds: int | None = None) -> ResearchResult:
    """执行一次完整研究，返回 ResearchResult。"""
    max_rounds = max_rounds or config.MAX_ROUNDS

    process = ResearchProcess()
    draft: list[DraftBlock] = []
    sources: list[Source] = []
    reviewed: set[str] = set()

    # 1. 规划
    initial = planner.plan(topic)
    process.plan = list(initial)
    process.steps.append({"type": "plan", "round": 0, "detail": {"keywords": initial}})
    logger.info("规划完成，初始关键词 %d 个: %s", len(initial), initial)

    # 2. 检索 → 总结累积 → 判断补检 循环
    searched: list[str] = []
    todo_keywords = list(initial)
    round_no = 0

    while round_no < max_rounds and todo_keywords:
        round_no += 1
        process.iterations = round_no

        for kw in list(todo_keywords):
            if kw in searched:
                continue
            searched.append(kw)
            process.search_queries.append(kw)

            try:
                results = searcher.web_search(kw)
            except Exception:  # noqa: BLE001 - 单次检索失败不中断流程
                logger.exception("检索「%s」失败", kw)
                results = []

            _collect_sources(results, sources, reviewed, process)
            process.steps.append(
                {"type": "search", "round": round_no, "detail": {"keyword": kw, "results": len(results)}}
            )

            text = reader.summarize(topic, kw, results).strip()
            if text:
                draft.append(DraftBlock(round_no=round_no, keyword=kw, text=text, had_results=bool(results)))
            process.steps.append(
                {"type": "summarize", "round": round_no, "detail": {"keyword": kw, "chars": len(text)}}
            )
            logger.info(
                "第 %d 轮「%s」→ 结果 %d 条 / 累积正文 %d 段 / 来源 %d 个",
                round_no, kw, len(results), len(draft), len(sources),
            )

        # 判断补检（基于当前累积草稿）
        decision = gap_detector.judge(topic, _join_draft(draft), searched)
        process.steps.append(
            {
                "type": "judge",
                "round": round_no,
                "detail": {
                    "sufficient": decision.get("sufficient"),
                    "reason": decision.get("reason", ""),
                    "new_keywords": decision.get("new_keywords", []),
                },
            }
        )
        logger.info("第 %d 轮判断: sufficient=%s", round_no, decision.get("sufficient"))

        if decision.get("sufficient"):
            break
        new_keywords = [k for k in (decision.get("new_keywords") or []) if k and k not in searched]
        todo_keywords = new_keywords

    # 3. 综合：置信度 + 报告元信息 + 分节映射
    report_meta, confidence, sections = synthesizer.synthesize(topic, draft, sources)
    logger.info(
        "研究完成: 共 %d 轮 / %d 个关键词 / 正文 %d 段 / 来源 %d 个 / 置信度 %s",
        process.iterations, len(process.search_queries), len(sections),
        len(sources), confidence.overall,
    )

    return ResearchResult(
        topic=topic,
        title=report_meta.get("title") or topic,
        summary=report_meta.get("summary") or "",
        sections=sections,
        key_conclusions=list(report_meta.get("key_conclusions") or []),
        open_questions=list(report_meta.get("open_questions") or []),
        sources=sources,
        process=process,
        confidence=confidence,
    )
