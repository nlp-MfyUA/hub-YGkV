"""Run the ChatBI evaluation set (``tests/chat_eval.csv``) against the agent.

Usage (from the repository root)::

    python -m tests.eval.run_chat_eval --db-path app/db/vuln_test_agent.db

Comparison rules are implemented for ``number`` / ``list`` / ``ranking`` /
``refusal`` / ``clarification``. Rows whose ``question`` contains ``|||``
run sequentially in one session and are checked on the final turn only.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
from pathlib import Path

from app.main import chat_once
from app.session import get_session

EVAL_CSV = Path(__file__).resolve().parents[1] / "chat_eval.csv"
DEFAULT_DB_PATH = Path("app/db/vuln_test_agent.db")

_REFUSAL_SYNONYMS = {
    "无法": ("无法", "没法", "超出"),
    "只能统计": (
        "只能统计",
        "只能查询和统计",
        "只能做统计",
        "只能对漏洞数据做统计",
        "只能做数据统计",
    ),
    "不能归因": (
        "不能归因",
        "不能做归因分析",
        "不能做归因",
        "无法归因",
        "做归因分析",
        "不能分析原因",
    ),
}


def _contains_number(answer: str, number: str) -> bool:
    """Return True when ``number`` appears as a standalone number."""
    pattern = rf"(?<!\d){re.escape(number)}(?!\d)"
    return re.search(pattern, answer.replace(",", "")) is not None


def _contains_standalone_number(answer: str, expected: str) -> bool:
    """Return True when ``expected`` appears as a standalone number.

    Long digit runs (chart paths, timestamps) and inline code are stripped
    first so a path or SQL fragment cannot satisfy the check.
    """
    cleaned = re.sub(
        r"[a-zA-Z0-9_/\\-]*\d{4,}[a-zA-Z0-9_/\\-]*", "", answer
    )
    cleaned = re.sub(r"`[^`]*`", "", cleaned)
    pattern = rf"(?<![\d.]){re.escape(expected)}(?![\d.])"
    return re.search(pattern, cleaned) is not None


def _check(row: dict[str, str], answer: str) -> bool:
    """Return whether ``answer`` satisfies the row's ``expected_value``."""
    expected_type = row["expected_answer_type"].strip()
    expected_value = row["expected_value"].strip()

    if expected_type == "number":
        return _contains_standalone_number(answer, expected_value)

    if expected_type == "list":
        expected_numbers = re.findall(r"\d+(?:\.\d+)?", expected_value)
        if expected_numbers:
            return all(
                _contains_number(answer, number)
                for number in expected_numbers
            )
        parts = [
            part.strip()
            for part in re.split(r"[,;]", expected_value)
            if part.strip()
        ]
        normalized_answer = re.sub(r"\s+", "", answer)
        return all(
            re.sub(r"\s+", "", part) in normalized_answer for part in parts
        )

    if expected_type == "ranking":
        return expected_value.lower() in answer.lower()

    if expected_type == "refusal":
        keywords = [item.strip() for item in expected_value.split("|") if item.strip()]
        for keyword in keywords:
            options = _REFUSAL_SYNONYMS.get(keyword, (keyword,))
            if any(option in answer for option in options):
                return True
        return False

    if expected_type == "clarification":
        markers = ("？", "?", "请问", "您是指")
        return any(marker in answer for marker in markers)

    return False


def _split_turns(question: str) -> list[str]:
    """Split a ``|||``-joined question into turns."""
    return [part.strip() for part in question.split("|||") if part.strip()]


def _reset_session(user_id: str) -> None:
    """Remove stale history for a deterministic multi-turn eval run."""
    get_session(user_id).db_path.unlink(missing_ok=True)


async def _run_case(
    row: dict[str, str],
    db_path: Path,
    user: str,
) -> bool:
    """Run one eval row and print its answer plus verdict.

    Multi-turn rows use one session (``eval_<id>``), call ``chat_once`` once
    per turn, and check only the final answer.
    """
    case_id = row.get("id", "<missing-id>")
    turns = _split_turns(row["question"])
    if not turns:
        print(f"[FAIL] {case_id}: empty question")
        return False
    is_multi = len(turns) > 1
    session_user = f"eval_{case_id}" if is_multi else user
    if is_multi:
        _reset_session(session_user)

    result = None
    for index, turn in enumerate(turns):
        result = await chat_once(
            user_id=session_user,
            question=turn,
            db_path=db_path,
            with_history=is_multi and index > 0,
        )
        print("-" * 70)
        if is_multi:
            print(f"{case_id} turn {index + 1}/{len(turns)}: {turn}")
        else:
            print(f"{case_id}: {turn}")
        print(result.answer)

    assert result is not None
    passed = _check(row, result.answer)
    print(f"[{'PASS' if passed else 'FAIL'}] {case_id}")
    return passed


def _read_rows(limit: int | None) -> list[dict[str, str]]:
    """Read eval rows from the CSV."""
    with EVAL_CSV.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if limit is not None:
        rows = rows[:limit]
    return rows


async def _main(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path)
    if not db_path.is_file():
        print(f"数据库不存在：{db_path}")
        return 1
    if not EVAL_CSV.is_file():
        print(f"评测集不存在：{EVAL_CSV}")
        return 1

    results: list[bool] = []
    for row in _read_rows(args.limit):
        results.append(await _run_case(row, db_path, args.user))

    passed = sum(1 for item in results if item)
    failed = sum(1 for item in results if not item)
    print("=" * 70)
    print(f"总计 {len(results)} 条：PASS {passed} / FAIL {failed}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run ChatBI eval set")
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database used by the agent tools",
    )
    parser.add_argument("--user", default="eval", help="session user id")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="only run the first N cases",
    )
    args = parser.parse_args(argv)
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
