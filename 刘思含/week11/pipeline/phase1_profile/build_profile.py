"""Build ``corpus_profile.json`` and ``sample_notes.md`` from inspection data."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.phase1_profile.constants import (
    CANONICAL_RULES,
    CLEAN_HEADER_MAX_LEN,
    SEVERITY_TERMS,
    SUMMARY_PATTERNS,
)

LOGGER = logging.getLogger("phase1_profile")

DEFAULT_SELECTION = Path("data/sample_selection.json")
DEFAULT_INSPECTION = Path("data/sample_inspection.json")
DEFAULT_NOTES = Path("data/sample_notes.md")
DEFAULT_PROFILE = Path("data/corpus_profile.json")

TOP_SECTION_PATTERN = re.compile(
    r"^(第[一二三四五六七八九十0-9]+章|[一二三四五六七八九十]+、)"
)
SENTENCE_PUNCTUATION = "。；！？，,;!?"


def _clean_header(header: str) -> str:
    """Normalize a table header."""
    return " ".join(header.split())


def _is_clean_header(header: str) -> bool:
    """Return True when a header looks like a column name, not prose."""
    cleaned = _clean_header(header)
    if not cleaned or len(cleaned) > CLEAN_HEADER_MAX_LEN:
        return False
    if any(char in SENTENCE_PUNCTUATION for char in cleaned):
        return False
    if cleaned.lower() in SEVERITY_TERMS:
        return False
    return not cleaned.isdigit()


def _canonical_header(header: str) -> str:
    """Map a raw header to a canonical field name when possible."""
    normalized = header.strip().lower()
    for canonical, keywords in CANONICAL_RULES.items():
        if any(keyword in normalized for keyword in keywords):
            return canonical
    return "unmapped"


def _is_appendix_table(headers: list[str]) -> bool:
    """Return True for the appendix risk-level definition table."""
    clean = [_clean_header(header) for header in headers]
    return any("风险等级" in header for header in clean) and any(
        "说明" in header for header in clean
    )


def _clean_headers(sample: dict[str, Any]) -> set[str]:
    """Return clean, non-appendix headers from substantive tables."""
    headers: set[str] = set()
    for table in sample["tables"]:
        if table["row_count"] < 3 or _is_appendix_table(table["headers"]):
            continue
        headers.update(
            _clean_header(header)
            for header in table["headers"]
            if _is_clean_header(header)
        )
    return headers


def _appendix_headers(samples: list[dict[str, Any]]) -> list[str]:
    """Return headers observed on the appendix risk-level table."""
    headers: set[str] = set()
    for sample in samples:
        for table in sample["tables"]:
            if not _is_appendix_table(table["headers"]):
                continue
            headers.update(
                _clean_header(header)
                for header in table["headers"]
                if _clean_header(header)
            )
    return sorted(headers)


def _header_aliases(samples: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Aggregate canonical -> clean observed header aliases."""
    mapping: dict[str, set[str]] = {}
    for sample in samples:
        for header in _clean_headers(sample):
            mapping.setdefault(_canonical_header(header), set()).add(header)
    return {key: sorted(values) for key, values in sorted(mapping.items()) if values}


def _ordered_top_sections(sample: dict[str, Any]) -> list[str]:
    """Return level-1 section titles in document order."""
    return [
        title for title in sample["section_titles"] if TOP_SECTION_PATTERN.search(title)
    ]


def _top_level_sections(sample: dict[str, Any]) -> set[str]:
    """Return level-1 section titles such as ``一、测试概述``."""
    return set(_ordered_top_sections(sample))


def _section_signature(sample: dict[str, Any]) -> set[str]:
    """Return a normalized level-1 section signature."""
    return {title.strip() for title in _top_level_sections(sample)}


def _jaccard(left: set[str], right: set[str]) -> float:
    """Jaccard similarity; empty/empty counts as identical."""
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def _has_vuln_table(sample: dict[str, Any]) -> bool:
    """Detect whether a sample has a clean vulnerability-detail table."""
    keywords = ("漏洞名称", "漏洞标题", "url", "位置", "host", "ip")
    for table in sample["tables"]:
        if table["row_count"] < 3 or _is_appendix_table(table["headers"]):
            continue
        headers = [_clean_header(header) for header in table["headers"]]
        clean = [header for header in headers if _is_clean_header(header)]
        if len(clean) < 2:
            continue
        if any(keyword in header.lower() for header in clean for keyword in keywords):
            return True
    return False


