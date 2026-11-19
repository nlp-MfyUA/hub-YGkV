"""Extract images, run OCR and link images to nearby vulnerabilities."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Protocol, Union

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageBlock,
    ImageExtractionResult,
    ImageRecord,
    ParsedDocument,
    RetestRecord,
)

LOGGER = logging.getLogger("phase2.images")

DEFAULT_RULES: dict[str, Any] = {
    "ocr_enabled": True,
    "ocr_engine": "paddleocr",
    "ocr_languages": ["ch", "en"],
    "link_by_page_proximity": True,
    "link_page_window": 1,
    "exclude_small_images": {
        "min_width": 300,
        "min_height": 150,
        "min_kb": 20,
    },
    "image_type_rules": {
        "screenshot": {"min_width": 600, "aspect_ratio_range": [1.2, 2.5]},
        "chart": {"min_width": 300, "aspect_ratio_range": [1.0, 2.0]},
    },
}


class OCREngine(Protocol):
    """OCR engine interface."""

    def recognize(self, image_path: Path, languages: list[str]) -> tuple[str, str]:
        """Return ``(text, confidence_level)``."""
        ...


class PaddleOCREngine:
    """Lazy PaddleOCR wrapper."""

    def __init__(self) -> None:
        self._ocr = None
        self._languages: tuple[str, ...] = ()

    def recognize(self, image_path: Path, languages: list[str]) -> tuple[str, str]:
        """Run PaddleOCR and return text plus confidence level."""
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - import environment
            LOGGER.warning("paddleocr import failed: %s", exc)
            return "", "low"

        if self._ocr is None or tuple(languages) != self._languages:
            self._ocr = PaddleOCR(
                use_angle_cls=True,
                lang=languages[0] if languages else "ch",
                show_log=False,
            )
            self._languages = tuple(languages)
        try:
            result = self._ocr.ocr(str(image_path), cls=True)
        except Exception as exc:  # pragma: no cover - engine/runtime issue
            LOGGER.warning("OCR failed for %s: %s", image_path, exc)
            return "", "low"
        return _parse_paddle_result(result)


_OCR_ENGINE_SINGLETON: PaddleOCREngine | None = None


def get_ocr_engine() -> PaddleOCREngine:
    """Return the process-wide OCR engine.

    ``PaddleOCREngine`` lazily constructs ``PaddleOCR`` on first use, which
    loads the det/rec/cls models. Reusing one instance across reports keeps
    that cost (and the model's memory) paid only once per process.
    """
    global _OCR_ENGINE_SINGLETON
    if _OCR_ENGINE_SINGLETON is None:
        _OCR_ENGINE_SINGLETON = PaddleOCREngine()
    return _OCR_ENGINE_SINGLETON


def _parse_paddle_result(result: Any) -> tuple[str, str]:
    """Parse PaddleOCR output into text and confidence level."""
    texts: list[str] = []
    scores: list[float] = []
    if not result:
        return "", "low"
    for page in result:
        if not page:
            continue
        for item in page:
            if not item or len(item) < 2:
                continue
            payload = item[1]
            if isinstance(payload, (list, tuple)) and payload:
                texts.append(str(payload[0]))
                if len(payload) > 1:
                    try:
                        scores.append(float(payload[1]))
                    except (TypeError, ValueError):
                        pass
    text = "\n".join(texts)
    if not text:
        return "", "low"
    average = sum(scores) / len(scores) if scores else 0.0
    if average >= 0.9:
        confidence = "high"
    elif average >= 0.6:
        confidence = "medium"
    else:
        confidence = "low"
    return text, confidence


def _image_size(block: ImageBlock) -> tuple[float, float]:
    """Return pixel dimensions when available."""
    if block.srcsize:
        return float(block.srcsize[0]), float(block.srcsize[1])
    return 0.0, 0.0


def _image_type(width: float, height: float, rules: dict[str, Any]) -> str:
    """Infer screenshot/chart/unknown from dimensions."""
    if width <= 0 or height <= 0:
        return "unknown"
    ratio = width / height
    type_rules = rules.get("image_type_rules", DEFAULT_RULES["image_type_rules"])
    for name in ("screenshot", "chart"):
        rule = type_rules.get(name)
        if not rule:
            continue
        min_width = rule.get("min_width", 0)
        low, high = rule.get("aspect_ratio_range", [0, 99])
        if width >= min_width and low <= ratio <= high:
            return name
    return "unknown"


def _template_keys(
    images: list[ImageBlock], page_count: int
) -> set[tuple[int, int, int]]:
    """Find repeated header/footer image signatures."""
    pages: dict[tuple[int, int, int], set[int]] = defaultdict(set)
    for image in images:
        width, height = _image_size(image)
        key = (round(width), round(height), round(len(image.image_bytes) / 1024))
        pages[key].add(image.page)
    return {
        key
        for key, page_set in pages.items()
        if len(page_set) >= max(3, (page_count + 1) // 2)
    }


def _is_small(block: ImageBlock, rules: dict[str, Any]) -> bool:
    """Return True for logo/icon-sized images."""
    limits = rules.get("exclude_small_images", {})
    width, height = _image_size(block)
    min_width = limits.get("min_width", 300)
    min_height = limits.get("min_height", 150)
    min_kb = limits.get("min_kb", 20)
    kb = len(block.image_bytes) / 1024
    return width < min_width or height < min_height or kb < min_kb


def _record_name(record: Union[CanonicalVulnRecord, RetestRecord]) -> str:
    """Return the vulnerability name for image linking."""
    if isinstance(record, RetestRecord):
        return record.raw_vuln_name
    return record.vuln_name


def _link_name(
    records: Iterable[Union[CanonicalVulnRecord, RetestRecord]],
    page: int,
    window: int,
) -> str | None:
    """Link an image by page proximity, checking source and evidence pages."""
    candidates: list[
        tuple[int, int, int, Union[CanonicalVulnRecord, RetestRecord]]
    ] = []
    for order, record in enumerate(records):
        if record.source_page is not None:
            diff = abs(record.source_page - page)
            if diff <= window:
                candidates.append((diff, 0, order, record))
        evidence_page = getattr(record, "evidence_page", None)
        if evidence_page is not None:
            diff = abs(evidence_page - page)
            if diff <= window:
                candidates.append((diff, 1, order, record))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return _record_name(candidates[0][3])


def extract_images(
    doc: ParsedDocument,
    records: list[Union[CanonicalVulnRecord, RetestRecord]],
    source_file: str,
    output_image_dir: Path,
    image_rules: dict[str, Any] | None = None,
    ocr_engine: OCREngine | None = None,
    pdf_id: str | None = None,
) -> ImageExtractionResult:
    """Write images to disk, OCR them, and link to nearby records."""
    rules = {**DEFAULT_RULES, **(image_rules or {})}
    output_image_dir = Path(output_image_dir)
    output_image_dir.mkdir(parents=True, exist_ok=True)
    template_keys = _template_keys(doc.images, doc.page_count)
    engine = ocr_engine
    ocr_enabled = bool(rules.get("ocr_enabled", True))
    if ocr_enabled and engine is None:
        engine = get_ocr_engine()
    window = int(rules.get("link_page_window", 1))
    languages = list(rules.get("ocr_languages", ["ch", "en"]))

    image_records: list[ImageRecord] = []
    ocr_success = 0
    linked = 0
    for block in doc.images:
        width, height = _image_size(block)
        key = (round(width), round(height), round(len(block.image_bytes) / 1024))
        if key in template_keys or _is_small(block, rules):
            continue
        filename = f"{block.page}_{block.index_on_page}.png"
        target = output_image_dir / filename
        target.write_bytes(block.image_bytes)
        if ocr_enabled and engine is not None:
            ocr_text, confidence = engine.recognize(target, languages)
        else:
            ocr_text, confidence = "", "low"
        if ocr_text:
            ocr_success += 1
        linked_name = _link_name(records, block.page, window)
        if linked_name:
            linked += 1
        relative_path = f"{pdf_id}/{filename}" if pdf_id else filename
        image_records.append(
            ImageRecord(
                source_file=source_file,
                source_page=block.page,
                image_index=block.index_on_page,
                image_path=relative_path,
                image_type=_image_type(width, height, rules),  # type: ignore[arg-type]
                ocr_text=ocr_text,
                ocr_confidence=confidence,  # type: ignore[arg-type]
                linked_vuln_name=linked_name,
                generated_description=None,
            )
        )

    return ImageExtractionResult(
        image_records=image_records,
        ocr_success_count=ocr_success,
        linked_count=linked,
        unlinked_count=len(image_records) - linked,
    )
