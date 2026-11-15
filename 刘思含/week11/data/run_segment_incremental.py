"""Run one batch segment with per-report parse-then-load.

Why this exists: ``run_full_batch.py`` parses the whole segment first and only
then loads, so an OOM during parsing loses every load of that segment (that is
what happened to batch 2a: 51 gates parsed, 0 rows loaded).

This driver keeps the same reuse semantics (a report that already has
``quality_gate.json`` is not re-parsed) but loads each report immediately after
its parse finishes, so progress is durable per report.

Usage:
    python -X utf8 data/run_segment_incremental.py data/full_batch_2a1.json
"""

from __future__ import annotations

import gc
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from pipeline.phase2_parse.run_parse import run_parse  # noqa: E402
from pipeline.phase3_load.run_load import run_load  # noqa: E402
from pipeline.run_full_batch import ParseResult  # noqa: E402

DB_PATH = ROOT_DIR / "app" / "db" / "vuln.db"
CONFIG_DIR = ROOT_DIR / "pipeline" / "config"
OUTPUT_DIR = ROOT_DIR / "data" / "parsed_output"
IMAGE_ROOT = ROOT_DIR / "data" / "images"
PROFILE_PATH = ROOT_DIR / "data" / "corpus_profile.json"
DELIVERABLES = ROOT_DIR / "deliverables"

LOGGER = logging.getLogger("segment")


def _result_from_gate(relative_path: str, pdf_id: str) -> ParseResult:
    out = OUTPUT_DIR / pdf_id
    gate = json.loads((out / "quality_gate.json").read_text(encoding="utf-8"))
    images_path = out / "image_records.json"
    images = (
        json.loads(images_path.read_text(encoding="utf-8"))
        if images_path.is_file()
        else []
    )
    return ParseResult(
        relative_path=relative_path,
        report_type="retest" if "回归测试报告" in relative_path else "pentest",
        parse_status=gate["parse_status"],
        output_path=str(out),
        record_count=gate["summary"].get("record_count", 0),
        retest_count=gate["summary"].get("retest_count", 0),
        image_count=len(images),
        ocr_success_count=sum(1 for item in images if item.get("ocr_text")),
        linked_count=sum(1 for item in images if item.get("linked_vuln_name")),
    )


def _already_loaded(conn: sqlite3.Connection, result: ParseResult) -> bool:
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


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    batch_path = Path(argv[1])
    files = json.loads(batch_path.read_text(encoding="utf-8"))["batches"][0]["files"]
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    rows: list[dict] = []
    started = time.perf_counter()

    for index, item in enumerate(files, 1):
        rel = item["relative_path"]
        pdf_id = __import__("hashlib").sha256(rel.encode()).hexdigest()[:16]
        row: dict = {"relative_path": rel, "pdf_id": pdf_id, "reused": False}
        t0 = time.perf_counter()
        try:
            gate_path = OUTPUT_DIR / pdf_id / "quality_gate.json"
            if gate_path.is_file():
                row["reused"] = True
                result = _result_from_gate(rel, pdf_id)
            else:
                result = run_parse(
                    [DELIVERABLES / rel],
                    profile,
                    CONFIG_DIR,
                    OUTPUT_DIR,
                    IMAGE_ROOT,
                    root=DELIVERABLES,
                )[0]
            row["parse_status"] = result.parse_status

            conn = sqlite3.connect(DB_PATH)
            try:
                if _already_loaded(conn, result):
                    row["load_status"] = "already"
                else:
                    lr = run_load([result], DB_PATH, CONFIG_DIR)[0]
                    row["load_status"] = lr.status
                    row["inserted"] = lr.inserted
                    row["error"] = lr.error
            finally:
                conn.close()
        except BaseException as exc:  # noqa: BLE001 - keep the segment going
            LOGGER.exception("report failed: %s", rel)
            row["parse_status"] = "exception"
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["seconds"] = round(time.perf_counter() - t0, 2)
        rows.append(row)
        print("ROW", json.dumps(row, ensure_ascii=False), flush=True)
        result = None
        if index % 5 == 0:
            gc.collect()
            print(f"MEMORY: processed={index}, gc done", flush=True)

    summary = {
        "segment": batch_path.stem,
        "total": len(files),
        "reused": sum(1 for r in rows if r["reused"]),
        "parse_status": {},
        "load_status": {},
        "seconds": round(time.perf_counter() - started, 1),
        "rows": rows,
    }
    for r in rows:
        summary["parse_status"][r.get("parse_status")] = (
            summary["parse_status"].get(r.get("parse_status"), 0) + 1
        )
        summary["load_status"][r.get("load_status")] = (
            summary["load_status"].get(r.get("load_status"), 0) + 1
        )
    out = ROOT_DIR / "data" / f"{batch_path.stem}_{time.strftime('%Y%m%dT%H%M%S')}_status.json"
    out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # 保留历史入口：同时写一份不带时间戳的副本（后者覆盖前者）
    (ROOT_DIR / "data" / f"{batch_path.stem}_status.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("SUMMARY", json.dumps({k: v for k, v in summary.items() if k != "rows"},
                                ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
