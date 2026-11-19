"""Knowledge-base lookup tool (read-only, no hit_count updates).

匹配规则：
1. 若 kb_entry.question_pattern 完整出现在归一化后的问题中，覆盖率 = 1.0；
2. 否则覆盖率 = 0.5 × (pattern 关键词在问题中命中的比例)
              + 0.5 × (问题字符被 pattern 关键词覆盖的比例)；
3. 关键词：中文 pattern 拆为完整短语 + 字符二元组；英文按空格/标点切分；
4. 排序键：(是否同属计数型问题, 覆盖率, pattern 长度)；
5. 覆盖率 < MIN_COVERAGE 的不返回。

注意：MVP 只读，不更新 kb_entry.hit_count（方案 C）。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from agents import function_tool

MIN_COVERAGE = 0.6
_SPLIT_RE = re.compile(r"[\s,，。.、;；:：!！?？()（）\[\]【】\"'“”‘’]+")
_SCHEMA_CACHE: dict[str, list[dict[str, Any]]] = {}


def _db_path() -> Path:
    """Return the database path from VULN_DB_PATH."""
    return Path(os.environ.get("VULN_DB_PATH", "app/db/vuln.db"))


def _connection_uri(db_path: Path) -> str:
    """Build the read-only SQLite URI."""
    return f"{db_path.resolve().as_uri()}?mode=ro"


def _normalize(text: str) -> str:
    """Lowercase and strip whitespace and punctuation."""
    return _SPLIT_RE.sub("", text.lower())


def _keywords(pattern: str) -> list[str]:
    """Split a question pattern into keywords.

    Chinese patterns have no spaces, so they are split into the full phrase
    plus character bigrams ("高危漏洞有多少" -> 高危漏洞有多少/高危/危漏/...).
    Latin words are split on whitespace and punctuation.
    """
    keywords: list[str] = []
    for part in _SPLIT_RE.split(pattern):
        normalized = _normalize(part)
        if not normalized:
            continue
        if re.search(r"[一-鿿]", normalized):
            keywords.append(normalized)
            keywords.extend(
                normalized[index : index + 2] for index in range(len(normalized) - 1)
            )
        else:
            keywords.append(normalized)
    return keywords


def _coverage(entry: dict[str, Any], question: str) -> float:
    """Return how well a pattern explains the question.

    - Full pattern appearing in the question scores 1.0.
    - Otherwise the score blends keyword recall (pattern keywords found in
      the question) and the share of question characters explained by the
      pattern's keywords.
    """
    keywords = entry["keywords"]
    if not keywords:
        return 0.0
    normalized = _normalize(question)
    if not normalized:
        return 0.0
    if entry["normalized"] in normalized:
        return 1.0
    hits = sum(1 for keyword in keywords if keyword in normalized)
    keyword_score = hits / len(keywords)
    covered = sum(len(keyword) for keyword in keywords if keyword in normalized)
    span_score = min(covered / len(normalized), 1.0)
    return 0.5 * keyword_score + 0.5 * span_score


def _question_terms(normalized: str) -> list[str]:
    """Return the interrogative/count terms present in a normalized text."""
    return [
        term
        for term in ("有多少", "多少个", "数量", "几个", "多少")
        if term in normalized
    ]


def _is_stat_intent(normalized: str) -> bool:
    """Return True for count-style questions."""
    return bool(_question_terms(normalized))


def _is_chinese(text: str) -> bool:
    """Return True when the text contains Chinese characters."""
    return re.search(r"[一-鿿]", text) is not None


def _load_entries() -> list[dict[str, Any]]:
    """Load approved kb_entry rows, caching them for the process."""
    if "entries" in _SCHEMA_CACHE:
        return _SCHEMA_CACHE["entries"]
    conn = sqlite3.connect(_connection_uri(_db_path()), uri=True, timeout=5)
    try:
        rows = conn.execute(
            """
            SELECT id, question_pattern, sql_template, params_schema
            FROM kb_entry
            WHERE status = 'approved'
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    entries = []
    for row in rows:
        pattern = row[1] or ""
        normalized = _normalize(pattern)
        entries.append(
            {
                "id": int(row[0]),
                "question_pattern": pattern,
                "sql_template": row[2] or "",
                "params_schema": row[3],
                "keywords": _keywords(pattern),
                "normalized": normalized,
                "has_count_question": bool(_question_terms(normalized)),
            }
        )
    _SCHEMA_CACHE["entries"] = entries
    return entries


def reset_kb_cache() -> None:
    """Clear the in-process knowledge cache (for tests)."""
    _SCHEMA_CACHE.clear()


def search_knowledge_payload(question: str) -> str:
    """Find the best approved template for a question.

    匹配规则见模块 docstring：完整命中记 1.0；否则关键词命中率与问题字符
    覆盖率的各半加权；排序为（计数型问题一致, 覆盖率, pattern 长度）；
    覆盖率低于 MIN_COVERAGE=0.6 的条目不返回。
    """
    normalized = _normalize(question)
    best: dict[str, Any] | None = None
    best_key: tuple[float, int, int] = (0.0, 0, 0)
    for entry in _load_entries():
        coverage = _coverage(entry, question)
        if coverage < MIN_COVERAGE:
            continue
        # Ranking: count-question agreement, coverage, then longer pattern.
        count_agreement = int(
            entry["has_count_question"] and _is_stat_intent(normalized)
        )
        key = (count_agreement, coverage, len(entry["question_pattern"]))
        if best is None or key > best_key:
            best = entry
            best_key = key

    if best is None:
        return json.dumps({"hit": False}, ensure_ascii=False)

    params: Any = None
    if best["params_schema"]:
        try:
            params = json.loads(best["params_schema"])
        except (TypeError, ValueError):
            params = best["params_schema"]
    return json.dumps(
        {
            "hit": True,
            "kb_entry_id": best["id"],
            "sql_template": best["sql_template"],
            "params_schema": params,
        },
        ensure_ascii=False,
    )


search_knowledge = function_tool(
    search_knowledge_payload, name_override="search_knowledge"
)
