# -*- coding: utf-8 -*-
"""数据模型：贯穿研究流程的最小数据结构集合（测试版从简，用 dataclass 即可）。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Source:
    """一条来源（搜索结果里的一个网页）。"""
    url: str
    title: str = ""
    site_name: str = ""
    snippet: str = ""
    date: str = ""
    accessed_at: str = ""


@dataclass
class DraftBlock:
    """报告正文草稿的一段（每检索一个关键词累积一段）。"""
    round_no: int
    keyword: str
    text: str
    had_results: bool = True  # 本轮检索是否真的搜到结果（False → 正文属模型推断）


@dataclass
class Confidence:
    """置信度说明：按来源数量分级 + 信息截止时间。"""
    overall: str = "low"  # high / medium / low
    info_cutoff: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class ResearchProcess:
    """研究过程记录：检索关键词、已读 URL、迭代轮数、逐步明细。"""
    plan: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    reviewed_urls: list[str] = field(default_factory=list)
    iterations: int = 0
    steps: list[dict] = field(default_factory=list)  # {type, round, detail}


@dataclass
class ReportSection:
    """报告正文分节（heading=关键词，body=对应草稿段落）。"""
    heading: str
    body: str
    inferred: bool = False


@dataclass
class ResearchResult:
    """一次研究的最终产物。"""
    topic: str
    title: str
    summary: str
    sections: list[ReportSection] = field(default_factory=list)
    key_conclusions: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    process: ResearchProcess = field(default_factory=ResearchProcess)
    confidence: Confidence = field(default_factory=Confidence)

    def to_dict(self) -> dict:
        return asdict(self)
