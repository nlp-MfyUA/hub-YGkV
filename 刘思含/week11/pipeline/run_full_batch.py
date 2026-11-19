"""Run a full-batch pipeline: parse missing reports, then load a batch.

Batches are described by ``data/full_batch.json``. Reports already analysed
under ``data/parsed_output/`` are reused (no re-parse, no re-OCR).
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from pipeline.common.types import ParseResult
from pipeline.phase2_parse.run_parse import (
    DEFAULT_IMAGE_ROOT,
    DEFAULT_OUTPUT,
    DEFAULT_PROFILE,
    DEFAULT_ROOT,
    run_parse,
)
from pipeline.phase3_load.run_load import run_load

LOGGER = logging.getLogger("full_batch")

DEFAULT_BATCH = Path("data/full_batch.json")
DEFAULT_DB = Path("app/db/vuln.db")
DEFAULT_SCHEMA = Path("app/db/schema.sql")
DEFAULT_CONFIG = Path("pipeline/config")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pdf_id(relative_path: str) -> str:
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _batch_result(
    relative_path: str,
    pdf_id: str,
    output_dir: Path,
) -> ParseResult:
    gate_path = output_dir / pdf_id / "quality_gate.json"
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    images_path = output_dir / pdf_id / "image_records.json"
    images = (
        json.loads(images_path.read_text(encoding="utf-8"))
        if images_path.is_file()
        else []
    )
    return ParseResult(
        relative_path=relative_path,
        report_type="retest" if "回归测试报告" in relative_path else "pentest",
        parse_status=gate["parse_status"],
        output_path=str(output_dir / pdf_id),
        record_count=gate["summary"].get("record_count", 0),
        retest_count=gate["summary"].get("retest_count", 0),
        image_count=len(images),
        ocr_success_count=sum(1 for item in images if item.get("ocr_text")),
        linked_count=sum(1 for item in images if item.get("linked_vuln_name")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--batch-index", type=int, required=True)
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
    parser.add_argument("--progress-every", type=int, default=20)
    parser.add_argument(
        "--gc-every",
        type=int,
        default=10,
        help="run gc.collect() after every N reports (default: 10)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    batches = json.loads(args.batch.read_text(encoding="utf-8"))["batches"]
    batch = next(
        (item for item in batches if item["batch_index"] == args.batch_index),
        None,
    )
    if batch is None:
        raise SystemExit(f"batch {args.batch_index} not found in {args.batch}")

    if args.db_path.exists() and args.reset:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(args.db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        print(f"removed {args.db_path}")
    if not args.db_path.exists():
        args.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(args.db_path)
        try:
            conn.executescript(args.schema.read_text(encoding="utf-8"))
            conn.commit()
        finally:
            conn.close()
        print(f"created {args.db_path}")

    files = batch["files"]
    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    status_path = Path(f"data/full_batch_{args.batch_index}_status.json")
    rows: list[dict] = []
    parse_results: list[ParseResult] = []
    shared: dict[str, ParseResult] = {}
    started_all = time.perf_counter()

    for index, item in enumerate(files, 1):
        relative_path = item["relative_path"]
        pdf_id = _pdf_id(relative_path)
        gate_exists = (
            args.output_dir / pdf_id / "quality_gate.json"
        ).is_file()
        row: dict = {
            "relative_path": relative_path,
            "reused": gate_exists,
            "parse_status": None,
            "load_status": None,
            "seconds": None,
            "error": None,
        }
        start = time.perf_counter()
        try:
            if gate_exists:
                result = _batch_result(relative_path, pdf_id, args.output_dir)
                shared[relative_path] = result
            else:
                results = run_parse(
                    [args.root / relative_path],
                    profile,
                    args.config_dir,
                    args.output_dir,
                    args.image_output_root,
                    root=args.root,
                )
                result = results[0]
                del results
            parse_results.append(result)
            row.update(
                {
                    "parse_status": result.parse_status,
                    "record_count": result.record_count,
                    "retest_count": result.retest_count,
                    "image_count": result.image_count,
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            LOGGER.exception("parse failed: %s", relative_path)
            row["error"] = f"{type(exc).__name__}: {exc}"
            row["parse_status"] = "exception"
        row["seconds"] = round(time.perf_counter() - start, 3)
        rows.append(row)

        # Release the per-report parse graph (ParsedDocument holds every page's
        # text and, before extraction, the image bytes) so memory does not pile
        # up across a long batch. pdfplumber's PDF object is already closed by
        # the adapter's ``with`` block; this drops the remaining references.
        result = None
        if index % args.gc_every == 0:
            collected = gc.collect()
            LOGGER.info(
                "MEMORY: processed=%s, gc_collected=%s objects", index, collected
            )
            print(
                f"MEMORY: processed={index}, gc_collected={collected}",
                flush=True,
            )

        if index % args.progress_every == 0 or index == len(files):
            done = len(rows)
            pending = sum(
                1 for item in rows if item["parse_status"] == "pending_review"
            )
            failed = sum(
                1
                for item in rows
                if item["parse_status"] in ("fail", "exception")
            )
            elapsed = time.perf_counter() - started_all
            print(
                f"PROGRESS batch{args.batch_index} {done}/{len(files)} "
                f"elapsed={elapsed/60:.1f}min pending={pending} fail={failed}",
                flush=True,
            )
            _write_json(
                status_path,
                {
                    "generated_at": _now(),
                    "batch_index": args.batch_index,
                    "completed": done,
                    "total": len(files),
                    "rows": rows,
                },
            )

    # Only reports parsed in this batch are loaded again; reports already in
    # the database (e.g. batch 1 when running batch 2) are left untouched.
    to_load = [item for item in parse_results if not _is_loaded(item, args.db_path)]
    print(f"load: {len(to_load)} new of {len(parse_results)} parsed", flush=True)
    load_start = time.perf_counter()
    load_results = run_load(to_load, args.db_path, args.config_dir)
    load_seconds = round(time.perf_counter() - load_start, 3)

    result_by_path = {item.relative_path: item for item in to_load}
    load_by_path = {
        parsed.relative_path: load
        for parsed, load in zip(to_load, load_results)
    }
    for row in rows:
        if row["relative_path"] not in result_by_path:
            continue
        match = load_by_path.get(row["relative_path"])
        if match is not None:
            row["load_status"] = match.status
            row["load_error"] = match.error

    summary = {
        "generated_at": _now(),
        "batch_index": args.batch_index,
        "total_files": len(files),
        "reused": sum(1 for row in rows if row["reused"]),
        "parsed": sum(1 for row in rows if not row["reused"]),
        "parse_status": dict(Counter(row["parse_status"] for row in rows)),
        "load_status": dict(Counter(row["load_status"] for row in rows)),
        "load_seconds": load_seconds,
        "total_seconds": round(time.perf_counter() - started_all, 3),
        "rows": rows,
    }
    _write_json(status_path, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"},
                     ensure_ascii=False))
    return 0


def _is_loaded(result: ParseResult, db_path: Path) -> bool:
    """Return True when the report already exists in the database."""
    if not db_path.is_file():
        return False
    conn = sqlite3.connect(db_path)
    try:
        if result.report_type == "retest":
            row = conn.execute(
                "SELECT 1 FROM v_report WHERE report_name=? AND status='active'",
                (result.relative_path,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM pdf_index WHERE relative_path=? AND load_status"
                " IN ('pass','skipped_no_vulns')",
                (result.relative_path,),
            ).fetchone()
        return row is not None
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
