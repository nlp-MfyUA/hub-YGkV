"""Extract fields from located text blocks."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional, Union

from pipeline.common.types import (
    CanonicalVulnRecord,
    RetestRecord,
    TextBlock,
)

PEN_LABELS = {
    "description": re.compile(r"^（1）\s*漏洞描述|^\d+\s+漏洞描述"),
    "location": re.compile(r"^（2）\s*漏洞位置|^\d+\s+漏洞位置"),
    "test_process": re.compile(r"^（3）\s*测试过程|^\d+\s+测试过程"),
    "remediation": re.compile(r"^（4）\s*整改建议|^\d+\s+整改建议"),
}
REG_DESCRIPTION = re.compile(r"^漏洞描述\s*[:：]?\s*(?P<inline>.*)$")
REG_LOCATION = re.compile(r"^漏洞位置\s*[:：]?\s*(?P<inline>.*)$")
SEVERITY_RE = re.compile(r"（(超危|严重|高危|中危|低危)）")
KV_FIELDS = {
    "severity": re.compile(r"^Severity\s*[:：]\s*(?P<v>.+)$", re.I),
    "vuln_name": re.compile(r"^Vulnerability\s*[:：]\s*(?P<v>.+)$", re.I),
    "cwe": re.compile(r"^CWE\s*[:：]\s*(?P<v>.+)$", re.I),
    "location": re.compile(r"^Location\s*[:：]\s*(?P<v>.+)$", re.I),
}
STATUS_RULES = (
    ("not_reproducible", ("无法复现", "未能复现", "不可复现")),
    ("partial", ("部分修复", "部分整改", "部分解决")),
    ("unfixed", ("未修复", "未整改", "仍然存在", "仍存在", "未解决")),
    ("fixed", ("已修复完成", "已修复", "修复完成", "已整改", "整改完成", "已解决")),
)


def _join(lines: list[str]) -> str:
    """Join lines into a single normalized fragment."""
    return " ".join(line.strip() for line in lines if line.strip()).strip()


def _snippet(text: str, limit: int = 300) -> Optional[str]:
    """Return a <=303-character snippet for description_snippet."""
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _label_indices(block: TextBlock) -> dict[str, int]:
    """Return the first line index of each pentest field label."""
    indices: dict[str, int] = {}
    for index, line in enumerate(block.lines):
        for name, pattern in PEN_LABELS.items():
            if name not in indices and pattern.match(line):
                indices[name] = index
    return indices


def _section(lines: list[str], start: int | None, end: int | None) -> list[str]:
    """Return lines between two label indices."""
    if start is None:
        return []
    stop = end if end is not None and end > start else len(lines)
    return lines[start + 1 : stop]


def _extract_pentest(block: TextBlock, source_file: str) -> CanonicalVulnRecord:
    """Build a CanonicalVulnRecord from a pentest block."""
    indices = _label_indices(block)
    description = _join(
        _section(
            block.lines,
            indices.get("description"),
            indices.get("location"),
        )
    )
    location = _join(
        _section(
            block.lines,
            indices.get("location"),
            indices.get("test_process"),
        )
    )
    # `test_process` / `remediation` are retained in block JSON by run_parse;
    # the canonical record only carries description/location/severity.
    severity_match = SEVERITY_RE.search(block.raw_title)
    severity_raw = severity_match.group(1) if severity_match else "未标注"
    confidence = "high" if description and location else "medium"
    return CanonicalVulnRecord(
        vuln_name=block.title,
        severity_raw=severity_raw,
        source_file=source_file,
        source_page=block.page_start,
        type_raw=None,
        cvss_score=None,
        component=None,
        cwe_id=None,
        description_snippet=_snippet(description or location),
        extraction_method="text_block",
        confidence=confidence,
    )


def _retest_status(status_text: str) -> str:
    """Map a retest status sentence to the five-value enum."""
    for status, keywords in STATUS_RULES:
        if any(keyword in status_text for keyword in keywords):
            return status
    return "unknown"


def _extract_retest(block: TextBlock, source_file: str) -> RetestRecord:
    """Build a RetestRecord from a retest block."""
    description_lines: list[str] = []
    location_lines: list[str] = []
    current: Optional[str] = None
    for line in block.lines[1:]:
        desc_match = REG_DESCRIPTION.match(line)
        loc_match = REG_LOCATION.match(line)
        if desc_match:
            current = "description"
            inline = desc_match.group("inline").strip()
            if inline:
                description_lines.append(inline)
            continue
        if loc_match:
            current = "location"
            inline = loc_match.group("inline").strip()
            if inline:
                location_lines.append(inline)
            continue
        if current == "description":
            description_lines.append(line)
        elif current == "location":
            location_lines.append(line)

    status_text = (block.status_text or "").strip()
    status = _retest_status(status_text)
    if status != "unknown" and not status_text:
        status = "unknown"
    evidence = _snippet(status_text or _join(description_lines))
    return RetestRecord(
        retest_report_path=source_file,
        raw_vuln_name=block.title,
        component=None,
        retest_status_raw=status_text,
        retest_status=status,
        retest_date=block.retest_date,
        evidence_snippet=evidence,
        source_page=block.page_start,
        evidence_page=block.status_page,
        parent_vuln_name=block.title,
        match_confidence="none",
    )


def _extract_kv(block: TextBlock, source_file: str) -> CanonicalVulnRecord:
    """Build a CanonicalVulnRecord from an English KV block."""
    values: dict[str, str] = {}
    for line in block.lines:
        for name, pattern in KV_FIELDS.items():
            match = pattern.match(line)
            if match and name not in values:
                values[name] = match.group("v").strip()
    cwe = values.get("cwe")
    return CanonicalVulnRecord(
        vuln_name=values.get("vuln_name", block.title),
        severity_raw=values.get("severity", "未标注"),
        source_file=source_file,
        source_page=block.page_start,
        type_raw=None,
        cvss_score=None,
        component=None,
        cwe_id=cwe if cwe and re.fullmatch(r"CWE-\d+", cwe) else None,
        description_snippet=_snippet(values.get("location")),
        extraction_method="kv_block",
        confidence="low",
    )


def assign_instance_index(
    records: list[Union[CanonicalVulnRecord, RetestRecord]],
) -> list[Union[CanonicalVulnRecord, RetestRecord]]:
    """Renumber instances by appearance order, ignoring input values."""
    counters: dict[tuple[str, str], int] = {}
    assigned: list[Union[CanonicalVulnRecord, RetestRecord]] = []
    for record in records:
        if isinstance(record, RetestRecord):
            name = record.raw_vuln_name
        else:
            name = record.vuln_name
        key = (name, record.component or "")
        counters[key] = counters.get(key, 0) + 1
        assigned.append(replace(record, instance_index=counters[key]))
    return assigned


def extract_record(
    block: TextBlock, source_file: str
) -> Union[CanonicalVulnRecord, RetestRecord]:
    """Extract one record from a text block."""
    if block.format == "kv_block":
        return _extract_kv(block, source_file)
    if block.report_type == "retest":
        return _extract_retest(block, source_file)
    return _extract_pentest(block, source_file)


def extract_records(
    blocks: list[TextBlock], source_file: str
) -> list[Union[CanonicalVulnRecord, RetestRecord]]:
    """Extract all records from text blocks."""
    records = [extract_record(block, source_file) for block in blocks]
    return assign_instance_index(records)
