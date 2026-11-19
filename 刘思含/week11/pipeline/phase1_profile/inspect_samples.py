"""Phase 1 sample inspection.

Reads ``data/sample_selection.json``, inspects each selected PDF with
pdfplumber, writes ``data/sample_inspection.json``, then delegates profile
and notes generation to :mod:`pipeline.phase1_profile.build_profile`.

Usage:
    python -m pipeline.phase1_profile.inspect_samples \
        --selection data/sample_selection.json --root deliverables
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pdfplumber

from pipeline.phase1_profile.constants import (
    FIRST_PAGES_TEXT_LIMIT,
    SCANNED_AVG_CHARS,
    SECTION_PATTERNS,
    SEVERITY_HEADER_KEYWORDS,
    SMALL_IMAGE_HEIGHT,
    SMALL_IMAGE_KB,
    SMALL_IMAGE_WIDTH,
    SUMMARY_PATTERNS,
)

LOGGER = logging.getLogger("phase1_inspect")

DEFAULT_SELECTION = Path("data/sample_selection.json")
DEFAULT_ROOT = Path("deliverables")
DEFAULT_INSPECTION = Path("data/sample_inspection.json")
DEFAULT_NOTES = Path("data/sample_notes.md")
DEFAULT_PROFILE = Path("data/corpus_profile.json")


def _clean(value: Any) -> str:
    """Normalize a table cell or text fragment."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _image_size(image: dict[str, Any]) -> tuple[float, float]:
    """Return image width/height in pixels when available."""
    srcsize = image.get("srcsize")
    if srcsize and len(srcsize) == 2:
        return float(srcsize[0] or 0), float(srcsize[1] or 0)
    return float(image.get("width") or 0), float(image.get("height") or 0)


def _image_kb(image: dict[str, Any], width: float, height: float) -> float:
    """Estimate embedded image size in KB."""
    stream = image.get("stream")
    if stream is not None:
        try:
            return round(len(stream.get_data()) / 1024, 2)
        except Exception:  # stream formats vary by parser
            pass
    bits = float(image.get("bits") or 8)
    return round(width * height * bits / 8 / 1024, 2)


def _image_type(width: float, height: float) -> str:
    """Rough screenshot/chart guess from pixel dimensions."""
    if width <= 0 or height <= 0:
        return "unknown"
    ratio = width / height
    if width >= 600 and 1.2 <= ratio <= 2.5:
        return "screenshot"
    if width >= 300 and 1.0 <= ratio <= 2.0:
        return "chart"
    return "unknown"


def _type_guess(counts: Counter[str], total: int) -> dict[str, Any]:
    """Convert image type counts to counts and ratios."""
    safe_total = total or 1
    return {
        "counts": {
            key: counts.get(key, 0) for key in ("screenshot", "chart", "unknown")
        },
        "screenshot_ratio": round(counts.get("screenshot", 0) / safe_total, 3),
        "chart_ratio": round(counts.get("chart", 0) / safe_total, 3),
        "unknown_ratio": round(counts.get("unknown", 0) / safe_total, 3),
    }


def _size_stats(values: list[float]) -> dict[str, float | None]:
    """Return min/max/avg KB for a list of image sizes."""
    if not values:
        return {"min_kb": None, "max_kb": None, "avg_kb": None}
    return {
        "min_kb": round(min(values), 1),
        "max_kb": round(max(values), 1),
        "avg_kb": round(sum(values) / len(values), 1),
    }


def _section_titles(page_texts: list[str]) -> list[str]:
    """Extract likely section headings from page text."""
    titles: list[str] = []
    seen: set[str] = set()
    for text in page_texts:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate or len(candidate) > 40:
                continue
            if all(char.isdigit() or char in " .、．" for char in candidate):
                continue
            if any(pattern.search(candidate) for pattern in SECTION_PATTERNS):
                if candidate not in seen:
                    seen.add(candidate)
                    titles.append(candidate)
    return titles[:30]


def _summary_hints(page_texts: list[str]) -> tuple[list[str], list[str]]:
    """Return count-like snippets and severity words seen near them."""
    snippets: list[str] = []
    severity: list[str] = []
    seen: set[str] = set()
    for text in page_texts:
        for line in text.splitlines():
            for pattern in SUMMARY_PATTERNS:
                for match in pattern.finditer(line):
                    snippet = line.strip()[:100]
                    if snippet not in seen:
                        seen.add(snippet)
                        snippets.append(snippet)
                    severity.append(match.group(1))
    return snippets[:20], severity


def _severity_from_table(table: list[list[Any]], headers: list[str]) -> list[str]:
    """Collect values from a severity column, if the table has one."""
    column = None
    for index, header in enumerate(headers):
        if any(keyword in header.lower() for keyword in SEVERITY_HEADER_KEYWORDS):
            column = index
            break
    if column is None:
        return []
    values: list[str] = []
    for row in table[1:]:
        if column >= len(row):
            continue
        value = _clean(row[column])
        if value and len(value) <= 12:
            values.append(value)
    return values


