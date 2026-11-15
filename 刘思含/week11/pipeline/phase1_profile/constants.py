"""Shared heuristics for Phase 1 inspection and profile building."""

from __future__ import annotations

import re

SCANNED_AVG_CHARS = 50
FIRST_PAGES_TEXT_LIMIT = 2000
SMALL_IMAGE_WIDTH = 300
SMALL_IMAGE_HEIGHT = 150
SMALL_IMAGE_KB = 20
CLEAN_HEADER_MAX_LEN = 30

SEVERITY_TERMS = {
    "critical",
    "high",
    "medium",
    "low",
    "info",
    "information",
    "超危",
    "严重",
    "高危",
    "中危",
    "低危",
    "信息",
    "提示",
}
SEVERITY_HEADER_KEYWORDS = (
    "severity",
    "风险等级",
    "严重程度",
    "风险级别",
    "等级",
)
SECTION_PATTERNS = (
    re.compile(r"^第[一二三四五六七八九十百0-9]+[章节部分]"),
    re.compile(r"^[0-9]+(\.[0-9]+){0,3}[\s、.．]"),
    re.compile(r"^[一二三四五六七八九十]+[、.．]"),
    re.compile(r"^(摘\s*要|概\s*述|测试结果|漏洞详情|风险分析|附录|总结|结论)"),
)
SUMMARY_PATTERNS = (
    re.compile(r"(?i)\b(critical|high|medium|low|info(?:rmation)?)\b\s*[:：]?\s*(\d+)"),
    re.compile(r"(超危|严重|高危|中危|低危|信息)\s*[:：]?\s*(\d+)\s*(个|项|条)?"),
    re.compile(r"(超危|严重|高危|中危|低危|信息)漏洞\s*[:：]?\s*(\d+)"),
)
CANONICAL_RULES = {
    "severity": ("severity", "风险等级", "严重程度", "风险级别", "等级"),
    "vuln_name": (
        "漏洞名称",
        "漏洞",
        "名称",
        "问题",
        "风险项",
        "finding",
        "vulnerability",
        "标题",
    ),
    "component": (
        "组件",
        "系统",
        "资产",
        "位置",
        "url",
        "component",
        "ip",
        "域名",
    ),
    "cwe": ("cwe",),
    "cvss": ("cvss", "评分"),
    "type": ("类型", "分类", "type", "类别"),
    "description": ("描述", "说明", "详情", "description", "detail"),
    "page": ("页码", "page"),
}
