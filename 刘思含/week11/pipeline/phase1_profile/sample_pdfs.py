"""Phase 1 stratified sampling.

Selects eight report samples from ``data/file_inventory.json`` with a fixed
seed.  Stratification is two-dimensional inside each
``(batch, report_type)`` pool:

* size terciles (small / large), and
* mtime terciles (old / new).

Coverage is enforced by construction: every required batch, both small
teams (财政局, 审计局/知识产权局) and both report types are represented.
Each slot carries a human-readable ``reason`` explaining why it was chosen.

Usage:
    python -m pipeline.phase1_profile.sample_pdfs \
        --inventory data/file_inventory.json \
        --output data/sample_selection.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("phase1_sample")

DEFAULT_INVENTORY = Path("data/file_inventory.json")
DEFAULT_OUTPUT = Path("data/sample_selection.json")
SEED = 42
SAMPLE_COUNT = 8
BATCH_PATTERN = re.compile(r"-(?P<batch>\d{6})-v\d+\.\d+\.pdf$")


@dataclass(frozen=True)
class Slot:
    """One sampling slot: a fixed stratum plus its size/mtime band."""

    batch: str
    report_type: str
    team: str
    size_band: str  # "small" | "large"
    mtime_band: str  # "old" | "new"


# The eight slots cover: both batches (4 each), both report types (4 each),
# all six teams, and the two smallest teams twice each.
SLOTS: tuple[Slot, ...] = (
    Slot("202606", "渗透测试报告", "财政局团队", "small", "old"),
    Slot("202606", "回归测试报告", "审计局和知识产权局团队", "small", "new"),
    Slot("202606", "渗透测试报告", "国资委、科委和金融监管局团队", "large", "old"),
    Slot(
        "202606",
        "回归测试报告",
        "发改委（含粮食物资储备局）和统计局团队",
        "large",
        "new",
    ),
    Slot("202610", "渗透测试报告", "财政局团队", "small", "new"),
    Slot("202610", "回归测试报告", "审计局和知识产权局团队", "small", "old"),
    Slot("202610", "渗透测试报告", "市场监管局（含药监局）团队", "large", "new"),
    Slot("202610", "回归测试报告", "经信委和商务委团队", "large", "old"),
)


def _batch(name: str) -> str | None:
    """Extract the YYYYMM batch token from a report filename."""
    match = BATCH_PATTERN.search(name)
    return match.group("batch") if match else None


def _band_bounds(values: list[int]) -> tuple[int, int]:
    """Return lower/upper tercile boundaries for a sorted list of values."""
    ordered = sorted(values)
    return ordered[len(ordered) // 3], ordered[(2 * len(ordered)) // 3]


def _in_band(value: int, bounds: tuple[int, int], band: str) -> bool:
    """Check whether a value falls into the requested tercile."""
    low, high = bounds
    return value <= low if band == "small" or band == "old" else value >= high


def _select_for_slot(
    pool: list[dict[str, Any]],
    slot: Slot,
    index: int,
    used: set[str],
    seed: int,
) -> dict[str, Any]:
    """Pick one file for a slot, relaxing bands only if necessary."""
    size_bounds = _band_bounds([entry["size"] for entry in pool])
    mtime_bounds = _band_bounds([entry["mtime_ns"] for entry in pool])
    candidates = [
        entry
        for entry in pool
        if entry["team"] == slot.team and entry["relative_path"] not in used
    ]
    if not candidates:
        raise RuntimeError(f"no candidates for slot {slot}")

    relaxed = False
    selected = [
        entry
        for entry in candidates
        if _in_band(entry["size"], size_bounds, slot.size_band)
        and _in_band(entry["mtime_ns"], mtime_bounds, slot.mtime_band)
    ]
    if not selected:
        relaxed = True
        selected = [
            entry
            for entry in candidates
            if _in_band(entry["size"], size_bounds, slot.size_band)
        ]
    if not selected:
        relaxed = True
        selected = [
            entry
            for entry in candidates
            if _in_band(entry["mtime_ns"], mtime_bounds, slot.mtime_band)
        ]
    if not selected:
        relaxed = True
        selected = candidates

    ordered = sorted(selected, key=lambda entry: entry["relative_path"])
    rng = random.Random(seed + index)
    choice = dict(rng.choice(ordered))
    choice["reason"] = (
        f"{slot.batch}/{slot.report_type}/{slot.team}："
        f"size={slot.size_band} 三分位、mtime={slot.mtime_band} 三分位；"
        f"候选池 {len(candidates)}，命中 {len(selected)}"
        + ("（已放宽分层条件）" if relaxed else "")
    )
    choice["relaxed"] = relaxed
    return choice


def select_samples(files: list[dict[str, Any]], seed: int = SEED) -> dict[str, Any]:
    """Select the eight samples and return selection metadata."""
    annotated: list[dict[str, Any]] = []
    for entry in files:
        batch = _batch(entry["name"])
        if batch is None:
            raise RuntimeError(f"cannot parse batch from filename: {entry['name']}")
        item = dict(entry)
        item["batch"] = batch
        annotated.append(item)

    used: set[str] = set()
    slots: list[dict[str, Any]] = []
    for index, slot in enumerate(SLOTS):
        pool = [
            entry
            for entry in annotated
            if entry["batch"] == slot.batch and entry["report_type"] == slot.report_type
        ]
        choice = _select_for_slot(pool, slot, index, used, seed)
        used.add(choice["relative_path"])
        slots.append(
            {
                "slot_id": index + 1,
                "batch": slot.batch,
                "team": slot.team,
                "report_type": slot.report_type,
                "size_band": slot.size_band,
                "mtime_band": slot.mtime_band,
                "pdf_id": choice["pdf_id"],
                "relative_path": choice["relative_path"],
                "size": choice["size"],
                "mtime_ns": choice["mtime_ns"],
                "reason": choice["reason"],
                "relaxed": choice["relaxed"],
            }
        )

    coverage = {
        "sample_count": len(slots),
        "by_batch": dict(sorted(Counter(item["batch"] for item in slots).items())),
        "by_team": dict(sorted(Counter(item["team"] for item in slots).items())),
        "by_report_type": dict(
            sorted(Counter(item["report_type"] for item in slots).items())
        ),
        "requirements": {
            "batch_202606_min_2": sum(1 for item in slots if item["batch"] == "202606")
            >= 2,
            "batch_202610_min_2": sum(1 for item in slots if item["batch"] == "202610")
            >= 2,
            "team_财政局_min_1": any(item["team"] == "财政局团队" for item in slots),
            "team_审计局_min_1": any(
                item["team"] == "审计局和知识产权局团队" for item in slots
            ),
            "report_type_渗透_min_2": sum(
                1 for item in slots if item["report_type"] == "渗透测试报告"
            )
            >= 2,
            "report_type_回归_min_2": sum(
                1 for item in slots if item["report_type"] == "回归测试报告"
            )
            >= 2,
        },
    }
    if not all(coverage["requirements"].values()):
        raise RuntimeError(f"coverage check failed: {coverage}")

    return {
        "seed": SEED,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample_count": SAMPLE_COUNT,
        "slots": slots,
        "coverage": coverage,
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    selection = select_samples(inventory["files"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    LOGGER.info("selected %s samples", selection["sample_count"])
    for item in selection["slots"]:
        LOGGER.info(
            "[%s] %s | %s | %s | %s",
            item["slot_id"],
            item["batch"],
            item["team"],
            item["report_type"],
            item["relative_path"],
        )
    LOGGER.info("coverage=%s", json.dumps(selection["coverage"], ensure_ascii=False))
    LOGGER.info("written=%s", args.output.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
