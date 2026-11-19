"""Phase 0 inventory scanner.

Recursively lists ``deliverables/`` without parsing file contents.  The
resulting JSON is the baseline for H-01 review and for Phase 1 sampling.

Usage:
    python -m pipeline.phase0_inventory.scan_deliverables \
        --root deliverables --output data/file_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("phase0_inventory")

DEFAULT_ROOT = Path("deliverables")
DEFAULT_OUTPUT = Path("data/file_inventory.json")
REPORT_TYPES = ("渗透测试报告", "回归测试报告")
LONG_PATH_LIST_THRESHOLD = 200
LONG_PATH_WARN_THRESHOLD = 260
VERSION_PATTERN = re.compile(r"-v(?P<version>\d+\.\d+)\.pdf$", re.IGNORECASE)
DATE_PATTERN = re.compile(r"-(?P<date>\d{6})-v\d+\.\d+\.pdf$", re.IGNORECASE)


class DeliverablesEmptyError(RuntimeError):
    """Raised when the root is missing or contains no readable PDF."""


def _relative_posix(path: Path, root: Path) -> str:
    """Return the path relative to root using forward slashes."""
    return path.relative_to(root).as_posix()


def _pdf_id(relative_path: str) -> str:
    """Return the stable 16-character identifier used for on-disk images."""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _context(relative_path: str) -> dict[str, str | None]:
    """Derive round, team and report type from a relative path."""
    parts = relative_path.split("/")
    round_name = parts[0] if parts else None
    team = parts[1] if len(parts) > 1 else None
    parent = parts[-2] if len(parts) > 1 else None
    report_type = parent if parent in REPORT_TYPES else None
    return {"round": round_name, "team": team, "report_type": report_type}


def _base_entry(path: Path, root: Path, stat: os.stat_result) -> dict[str, Any]:
    """Build the metadata shared by every file category."""
    relative_path = _relative_posix(path, root)
    return {
        "relative_path": relative_path,
        "path": path.resolve().as_posix(),
        "name": path.name,
        "ext": path.suffix.lower(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _naming_observation(
    files: list[dict[str, Any]], group_counts: dict[str, dict[str, int]]
) -> dict[str, Any]:
    """Summarize filename patterns for H-01 review."""
    versions: Counter[str] = Counter()
    dates: Counter[str] = Counter()
    prefixes: Counter[str] = Counter()
    unmatched: list[str] = []

    for entry in files:
        name = entry["name"]
        version_match = VERSION_PATTERN.search(name)
        if version_match:
            versions[version_match.group("version")] += 1
        else:
            unmatched.append(entry["relative_path"])
        date_match = DATE_PATTERN.search(name)
        if date_match:
            dates[date_match.group("date")] += 1
        prefixes[name[:3]] += 1

    notes: list[str] = []
    if versions:
        notes.append("文件名以 -v<主>.<次>.pdf 结尾，版本号可解析")
    if unmatched:
        notes.append(
            f"发现 {len(unmatched)} 个非标准版本号（如 -v1.pdf / -v1..pdf），"
            "扫描保留原文件名，不做规范化"
        )
    if dates:
        notes.append("文件名含 6 位年月批次标记（YYYYMM）")
    if group_counts.get("by_round"):
        notes.append(
            "按轮次统计："
            + "，".join(
                f"{key}={value}"
                for key, value in sorted(group_counts["by_round"].items())
            )
        )
    if group_counts.get("by_report_type"):
        notes.append(
            "按报告类型统计："
            + "，".join(
                f"{key}={value}"
                for key, value in sorted(group_counts["by_report_type"].items())
            )
        )

    return {
        "pattern": "<区域前缀><团队><系统名><报告类型>-<YYYYMM>-v<主.次>.pdf",
        "common_prefixes": dict(sorted(prefixes.items())),
        "version_tokens": dict(sorted(versions.items())),
        "date_tokens": dict(sorted(dates.items())),
        "unmatched_version_pattern_count": len(unmatched),
        "unmatched_version_pattern_samples": unmatched[:10],
        "group_counts": group_counts,
        "notes": notes,
    }


def scan_deliverables(
    root: Path, allowed_exts: tuple[str, ...] = (".pdf",)
) -> dict[str, Any]:
    """Recursively scan *root* and return an inventory dictionary.

    Only metadata is read; file contents are never parsed.  Files are
    classified into three disjoint sets: readable PDFs, non-PDF files, and
    zero-byte files (regardless of extension).
    """
    root = Path(root)
    if not root.is_dir():
        raise DeliverablesEmptyError(f"deliverables root not found: {root}")

    allowed = {extension.lower() for extension in allowed_exts}
    pdf_files: list[dict[str, Any]] = []
    non_pdf_files: list[dict[str, Any]] = []
    zero_byte_files: list[dict[str, Any]] = []
    unreadable_files: list[dict[str, Any]] = []
    total_pdf_bytes = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
            readable = os.access(path, os.R_OK)
        except OSError as exc:
            unreadable_files.append(
                {
                    "relative_path": _relative_posix(path, root),
                    "path": path.resolve().as_posix(),
                    "error": str(exc),
                }
            )
            continue

        entry = _base_entry(path, root, stat)
        if stat.st_size == 0:
            zero_byte_files.append(entry)
        elif not readable:
            unreadable_files.append(entry)
        elif entry["ext"] in allowed:
            entry["pdf_id"] = _pdf_id(entry["relative_path"])
            entry.update(_context(entry["relative_path"]))
            pdf_files.append(entry)
            total_pdf_bytes += stat.st_size
        else:
            non_pdf_files.append(entry)

    if not pdf_files:
        raise DeliverablesEmptyError(f"no readable PDF found under: {root}")

    by_round: Counter[str] = Counter()
    by_team: Counter[str] = Counter()
    by_report_type: Counter[str] = Counter()
    for entry in pdf_files:
        if entry["round"]:
            by_round[entry["round"]] += 1
        if entry["team"]:
            by_team[entry["team"]] += 1
        if entry["report_type"]:
            by_report_type[entry["report_type"]] += 1
    group_counts = {
        "by_round": dict(sorted(by_round.items())),
        "by_team": dict(sorted(by_team.items())),
        "by_report_type": dict(sorted(by_report_type.items())),
    }

    lengths = sorted(
        (len(entry["relative_path"]), entry["relative_path"]) for entry in pdf_files
    )
    path_length_max = lengths[-1][0]
    long_paths_over_200 = [
        {
            "relative_path": relative_path,
            "length": length,
            "pdf_id": _pdf_id(relative_path),
        }
        for length, relative_path in reversed(lengths)
        if length > LONG_PATH_LIST_THRESHOLD
    ]
    absolute_root = root.resolve()
    absolute_path_length_max = max(
        len((absolute_root / entry["relative_path"]).as_posix()) for entry in pdf_files
    )
    long_path_warning = (
        "Phase 2 必须使用 pdf_id 落盘"
        if path_length_max > LONG_PATH_WARN_THRESHOLD
        else None
    )

    return {
        "root": absolute_root.as_posix(),
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "allowed_exts": list(allowed_exts),
        "pdf_count": len(pdf_files),
        "non_pdf_count": len(non_pdf_files),
        "zero_byte_count": len(zero_byte_files),
        "unreadable_count": len(unreadable_files),
        "total_bytes": total_pdf_bytes,
        "path_length_max": path_length_max,
        "absolute_path_length_max": absolute_path_length_max,
        "long_paths_over_200": long_paths_over_200,
        "long_path_warning": long_path_warning,
        "files": pdf_files,
        "non_pdf_files": non_pdf_files,
        "zero_byte_files": zero_byte_files,
        "unreadable_files": unreadable_files,
        "naming_observation": _naming_observation(pdf_files, group_counts),
        "inventory_notes": None,
    }


def write_inventory(inventory: dict[str, Any], output_path: Path) -> None:
    """Write the inventory as UTF-8 JSON with a trailing newline."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(inventory, ensure_ascii=False, indent=2)
    output_path.write_text(payload + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        inventory = scan_deliverables(args.root)
    except DeliverablesEmptyError as exc:
        LOGGER.error("inventory failed: %s", exc)
        return 1

    write_inventory(inventory, args.output)
    LOGGER.info("pdf_count=%s", inventory["pdf_count"])
    LOGGER.info("total_bytes=%s", inventory["total_bytes"])
    LOGGER.info("non_pdf_count=%s", inventory["non_pdf_count"])
    LOGGER.info("zero_byte_files=%s", inventory["zero_byte_count"])
    LOGGER.info("path_length_max=%s", inventory["path_length_max"])
    if inventory["long_path_warning"]:
        LOGGER.warning("long_path_warning=%s", inventory["long_path_warning"])
    if inventory["long_paths_over_200"]:
        LOGGER.info("long_paths_over_200:")
        for item in inventory["long_paths_over_200"]:
            LOGGER.info("  %s (%s)", item["relative_path"], item["length"])
    LOGGER.info(
        "naming_observation=%s",
        json.dumps(inventory["naming_observation"], ensure_ascii=False),
    )
    LOGGER.info("written=%s", args.output.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
