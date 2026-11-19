"""Locate the summary count paragraph in a report."""

from __future__ import annotations

import re
from typing import Any

COUNT_RE = re.compile(r"(超危|严重|高危|中危|低危|信息)漏洞(\d+)个")
# Literal phrases kept for backwards compatibility with the Phase 1 profile.
ZERO_LITERALS = (
    "未发现明显安全漏洞",
    "未发现漏洞",
    "novulnerabilityfindings",
    "novulnerabilitiesfound",
    "0个漏洞",
)
# Regex fallbacks covering "本次测试/渗透/评估/检测未发现（明显）安全漏洞" and
# other zero-declaration wordings seen in batch 1 (>= 3 distinct phrasings).
ZERO_REGEXES = (
    re.compile(r"本次(?:测试|渗透|评估|检测)未发现(?:明显)?安全漏洞"),
    re.compile(r"未发现(?:任何)?(?:明显)?安全漏洞"),
    re.compile(r"(?:发现|存在)\s*0\s*个漏洞"),
)


def locate_summary(page_texts: list[str]) -> dict[str, Any]:
    """Normalize text, extract severity counts and zero-declaration."""
    full_text = "\n".join(page_texts)
    normalized = re.sub(r"\s+", "", full_text)
    counts: dict[str, int] = {}
    for match in COUNT_RE.finditer(normalized):
        severity = match.group(1)
        counts[severity] = counts.get(severity, 0) + int(match.group(2))

    lowered = normalized.lower()
    declares_zero = any(pattern in lowered for pattern in ZERO_LITERALS) or any(
        pattern.search(normalized) for pattern in ZERO_REGEXES
    )
    declared_total: int | None
    if counts:
        declared_total = sum(counts.values())
    elif declares_zero:
        declared_total = 0
    else:
        declared_total = None

    return {
        "counts": counts,
        "declared_total": declared_total,
        "declares_zero": declares_zero,
        "normalized_length": len(normalized),
    }
