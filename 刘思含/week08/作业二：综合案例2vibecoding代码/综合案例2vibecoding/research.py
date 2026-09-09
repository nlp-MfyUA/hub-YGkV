# -*- coding: utf-8 -*-
"""research —— 最简研究循环（闭环核心）。

流程：规划关键词 → 逐关键词搜索 + LLM 总结成正文段 → LLM 判断是否补检
→ 不足则用新关键词进入下一轮（上限 MAX_ROUNDS）→ LLM 综合生成 Markdown 报告。

所有 LLM 调用统一走 llm.py；检索统一走 search.py；本文件只做控制流编排。
在项目根目录下运行（python main.py / uvicorn api:app）。
"""
from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import llm
import search

logger = logging.getLogger(__name__)

MAX_ROUNDS = int(os.environ.get("RESEARCH_MAX_ROUNDS", "2"))

TODAY = date.today().isoformat()

# ---- 各环节提示词（直接写在代码里，保持最简）----

PLAN_SYSTEM = (
    "你是研究规划员。根据研究主题生成 3 个互补的中文搜索关键词，"
    "覆盖主题的不同侧面。只输出 JSON：{\"keywords\": [\"关键词1\", \"关键词2\", \"关键词3\"]}"
)

SUMMARY_SYSTEM = (
    "你是资料整理员。基于给出的搜索结果（标题+摘要），围绕研究主题写一段 150~300 字的正文，"
    "客观陈述事实并在句末用 [来源n] 标注引用。直接输出正文文字，不要 JSON、不要标题。"
)

JUDGE_SYSTEM = (
    "你是研究质量评审员。基于当前已累积的研究正文，判断信息是否足够支撑一份入门级研究报告。"
    '只输出 JSON：{"sufficient": true/false, "reason": "理由", '
    '"new_keywords": ["补充关键词", ...]}（sufficient 为 true 时 new_keywords 给空数组）'
)

REPORT_SYSTEM = (
    "你是研究报告撰写人。基于多段研究正文和来源列表，撰写一份结构化 Markdown 报告，包含："
    "标题（# 开头）、## 摘要、## 正文（分节）、## 关键结论（列表）、## 遗留问题（列表）。"
    "结论需标注来源编号，无来源支撑的结论标注（模型推断）。直接输出 Markdown 原文。"
)


async def run_research(topic: str, on_event=None) -> dict:
    """执行完整研究循环，返回 {"report": md文本, "sources": [...], "process": [...]}。

    on_event  可选回调 on_event(text: str)，用于实时输出过程信息（CLI 打印 / API 记录）。
    """

    def emit(text: str) -> None:
        logger.info(text)
        if on_event:
            on_event(text)

    sources: list[dict] = []          # 来源列表（按 URL 去重）
    seen_urls: set[str] = set()
    draft: list[str] = []             # 正文段落（每个关键词一段）
    process: list[str] = []           # 过程记录

    # ---- 1. 规划 ----
    emit(f"[规划] 主题：{topic}")
    plan = await llm.chat_json(PLAN_SYSTEM, f"研究主题：{topic}\n今天日期：{TODAY}")
    keywords = [k for k in plan.get("keywords", []) if k] or [topic]
    emit(f"[规划] 关键词：{keywords}")
    process.append(f"规划出关键词 {len(keywords)} 个")

    searched: set[str] = set()
    todo = list(keywords)

    # ---- 2. 检索 → 总结 → 判断 循环 ----
    round_no = 0
    for round_no in range(1, MAX_ROUNDS + 1):
        emit(f"===== 第 {round_no}/{MAX_ROUNDS} 轮 =====")
        for kw in todo:
            if kw in searched:
                continue
            searched.add(kw)
            try:
                results = await search.web_search(kw)
            except Exception as exc:  # 单次检索失败不中断
                emit(f"[搜索] 「{kw}」失败：{exc}")
                results = []
            for r in results:
                url = r.get("url") or ""
                if not url:
                    continue  # 无 URL 的结果无法追溯来源，跳过
                if url not in seen_urls:
                    seen_urls.add(url)
                    r["ref"] = len(sources) + 1  # 引用编号
                    sources.append(r)
            results = [r for r in results if r.get("ref")]
            emit(f"[搜索] 「{kw}」→ {len(results)} 条结果（累计来源 {len(sources)} 个）")
            process.append(f"检索「{kw}」，得到 {len(results)} 条结果")

            results_text = "\n".join(
                f"[来源{r['ref']}] {r['title']} | {r['site_name']} | {r['url']}\n  {r['snippet']}"
                for r in results
            ) or "（无搜索结果，可基于常识谨慎推断并标注）"
            paragraph = await llm.chat(
                SUMMARY_SYSTEM,
                f"研究主题：{topic}\n搜索关键词：{kw}\n\n搜索结果：\n{results_text}",
            )
            if paragraph:
                draft.append(f"【{kw}】\n{paragraph}")
            emit(f"[总结] 「{kw}」→ 正文 {len(paragraph)} 字")

        # 判断是否补检
        draft_text = "\n\n".join(draft) or "（尚无内容）"
        sources_text = "\n".join(
            f"[来源{s['ref']}] {s['title']} ({s['site_name']})" for s in sources
        ) or "（无）"
        decision = await llm.chat_json(
            JUDGE_SYSTEM,
            f"研究主题：{topic}\n已检索关键词：{list(searched)}\n来源：\n{sources_text}\n\n"
            f"当前正文：\n{draft_text}",
        )
        emit(f"[评审] sufficient={decision.get('sufficient')} 原因：{decision.get('reason')}")
        process.append(f"第 {round_no} 轮评审：sufficient={decision.get('sufficient')}")
        if decision.get("sufficient") or round_no >= MAX_ROUNDS:
            break
        todo = [k for k in decision.get("new_keywords", []) if k and k not in searched]
        if not todo:
            break
        emit(f"[评审] 补检关键词：{todo}")

    # ---- 3. 综合生成报告 ----
    draft_text = "\n\n".join(draft) or "（检索无结果）"
    sources_list = "\n".join(
        f"[来源{s['ref']}] {s['title']} | {s['site_name']} | {s['url']}" for s in sources
    ) or "（无来源，全文为模型推断）"
    report = await llm.chat(
        REPORT_SYSTEM,
        f"研究主题：{topic}\n今天日期：{TODAY}\n\n研究正文（多段草稿）：\n{draft_text}\n\n"
        f"来源列表：\n{sources_list}",
    )
    emit(f"[完成] 报告 {len(report)} 字 / 来源 {len(sources)} 个 / 轮数 {round_no}")

    return {"report": report, "sources": sources, "process": process}


def save_report(topic: str, result: dict) -> Path:
    """把报告 + 来源 + 过程记录保存为 Markdown 文件，返回文件路径。"""
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    path = out_dir / f"report_{stamp}.md"

    lines = [result["report"], "", "---", "", "## 来源列表", ""]
    lines += [
        f"- [来源{s['ref']}] [{s['title']}]({s['url']}) ({s['site_name']})" for s in result["sources"]
    ] or ["- （无）"]
    lines += ["", "## 研究过程", ""] + [f"- {p}" for p in result["process"]]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