def _template_groups(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group samples by report type, then by level-1 section signature."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for sample in samples:
        by_type.setdefault(sample["report_type"], []).append(sample)

    groups: list[dict[str, Any]] = []
    index = 0
    type_order = {"渗透测试报告": 0, "回归测试报告": 1}
    for report_type, items in sorted(
        by_type.items(), key=lambda item: type_order.get(item[0], 99)
    ):
        clusters: list[dict[str, Any]] = []
        for sample in items:
            signature = _section_signature(sample)
            for cluster in clusters:
                if _jaccard(signature, cluster["signature"]) >= 0.5:
                    cluster["samples"].append(sample)
                    cluster["signature"] |= signature
                    break
            else:
                clusters.append({"signature": set(signature), "samples": [sample]})
        for cluster in clusters:
            index += 1
            grouped = cluster["samples"]
            sections: list[str] = []
            for sample in grouped:
                for title in _ordered_top_sections(sample):
                    if title not in sections:
                        sections.append(title)
            has_vuln_table = any(_has_vuln_table(sample) for sample in grouped)
            groups.append(
                {
                    "group_id": f"group_{index}",
                    "description": (
                        f"{report_type}模板（{len(grouped)} 份）；"
                        f"一级章节：{' / '.join(sections) or '未识别'}"
                        + (
                            "；未识别到规则漏洞详情表"
                            if not has_vuln_table
                            else "；识别到漏洞详情表"
                        )
                    ),
                    "sample_files": [sample["relative_path"] for sample in grouped],
                    "report_types": {report_type: len(grouped)},
                    "header_aliases": _header_aliases(grouped),
                    "section_titles": sections,
                    "vulnerability_table_detected": has_vuln_table,
                }
            )
    return groups


def _severity_vocabulary(samples: list[dict[str, Any]]) -> list[str]:
    """Return observed severity values in a stable severity order."""
    order = (
        "超危",
        "严重",
        "高危",
        "中危",
        "低危",
        "critical",
        "high",
        "medium",
        "low",
        "info",
        "information",
        "信息",
        "提示",
    )
    counter: Counter[str] = Counter()
    for sample in samples:
        for value in sample["severity_values"]:
            normalized = value.strip()
            if normalized.lower() in SEVERITY_TERMS:
                counter[normalized] += 1

    def rank(value: str) -> int:
        lowered = value.lower()
        return order.index(lowered) if lowered in order else len(order)

    return sorted(counter, key=lambda value: (rank(value), value))


def _tables_span_pages(samples: list[dict[str, Any]]) -> bool:
    """Detect adjacent-page tables with identical clean headers."""
    for sample in samples:
        tables = sample["tables"]
        for current, following in zip(tables, tables[1:]):
            if following["page"] != current["page"] + 1:
                continue
            if current["row_count"] < 3:
                continue
            if _is_appendix_table(current["headers"]):
                continue
            left = [
                _clean_header(header).lower()
                for header in current["headers"]
                if _is_clean_header(header)
            ]
            right = [
                _clean_header(header).lower()
                for header in following["headers"]
                if _is_clean_header(header)
            ]
            if left and left == right:
                return True
    return False


def _image_stats(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate raw and evidence image statistics."""
    total_pages = sum(sample["page_count"] for sample in samples) or 1
    raw_total = sum(sample["image_count"] for sample in samples)
    evidence_total = sum(sample["evidence_image_count"] for sample in samples)
    raw_pages = sum(len(sample["image_pages"]) for sample in samples)
    evidence_pages = sum(len(sample["evidence_image_pages"]) for sample in samples)
    raw_kbs = [
        value
        for sample in samples
        for value in (
            sample["image_size_stats"]["min_kb"],
            sample["image_size_stats"]["max_kb"],
        )
        if value is not None
    ]
    evidence_kbs = [
        value
        for sample in samples
        for value in (
            sample["evidence_image_size_stats"]["min_kb"],
            sample["evidence_image_size_stats"]["max_kb"],
        )
        if value is not None
    ]
    evidence_types: Counter[str] = Counter()
    raw_types: Counter[str] = Counter()
    for sample in samples:
        evidence_types.update(sample["evidence_image_type_guess"]["counts"])
        raw_types.update(sample["image_type_guess"]["counts"])
    typical = [
        key
        for key, value in evidence_types.items()
        if evidence_total and value / evidence_total >= 0.2
    ]
    return {
        "avg_images_per_report": round(raw_total / len(samples), 2),
        "image_page_ratio": round(raw_pages / total_pages, 3),
        "total_images_sampled": raw_total,
        "max_image_kb": round(max(raw_kbs), 1) if raw_kbs else None,
        "min_image_kb": round(min(raw_kbs), 1) if raw_kbs else None,
        "type_counts": {
            key: raw_types.get(key, 0) for key in ("screenshot", "chart", "unknown")
        },
        "evidence_avg_images_per_report": round(evidence_total / len(samples), 2),
        "evidence_image_page_ratio": round(evidence_pages / total_pages, 3),
        "evidence_total_images": evidence_total,
        "evidence_max_image_kb": round(max(evidence_kbs), 1) if evidence_kbs else None,
        "evidence_min_image_kb": round(min(evidence_kbs), 1) if evidence_kbs else None,
        "evidence_type_counts": {
            key: evidence_types.get(key, 0)
            for key in ("screenshot", "chart", "unknown")
        },
        "typical_image_types": typical,
        "template_image_count": sum(
            sample["template_image_count"] for sample in samples
        ),
        "small_image_count": sum(sample["small_image_count"] for sample in samples),
        "template_signatures": sorted(
            {
                f"{key['width']}x{key['height']}@{key['kb']}KB"
                for sample in samples
                for key in sample["template_image_keys"]
            }
        ),
        "per_report": [
            {
                "relative_path": sample["relative_path"],
                "raw_images": sample["image_count"],
                "evidence_images": sample["evidence_image_count"],
                "template_images": sample["template_image_count"],
            }
            for sample in samples
        ],
    }


def _table_extraction_observation(samples: list[dict[str, Any]]) -> str:
    """Summarize what pdfplumber can and cannot extract."""
    table_count = sum(len(sample["tables"]) for sample in samples)
    vuln_tables = sum(_has_vuln_table(sample) for sample in samples)
    return (
        f"{len(samples)} 份样本共提取 {table_count} 个表格对象，"
        f"其中 {vuln_tables} 个疑似漏洞详情表。"
        "渗透测试报告的漏洞条目以「N．名称（等级）」文本标题 + 截图呈现；"
        "回归测试报告以「（N）名称 + 漏洞描述：/ 漏洞位置：」KV 文本呈现；"
        "pdfplumber 稳定识别到的规则表主要是附录「风险等级定义表」。"
        "Phase 2 不应只依赖表格定位，应以文本/KV 解析为主，"
        "并用附录与摘要计数做交叉校验。"
    )


def build_profile(
    samples: list[dict[str, Any]], selection: dict[str, Any]
) -> dict[str, Any]:
    """Build corpus_profile.json content with approved=false."""
    page_counts = [sample["page_count"] for sample in samples]
    hints = sorted(
        {hint for sample in samples for hint in sample["summary_count_hints"]}
    )
    has_summary = bool(hints) or any(
        any(
            keyword in header
            for keyword in ("统计", "汇总", "总数", "高危", "中危", "低危")
        )
        for sample in samples
        for table in sample["tables"]
        for header in table["headers"]
    )
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_seed": selection["seed"],
        "sample_files": [sample["relative_path"] for sample in samples],
        "page_count_range": [min(page_counts), max(page_counts)],
        "is_scanned_ratio": round(
            sum(1 for sample in samples if sample["is_scanned"]) / len(samples),
            3,
        ),
        "template_groups": _template_groups(samples),
        "header_aliases_observed": _header_aliases(samples),
        "appendix_table_headers_observed": _appendix_headers(samples),
        "severity_vocabulary": _severity_vocabulary(samples),
        "has_summary_count_table": has_summary,
        "summary_count_format": "text_paragraph",
        "summary_count_patterns": {
            "patterns": [pattern.pattern for pattern in SUMMARY_PATTERNS],
            "observed_snippets": hints[:20],
        },
        "tables_span_pages": _tables_span_pages(samples),
        "table_extraction_observation": _table_extraction_observation(samples),
        "image_stats": _image_stats(samples),
        "image_strategy": {
            "ocr_enabled": True,
            "ocr_engine": "paddleocr",
            "ocr_languages": ["ch", "en"],
            "image_type_rules": {
                "screenshot": {
                    "min_width": 600,
                    "aspect_ratio_range": [1.2, 2.5],
                },
                "chart": {
                    "min_width": 300,
                    "aspect_ratio_range": [1.0, 2.0],
                },
            },
            "exclude_template_images": True,
            "exclude_small_images": {
                "min_width": 300,
                "min_height": 150,
                "min_kb": 20,
            },
            "link_by_page_proximity": True,
            "link_page_window": 1,
            "resize_before_ocr": {"max_side_px": 2048, "max_kb": 2048},
            "vlm_description_enabled": False,
        },
        "parse_strategy": {
            "primary_adapter": "pdfplumber",
            "fallback_adapter": "pdfplumber",
            "kv_fallback_enabled": True,
            "vlm_description_enabled": False,
        },
        "approved": False,
        "approved_by": None,
        "approved_at": None,
    }


def _format_table_observation(sample: dict[str, Any]) -> str:
    """Format table headers for sample_notes.md."""
    if not sample["tables"]:
        return "  - 未提取到表格"
    lines = []
    for table in sample["tables"]:
        headers = " | ".join(header for header in table["headers"] if header)
        lines.append(
            f"  - 第 {table['page']} 页：{headers or '(空表头)'} "
            f"（{table['row_count']} 行）"
        )
    return "\n".join(lines)


def write_notes(
    samples: list[dict[str, Any]], profile: dict[str, Any], path: Path
) -> None:
    """Write the human-readable Phase 1 notes."""
    lines = [
        "# Phase 1 语料勘察记录（sample_notes）",
        "",
        f"- 生成时间：{profile['generated_at']}",
        f"- 抽样 seed：{profile['sample_seed']}",
        f"- 样本数：{len(samples)}",
        f"- 页数范围：{profile['page_count_range']}",
        f"- 扫描件比例：{profile['is_scanned_ratio']:.2%}",
        f"- 模板分组数：{len(profile['template_groups'])}",
        "",
        "## 抽样覆盖",
        "",
        "| 样本 | 批次 | 团队 | 报告类型 | 页数 | 扫描件 | 原始图片 | 有效图片 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sample in samples:
        lines.append(
            f"| {sample['slot_id']} | {sample['batch']} | {sample['team']} "
            f"| {sample['report_type']} | {sample['page_count']} "
            f"| {'是' if sample['is_scanned'] else '否'} "
            f"| {sample['image_count']} "
            f"| {sample['evidence_image_count']} |"
        )

    lines.extend(["", "## 逐份观察", ""])
    for sample in samples:
        raw_stats = sample["image_size_stats"]
        ev_stats = sample["evidence_image_size_stats"]
        lines.extend(
            [
                f"### 样本 {sample['slot_id']}",
                "",
                f"- 相对路径：`{sample['relative_path']}`",
                f"- pdf_id：`{sample['pdf_id']}`",
                f"- 批次 / 团队 / 类型：{sample['batch']} / "
                f"{sample['team']} / {sample['report_type']}",
                f"- 抽样原因：{sample['selection_reason']}",
                f"- 页数：{sample['page_count']}",
                f"- 是否扫描件：{'是' if sample['is_scanned'] else '否'}"
                f"（前 3 页平均字符数 {sample['first_three_pages_avg_chars']}）",
                f"- 原始图片：{sample['image_count']} 张，涉及页 "
                f"{sample['image_pages'] or '无'}；"
                f"min/max/avg KB = "
                f"{raw_stats['min_kb']}/{raw_stats['max_kb']}/{raw_stats['avg_kb']}",
                f"- 模板/页眉图片：{sample['template_image_count']} 张；"
                f"过小图片：{sample['small_image_count']} 张；"
                f"模板尺寸：{sample['template_image_keys'] or '无'}",
                f"- 有效证据图：{sample['evidence_image_count']} 张，涉及页 "
                f"{sample['evidence_image_pages'] or '无'}；"
                f"min/max/avg KB = "
                f"{ev_stats['min_kb']}/{ev_stats['max_kb']}/{ev_stats['avg_kb']}",
                f"- 原始图片类型比例：screenshot="
                f"{sample['image_type_guess']['screenshot_ratio']}, chart="
                f"{sample['image_type_guess']['chart_ratio']}, unknown="
                f"{sample['image_type_guess']['unknown_ratio']}",
                f"- 有效图片类型比例：screenshot="
                f"{sample['evidence_image_type_guess']['screenshot_ratio']}, "
                f"chart={sample['evidence_image_type_guess']['chart_ratio']}, "
                f"unknown={sample['evidence_image_type_guess']['unknown_ratio']}",
                f"- 疑似章节标题："
                f"{' / '.join(sample['section_titles'][:12]) or '未识别'}",
                f"- 摘要计数线索："
                f"{' | '.join(sample['summary_count_hints']) or '未发现'}",
                "- 表头观察：",
                _format_table_observation(sample),
                "",
            ]
        )
        anomalies = []
        if sample["is_scanned"]:
            anomalies.append("扫描件（文本层不足，需 OCR）")
        if sample["evidence_image_count"] == 0:
            anomalies.append("无有效证据图")
        if not sample["summary_count_hints"]:
            anomalies.append("未发现摘要计数线索")
        if not sample["tables"]:
            anomalies.append("未提取到表格")
        if anomalies:
            lines.append(f"- 异常/注意：{'；'.join(anomalies)}")
            lines.append("")

    lines.extend(["## 模板分组", ""])
    for group in profile["template_groups"]:
        lines.extend(
            [
                f"### {group['group_id']}",
                "",
                f"- 描述：{group['description']}",
                f"- 一级章节：{' / '.join(group['section_titles']) or '未识别'}",
                f"- 是否识别到规则漏洞表："
                f"{'是' if group['vulnerability_table_detected'] else '否'}",
                f"- 表头别名："
                f"{json.dumps(group['header_aliases'], ensure_ascii=False)}",
                "- 样本：",
            ]
        )
        for sample_file in group["sample_files"]:
            lines.append(f"  - `{sample_file}`")
        lines.append("")

    lines.extend(
        [
            "## 渗透测试报告 vs 回归测试报告",
            "",
        ]
    )
    penetration = [
        sample for sample in samples if sample["report_type"] == "渗透测试报告"
    ]
    regression = [
        sample for sample in samples if sample["report_type"] == "回归测试报告"
    ]

    def sections(items: list[dict[str, Any]]) -> list[str]:
        ordered: list[str] = []
        for item in items:
            for title in _ordered_top_sections(item):
                if title not in ordered:
                    ordered.append(title)
        return ordered

    def headers(items: list[dict[str, Any]]) -> list[str]:
        return sorted({header for sample in items for header in _clean_headers(sample)})

    p_sections = sections(penetration)
    r_sections = sections(regression)
    p_headers = headers(penetration)
    r_headers = headers(regression)
    lines.append(f"- 渗透测试报告一级章节：{' / '.join(p_sections) or '无'}")
    lines.append(f"- 回归测试报告一级章节：{' / '.join(r_sections) or '无'}")
    lines.append(f"- 渗透测试报告表头集合：{' / '.join(p_headers) or '无'}")
    lines.append(f"- 回归测试报告表头集合：{' / '.join(r_headers) or '无'}")
    lines.append(
        "- 说明：表头集合仅统计疑似漏洞详情表；附录「风险等级定义表」的"
        "表头已单独记录在 `corpus_profile.appendix_table_headers_observed`。"
    )
    lines.append(
        "- 风险等级用词：摘要中主要使用「超危/高危/中危/低危」；"
        "样本 1 使用「严重漏洞」表述，Phase 2 归一化时需把「严重」"
        "映射到最高级。"
    )
    lines.append(
        "- 跨页：未观察到规则表格跨页；漏洞条目文本可能跨页，"
        "Phase 2 需按文本结构判断。"
    )
    only_p = sorted(set(p_headers) - set(r_headers))
    only_r = sorted(set(r_headers) - set(p_headers))
    lines.append(
        "- 结论："
        + (
            "两类报告的章节结构与表头存在差异，已分为不同 template group。"
            if set(p_sections) != set(r_sections) or only_p or only_r
            else "本次样本中两类报告结构一致。"
        )
    )
    if only_p:
        lines.append(f"  - 仅渗透测试报告出现：{' / '.join(only_p)}")
    if only_r:
        lines.append(f"  - 仅回归测试报告出现：{' / '.join(only_r)}")
    lines.extend(
        [
            "",
            "## 表格抽取观察",
            "",
            profile["table_extraction_observation"],
            "",
            "## 图片观察",
            "",
            f"- 原始图片总数：{profile['image_stats']['total_images_sampled']}；"
            f"有效证据图：{profile['image_stats']['evidence_total_images']}；"
            f"模板/页眉图：{profile['image_stats']['template_image_count']}；"
            f"过小图：{profile['image_stats']['small_image_count']}",
            f"- 原始图片页面占比：{profile['image_stats']['image_page_ratio']}；"
            f"有效图片页面占比："
            f"{profile['image_stats']['evidence_image_page_ratio']}",
            f"- 典型模板尺寸："
            f"{profile['image_stats']['template_signatures'] or '无'}",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point for rebuilding profile and notes."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--inspection", type=Path, default=DEFAULT_INSPECTION)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    samples = json.loads(args.inspection.read_text(encoding="utf-8"))
    profile = build_profile(samples, selection)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_notes(samples, profile, args.notes)
    LOGGER.info("written=%s", args.profile.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