def _image_observations(
    records: list[dict[str, Any]], page_count: int
) -> dict[str, Any]:
    """Split raw images into template/small images and evidence images."""
    page_sets: dict[tuple[int, int, float], set[int]] = {}
    for record in records:
        key = (
            round(record["width"]),
            round(record["height"]),
            round(record["kb"], 1),
        )
        page_sets.setdefault(key, set()).add(record["page"])

    template_keys = {
        key
        for key, pages in page_sets.items()
        if len(pages) >= max(3, (page_count + 1) // 2)
    }

    def is_template(record: dict[str, Any]) -> bool:
        key = (
            round(record["width"]),
            round(record["height"]),
            round(record["kb"], 1),
        )
        return key in template_keys

    evidence = [
        record
        for record in records
        if not is_template(record)
        and record["width"] >= SMALL_IMAGE_WIDTH
        and record["height"] >= SMALL_IMAGE_HEIGHT
        and record["kb"] >= SMALL_IMAGE_KB
    ]
    small_count = sum(
        1
        for record in records
        if not is_template(record)
        and (
            record["width"] < SMALL_IMAGE_WIDTH
            or record["height"] < SMALL_IMAGE_HEIGHT
            or record["kb"] < SMALL_IMAGE_KB
        )
    )
    template_count = sum(1 for record in records if is_template(record))

    raw_pages = sorted({record["page"] for record in records})
    evidence_pages = sorted({record["page"] for record in evidence})
    raw_types = Counter(record["type"] for record in records)
    evidence_types = Counter(record["type"] for record in evidence)

    return {
        "image_count": len(records),
        "image_pages": raw_pages,
        "image_page_ratio": round(len(raw_pages) / max(page_count, 1), 3),
        "image_size_stats": _size_stats([record["kb"] for record in records]),
        "image_type_guess": _type_guess(raw_types, len(records)),
        "evidence_image_count": len(evidence),
        "evidence_image_pages": evidence_pages,
        "evidence_image_page_ratio": round(len(evidence_pages) / max(page_count, 1), 3),
        "evidence_image_size_stats": _size_stats([record["kb"] for record in evidence]),
        "evidence_image_type_guess": _type_guess(evidence_types, len(evidence)),
        "template_image_count": template_count,
        "small_image_count": small_count,
        "template_image_keys": [
            {
                "width": key[0],
                "height": key[1],
                "kb": key[2],
                "pages": len(page_sets[key]),
            }
            for key in sorted(template_keys)
        ],
    }


def inspect_sample(item: dict[str, Any], root: Path) -> dict[str, Any]:
    """Inspect one PDF and return its observation dictionary."""
    path = root / item["relative_path"]
    if not path.is_file():
        raise FileNotFoundError(f"sample not found: {path}")

    with pdfplumber.open(path) as pdf:
        pages = pdf.pages
        page_count = len(pages)
        page_texts = [page.extract_text() or "" for page in pages]

        first_three = page_texts[:3]
        first_avg = (
            sum(len(text) for text in first_three) / len(first_three)
            if first_three
            else 0.0
        )
        is_scanned = first_avg < SCANNED_AVG_CHARS

        tables: list[dict[str, Any]] = []
        severity_values: list[str] = []
        image_records: list[dict[str, Any]] = []

        for page_number, page in enumerate(pages, start=1):
            try:
                page_tables = page.extract_tables()
            except Exception as exc:  # malformed pages are recorded, not fatal
                LOGGER.warning(
                    "%s page %s table error: %s",
                    item["relative_path"],
                    page_number,
                    exc,
                )
                page_tables = []
            for table in page_tables:
                if not table or not table[0]:
                    continue
                headers = [_clean(cell) for cell in table[0]]
                tables.append(
                    {
                        "page": page_number,
                        "headers": headers,
                        "row_count": len(table),
                    }
                )
                severity_values.extend(_severity_from_table(table, headers))

            for image in page.images:
                width, height = _image_size(image)
                image_records.append(
                    {
                        "page": page_number,
                        "width": width,
                        "height": height,
                        "kb": _image_kb(image, width, height),
                        "type": _image_type(width, height),
                    }
                )

    hints, hint_severity = _summary_hints(page_texts)
    severity_values.extend(hint_severity)
    observations = _image_observations(image_records, page_count)

    return {
        "slot_id": item["slot_id"],
        "relative_path": item["relative_path"],
        "pdf_id": item["pdf_id"],
        "batch": item["batch"],
        "team": item["team"],
        "report_type": item["report_type"],
        "selection_reason": item["reason"],
        "size_bytes": item["size"],
        "mtime_ns": item["mtime_ns"],
        "page_count": page_count,
        "is_scanned": is_scanned,
        "first_three_pages_avg_chars": round(first_avg, 1),
        "first_pages_text": "\n".join(page_texts[:2])[:FIRST_PAGES_TEXT_LIMIT],
        "tables": tables,
        "table_headers": [
            {"page": table["page"], "headers": table["headers"]} for table in tables
        ],
        "section_titles": _section_titles(page_texts),
        "summary_count_hints": hints,
        "severity_values": sorted(set(severity_values)),
        **observations,
    }


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--inspection", type=Path, default=DEFAULT_INSPECTION)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    args = parser.parse_args(argv)

    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    samples: list[dict[str, Any]] = []
    for item in selection["slots"]:
        LOGGER.info("inspecting slot %s: %s", item["slot_id"], item["relative_path"])
        samples.append(inspect_sample(item, args.root))

    args.inspection.parent.mkdir(parents=True, exist_ok=True)
    args.inspection.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from pipeline.phase1_profile.build_profile import (
        build_profile,
        write_notes,
    )

    profile = build_profile(samples, selection)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_notes(samples, profile, args.notes)

    LOGGER.info("page_count_range=%s", profile["page_count_range"])
    LOGGER.info("is_scanned_ratio=%s", profile["is_scanned_ratio"])
    LOGGER.info("template_groups=%s", len(profile["template_groups"]))
    LOGGER.info("images=%s", profile["image_stats"])
    LOGGER.info("written=%s", args.profile.resolve().as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
