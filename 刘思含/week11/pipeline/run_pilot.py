"""Run a pilot batch through Phase 2 (parse) and Phase 3 (load).

The pilot database is separate from ``app/db/vuln.db`` and
``app/db/vuln_test_agent.db``. Progress is written after every report so an
interrupted run can be inspected.
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pipeline.phase2_parse.run_parse import (
    DEFAULT_IMAGE_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_PROFILE,
    DEFAULT_ROOT,
    run_parse,
)
from pipeline.phase3_load.run_load import _report_type, run_load

LOGGER = logging.getLogger("pilot")

DEFAULT_BATCH = Path("data/pilot_batch.json")
DEFAULT_DB = Path("app/db/vuln_pilot.db")
DEFAULT_SCHEMA = Path("app/db/schema.sql")
DEFAULT_CONFIG = Path("pipeline/config")
STATUS_PATH = Path("data/pilot_run_status.json")
REPORT_PATH = Path("data/pilot_run_report.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _quality_summary(output_path: str | None) -> dict | None:
    if not output_path:
        return None
    path = Path(output_path) / "quality_gate.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    checks = [
        check
        for check in data.get("checks", [])
        if check.get("level") != "pass"
    ]
    return {
        "parse_status": data.get("parse_status"),
        "non_pass_checks": checks,
        "summary": data.get("summary"),
    }


def _db_stats(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        tables = (
            "v_report",
            "v_vulnerability",
            "v_retest_result",
            "v_image_evidence",
        )
        total = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        active = {
            table: conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE status='active'"
            ).fetchone()[0]
            for table in tables
        }
        fts_docsize = conn.execute(
            "SELECT COUNT(*) FROM v_image_evidence_fts_docsize"
        ).fetchone()[0]
        return {
            "total": total,
            "active": active,
            "fts_docsize": fts_docsize,
            "fts_consistent": active["v_image_evidence"] == fts_docsize,
        }
    finally:
        conn.close()


def _init_db(db_path: Path, schema_path: Path, reset: bool) -> None:
    if db_path.exists():
        if not reset:
            raise SystemExit(
                f"{db_path} already exists; pass --reset to recreate it"
            )
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--image-output-root", type=Path, default=DEFAULT_IMAGE_ROOT
    )
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    files = [item["relative_path"] for item in batch["files"]]
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    _init_db(args.db_path, args.schema, args.reset)

    status_rows: list[dict] = []
    parse_results = []
    parse_failures: list[dict] = []
    run_start = time.perf_counter()

    for index, relative_path in enumerate(files, 1):
        pdf_path = args.root / relative_path
        print(f"[{index}/{len(files)}] PARSE {relative_path}", flush=True)
        started = time.perf_counter()
        row = {
            "relative_path": relative_path,
            "parse_status": "exception",
            "load_status": None,
            "record_count": None,
            "retest_count": None,
            "image_count": None,
            "parse_seconds": None,
            "error": None,
        }
        try:
            if not pdf_path.is_file():
                raise FileNotFoundError(str(pdf_path))
            results = run_parse(
                [pdf_path],
                profile,
                args.config_dir,
                args.output_dir,
                args.image_output_root,
                root=args.root,
            )
            if len(results) != 1:
                raise RuntimeError(f"expected 1 ParseResult, got {len(results)}")
            result = results[0]
            parse_results.append(result)
            row.update(
                {
                    "parse_status": result.parse_status,
                    "record_count": result.record_count,
                    "retest_count": result.retest_count,
                    "image_count": result.image_count,
                    "output_path": result.output_path,
                }
            )
            if result.parse_status == "pending_review":
                row["quality_gate"] = _quality_summary(result.output_path)
            if result.parse_status in ("pending_review", "fail"):
                parse_failures.append(
                    {
                        "relative_path": relative_path,
                        "parse_status": result.parse_status,
                        "quality_gate": _quality_summary(result.output_path),
                    }
                )
        except Exception as exc:  # noqa: BLE001 - pilot should keep going
            row["error"] = f"{type(exc).__name__}: {exc}"
            parse_failures.append(
                {
                    "relative_path": relative_path,
                    "parse_status": "exception",
                    "error": row["error"],
                }
            )
        row["parse_seconds"] = round(time.perf_counter() - started, 3)
        status_rows.append(row)
        _write_json(
            STATUS_PATH,
            {
                "generated_at": _now(),
                "db_path": str(args.db_path),
                "completed": len(status_rows),
                "total": len(files),
                "rows": status_rows,
            },
        )
        print(
            f"  -> {row['parse_status']} records={row['record_count']} "
            f"retests={row['retest_count']} images={row['image_count']} "
            f"{row['parse_seconds']}s",
            flush=True,
        )

    load_started = time.perf_counter()
    load_error = None
    load_results = []
    try:
        load_results = run_load(parse_results, args.db_path, args.config_dir)
    except Exception as exc:  # noqa: BLE001
        load_error = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("pilot load failed")
    load_seconds = round(time.perf_counter() - load_started, 3)

    ordered_parse = [
        result
        for result in parse_results
        if _report_type(result.relative_path) == "pentest"
    ] + [
        result
        for result in parse_results
        if _report_type(result.relative_path) == "retest"
    ]
    by_path = {row["relative_path"]: row for row in status_rows}
    for batch_result, load in zip(ordered_parse, load_results):
        row = by_path.get(batch_result.relative_path)
        if row is None:
            continue
        row["load_status"] = load.status
        row["load_error"] = load.error
        row["report_id"] = load.report_id
        row["inserted"] = load.inserted
        row["updated"] = load.updated
        row["superseded"] = load.superseded

    total_seconds = round(time.perf_counter() - run_start, 3)
    db_stats = _db_stats(args.db_path)
    pending = [
        row for row in status_rows if row["parse_status"] == "pending_review"
    ]
    failures = [
        row
        for row in status_rows
        if row["parse_status"] in ("fail", "exception")
        or row["load_status"] == "fail"
    ]
    report = {
        "generated_at": _now(),
        "batch": str(args.batch),
        "db_path": str(args.db_path),
        "total_files": len(files),
        "total_seconds": total_seconds,
        "parse_seconds": round(
            sum(row["parse_seconds"] or 0 for row in status_rows), 3
        ),
        "load_seconds": load_seconds,
        "average_seconds_per_file": round(total_seconds / len(files), 3),
        "load_error": load_error,
        "coverage": batch.get("coverage"),
        "selection": [
            {
                "relative_path": item["relative_path"],
                "category": item.get("category"),
                "report_type": item.get("report_type"),
                "round": item.get("round"),
                "team": item.get("team"),
            }
            for item in batch["files"]
        ],
        "db_stats": db_stats,
        "files": status_rows,
        "pending_review": pending,
        "failures": failures,
        "parse_failures": parse_failures,
    }
    _write_json(REPORT_PATH, report)

    print("=" * 70)
    print(f"pilot files: {len(files)}")
    print(f"total: {total_seconds}s (parse {report['parse_seconds']}s, load {load_seconds}s)")
    print(f"average per file: {report['average_seconds_per_file']}s")
    print(f"db counts (active): {db_stats['active']}")
    print(f"fts consistent: {db_stats['fts_consistent']} ({db_stats['fts_docsize']})")
    print(f"pending_review: {len(pending)}")
    print(f"failures: {len(failures)}")
    for item in pending:
        print(f"  PENDING {item['relative_path']}")
        print(f"    quality_gate: {json.dumps(item.get('quality_gate'), ensure_ascii=False)}")
    for item in failures:
        print(f"  FAILURE {item['relative_path']} parse={item['parse_status']} load={item['load_status']} error={item.get('load_error') or item.get('error')}")
    return 0 if not load_error else 1


if __name__ == "__main__":
    raise SystemExit(main())
