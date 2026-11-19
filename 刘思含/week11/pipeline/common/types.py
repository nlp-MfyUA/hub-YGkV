"""Shared data structures for the ChatBI-Vuln pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


@dataclass(frozen=True, kw_only=True)
class CanonicalVulnRecord:
    """A single vulnerability extracted from a pentest report."""

    vuln_name: str
    severity_raw: str
    source_file: str
    source_page: Optional[int]
    instance_index: int = 1
    type_raw: Optional[str]
    cvss_score: Optional[float]
    component: Optional[str]
    cwe_id: Optional[str]
    description_snippet: Optional[str]
    extraction_method: Literal["table_row", "kv_block", "text_block"]
    confidence: Literal["high", "medium", "low"]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class ImageRecord:
    """A single image extracted from a report, with OCR and linking."""

    source_file: str
    source_page: int
    image_index: int
    image_path: str
    image_type: Literal["screenshot", "chart", "unknown"]
    ocr_text: str
    ocr_confidence: Literal["high", "medium", "low"]
    linked_vuln_name: Optional[str]
    generated_description: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass(frozen=True)
class RetestRecord:
    """A retest result pointing at a pentest vulnerability."""

    retest_report_path: str
    raw_vuln_name: str
    component: Optional[str]
    retest_status_raw: str
    retest_status: Literal["fixed", "unfixed", "partial", "not_reproducible", "unknown"]
    retest_date: Optional[str]
    evidence_snippet: Optional[str]
    source_page: Optional[int]
    instance_index: int = 1
    evidence_page: Optional[int] = None
    parent_vuln_name: Optional[str] = (
        None  # Extractor 预填 raw_vuln_name；Phase 3 匹配成功覆盖为父漏洞名
    )
    match_confidence: Literal["exact", "fuzzy", "none"] = "none"

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class TableBlock:
    """A table detected by the adapter."""

    page: int
    rows: list[list[str]] = field(default_factory=list)

    @property
    def headers(self) -> list[str]:
        """Return the first row as headers."""
        return self.rows[0] if self.rows else []


@dataclass
class PageText:
    """Raw text of one page."""

    page: int
    text: str
    lines: list[str] = field(default_factory=list)


@dataclass
class ImageBlock:
    """An image extracted by the adapter."""

    page: int
    index_on_page: int
    image_bytes: bytes
    ext: str
    bbox: Optional[tuple[float, float, float, float]] = None
    srcsize: Optional[tuple[int, int]] = None


@dataclass
class ParsedDocument:
    """Adapter output consumed by the locator/extractor/image modules."""

    source_file: str
    page_count: int
    text_blocks: list[PageText] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    images: list[ImageBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TextBlock:
    """One candidate vulnerability/retest block."""

    report_type: Literal["pentest", "retest"]
    raw_title: str
    title: str
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)
    status_text: Optional[str] = None
    retest_date: Optional[str] = None
    status_page: Optional[int] = None
    format: Literal["text_block", "kv_block", "pattern_a"] = "text_block"


@dataclass
class ImageExtractionResult:
    """Result returned by the image extractor."""

    image_records: list[ImageRecord] = field(default_factory=list)
    ocr_success_count: int = 0
    linked_count: int = 0
    unlinked_count: int = 0


@dataclass
class QualityGateResult:
    """Result returned by the quality gate."""

    parse_status: Literal["pass", "pending_review", "fail", "no_vulnerabilities"]
    checks: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """Per-file result of the Phase 2 pipeline."""

    relative_path: str
    report_type: Literal["pentest", "retest"]
    parse_status: str
    output_path: str
    record_count: int
    retest_count: int
    image_count: int
    ocr_success_count: int
    linked_count: int


@dataclass
class LoadResult:
    """Result of loading one report into SQLite."""

    report_id: Optional[int]
    inserted: int
    updated: int
    superseded: int
    status: Literal["pass", "skipped_no_vulns", "skipped_pending_review", "fail"]
    error: Optional[str] = None


@dataclass
class RetestLoadResult:
    """Result of loading one retest report into SQLite."""

    report_id: Optional[int]
    inserted: int
    updated: int
    superseded: int
    matched: int
    unmatched: int
    status: Literal["pass", "fail"] = "pass"
    error: Optional[str] = None


@dataclass
class ImageLoadResult:
    """Result of loading one report's images into SQLite."""

    inserted: int
    updated: int
    superseded: int
    status: Literal["pass", "fail"] = "pass"
    error: Optional[str] = None
