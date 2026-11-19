"""Phase 2 entry point: PDF -> text blocks -> records -> quality gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageExtractionResult,
    ParsedDocument,
    ParseResult,
    RetestRecord,
    TextBlock,
)
from pipeline.phase2_parse.adapters.pdfplumber_adapter import PdfplumberAdapter
from pipeline.phase2_parse.field_extractor import extract_records
from pipeline.phase2_parse.image_extractor import extract_images
from pipeline.phase2_parse.quality_gate import evaluate_quality
from pipeline.phase2_parse.summary_locator import locate_summary
from pipeline.phase2_parse.text_block_locator import locate_text_blocks

LOGGER = logging.getLogger("phase2.run")

DEFAULT_PROFILE = Path("data/corpus_profile.json")
DEFAULT_OUTPUT = Path("data/parsed_output")
DEFAULT_IMAGE_ROOT = Path("data/images")
DEFAULT_ROOT = Path("deliverables")


def _pdf_id(relative_path: str) -> str:
    """Return the stable 16-character report identifier."""
    return hashlib.sha256(relative_path.encode("utf-8")).hexdigest()[:16]


def _report_type(name: str) -> str:
    """Infer report type from the path/name."""
    return "retest" if "回归测试报告" in name else "pentest"


def _relative_path(pdf_path: Path, root: Path) -> str:
    """Return a POSIX path relative to the deliverables root when possible."""
    try:
        return pdf_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return pdf_path.name


def _write_json(path: Path, payload: Any) -> None:
    """Write UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _doc_payload(doc: ParsedDocument) -> dict[str, Any]:
    """Serialize ParsedDocument without raw image bytes."""
    return {
        "source_file": doc.source_file,
        "page_count": doc.page_count,
        "text_blocks": [
            {"page": page.page, "text": page.text} for page in doc.text_blocks
        ],
        "tables": [
            {
                "page": table.page,
                "headers": table.headers,
                "rows": table.rows,
            }
            for table in doc.tables
        ],
        "images": [
            {
                "page": image.page,
                "index_on_page": image.index_on_page,
                "srcsize": image.srcsize,
                "bbox": image.bbox,
                "ext": image.ext,
                "size_bytes": len(image.image_bytes),
            }
            for image in doc.images
        ],
        "metadata": doc.metadata,
    }


def _block_payload(block: TextBlock) -> dict[str, Any]:
    """Serialize a TextBlock."""
    return asdict(block)


def _record_payload(
    record: CanonicalVulnRecord | RetestRecord,
) -> dict[str, Any]:
    """Serialize a canonical/retest record."""
    return record.to_dict()


def run_parse(
    pdf_paths: list[Path],
    profile: dict[str, Any],
    config_dir: Path,
    output_dir: Path,
    image_output_root: Path,
    force_adapter: str | None = None,
    root: Path = DEFAULT_ROOT,
) -> list[ParseResult]:
    """Run the Phase 2 pipeline for each PDF and write intermediate files."""
    del force_adapter  # pdfplumber is the only adapter in Phase 2 MVP
    results: list[ParseResult] = []
    adapter = PdfplumberAdapter()
    for pdf_path in pdf_paths:
        relative_path = _relative_path(Path(pdf_path), root)
        report_type = _report_type(relative_path)
        pdf_id = _pdf_id(relative_path)
        report_dir = Path(output_dir) / pdf_id
        report_dir.mkdir(parents=True, exist_ok=True)

        doc = adapter.parse(Path(pdf_path))
        _write_json(report_dir / "raw_parsed.json", _doc_payload(doc))

        blocks = locate_text_blocks(doc, report_type)
        _write_json(
            report_dir / "located_text_blocks.json",
            [_block_payload(block) for block in blocks],
        )

        page_texts = [page.text for page in doc.text_blocks]
        summary = locate_summary(page_texts)
        records = extract_records(blocks, relative_path)
        canonical = [
            record for record in records if isinstance(record, CanonicalVulnRecord)
        ]
        retests = [record for record in records if isinstance(record, RetestRecord)]
        _write_json(
            report_dir / "canonical_records.json",
            [_record_payload(record) for record in canonical],
        )
        _write_json(
            report_dir / "retest_records.json",
            [_record_payload(record) for record in retests],
        )

        image_result: ImageExtractionResult = extract_images(
            doc,
            records,
            relative_path,
            Path(image_output_root) / pdf_id,
            image_rules=profile.get("image_strategy", {}),
            pdf_id=pdf_id,
        )
        _write_json(
            report_dir / "image_records.json",
            [record.to_dict() for record in image_result.image_records],
        )

        quality = evaluate_quality(
            records,
            summary,
            image_result,
            doc,
            report_type,
            profile,
        )
        _write_json(
            report_dir / "quality_gate.json",
            {
                "parse_status": quality.parse_status,
                "checks": quality.checks,
                "summary": quality.summary,
            },
        )

        results.append(
            ParseResult(
                relative_path=relative_path,
                report_type=report_type,  # type: ignore[arg-type]
                parse_status=quality.parse_status,
                output_path=report_dir.as_posix(),
                record_count=len(canonical),
                retest_count=len(retests),
                image_count=len(image_result.image_records),
                ocr_success_count=image_result.ocr_success_count,
                linked_count=image_result.linked_count,
            )
        )
        LOGGER.info(
            "%s -> %s (records=%s, retests=%s, images=%s)",
            relative_path,
            quality.parse_status,
            len(canonical),
            len(retests),
            len(image_result.image_records),
        )
    return results


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        type=Path,
        action="append",
        required=True,
        help="PDF file to parse (repeatable)",
    )
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--config-dir", type=Path, default=Path("pipeline/config"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image-output-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    files = [
        path if path.is_absolute() or path.exists() else args.root / path
        for path in args.file
    ]
    results = run_parse(
        files,
        profile,
        args.config_dir,
        args.output_dir,
        args.image_output_root,
        root=args.root,
    )
    for result in results:
        LOGGER.info(
            "RESULT %s status=%s records=%s retests=%s images=%s ocr_ok=%s linked=%s",
            result.relative_path,
            result.parse_status,
            result.record_count,
            result.retest_count,
            result.image_count,
            result.ocr_success_count,
            result.linked_count,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
