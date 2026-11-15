"""Normalize severity and vulnerability type values."""

from __future__ import annotations

import logging
from typing import Any, Optional

LOGGER = logging.getLogger("phase3.normalizer")

UNKNOWN_TYPE = ("UNKNOWN", "待归类")


def normalize_severity(raw: Any, mapping: dict[str, str]) -> str:
    """Map a raw severity string to one of 高危/中危/低危/信息."""
    value = "" if raw is None else str(raw).strip()
    lowered = value.lower()
    normalized_mapping = {
        str(key).strip().lower(): str(target) for key, target in mapping.items()
    }
    if lowered in normalized_mapping:
        return normalized_mapping[lowered]

    rules = (
        (("crit", "超危", "严重"), "高危"),
        (("high", "高"), "高危"),
        (("med", "中"), "中危"),
        (("low", "低"), "低危"),
        (("info", "信息"), "信息"),
    )
    for tokens, normalized in rules:
        if any(token in lowered for token in tokens):
            LOGGER.warning("severity_fallback raw=%r -> %s", raw, normalized)
            return normalized

    LOGGER.warning("severity_fallback raw=%r -> 信息 (unmatched)", raw)
    return "信息"


def normalize_type(
    raw: Optional[str],
    catalog: dict[str, tuple[str, str]],
    rules: list[dict[str, Any]] | None = None,
    fallback_name: Optional[str] = None,
) -> tuple[str, str]:
    """Map a raw type string to (type_code, type_name).

    Matching order: catalog name (exact / containment), then the keyword
    rules from ``config/type_mapping.yaml`` in file order, then UNKNOWN.
    ``fallback_name`` (usually ``vuln_name``) is used when ``type_raw`` is
    empty, because the Phase 2 extractor does not populate ``type_raw`` for
    Chinese text-block reports.
    """
    value = "" if raw is None else str(raw).strip()
    if not value:
        value = "" if fallback_name is None else str(fallback_name).strip()
    if not value:
        return UNKNOWN_TYPE
    value = value.lower()
    for type_code, payload in catalog.items():
        type_name = payload[0] if isinstance(payload, (tuple, list)) else str(payload)
        name_lower = type_name.strip().lower()
        if not name_lower:
            continue
        if value == name_lower or name_lower in value:
            return type_code, type_name
    for rule in rules or []:
        keywords = rule.get("keywords") or []
        if any(str(keyword).lower() in value for keyword in keywords):
            return str(rule["type_code"]), str(rule["type_name"])
    return UNKNOWN_TYPE
