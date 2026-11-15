"""Phase 2 quality gate."""

from __future__ import annotations

from typing import Any, Union

from pipeline.common.types import (
    CanonicalVulnRecord,
    ImageExtractionResult,
    ParsedDocument,
    QualityGateResult,
    RetestRecord,
)

Record = Union[CanonicalVulnRecord, RetestRecord]


def _check(check_id: str, level: str, detail: str) -> dict[str, str]:
    """Build one check record."""
    return {"id": check_id, "level": level, "detail": detail}


def evaluate_quality(
    records: list[Record],
    summary: dict[str, Any],
    image_result: ImageExtractionResult,
    doc: ParsedDocument,
    report_type: str,
    profile: dict[str, Any] | None = None,
) -> QualityGateResult:
    """Evaluate the Phase 2 quality checks and return a status."""
    profile = profile or {}
    checks: list[dict[str, str]] = []
    declared_total = summary.get("declared_total")
    declares_zero = bool(summary.get("declares_zero"))
    record_count = len(records)

    if report_type == "retest":
        if record_count > 0:
            checks.append(_check("non_empty", "pass", f"{record_count} retest records"))
            base_status = "pass"
        else:
            checks.append(_check("non_empty", "fail", "no retest records"))
            base_status = "fail"
    else:
        if record_count > 0:
            checks.append(_check("non_empty", "pass", f"{record_count} records"))
            base_status = "pass"
        elif declares_zero or declared_total == 0:
            checks.append(
                _check(
                    "non_empty",
                    "pass",
                    "0 records; summary declares zero vulnerabilities",
                )
            )
            base_status = "no_vulnerabilities"
        else:
            checks.append(
                _check(
                    "non_empty",
                    "fail",
                    "0 records; summary does not declare zero vulnerabilities",
                )
            )
            base_status = "fail"

    if declared_total is None:
        checks.append(_check("count_cross_check", "warn", "no summary count found"))
        count_status = "warn"
        count_mismatch_warning = False
    else:
        diff = abs(record_count - declared_total)
        ratio = declared_total / record_count if record_count else None
        # Pentest records carry a severity; retest records carry a status
        # instead. Requiring a severity on retest records would block every
        # aggregated retest report.
        if report_type == "retest":
            fields_complete = all(
                getattr(record, "raw_vuln_name", None)
                and getattr(record, "retest_status", None)
                for record in records
            )
        else:
            fields_complete = all(
                getattr(record, "vuln_name", None)
                and getattr(record, "severity_raw", None)
                for record in records
            )
        if diff == 0:
            checks.append(
                _check(
                    "count_cross_check",
                    "pass",
                    f"records={record_count}, declared={declared_total}",
                )
            )
            count_status = "pass"
            count_mismatch_warning = False
        elif record_count == 0 and declared_total > 0:
            checks.append(
                _check(
                    "count_cross_check",
                    "fail",
                    f"records=0, declared={declared_total}",
                )
            )
            count_status = "fail"
            count_mismatch_warning = False
        elif (
            record_count >= 3
            and fields_complete
            and ratio is not None
            and ratio > 2.0
        ):
            checks.append(
                _check(
                    "count_cross_check",
                    "warn",
                    (
                        f"count_mismatch_warning: records={record_count}, "
                        f"declared={declared_total}, ratio={ratio:.2f}"
                    ),
                )
            )
            checks.append(
                _check(
                    "count_mismatch_warning",
                    "warn",
                    (
                        "summary count likely counts interfaces/test items, "
                        f"not titled vulnerabilities (declared={declared_total}, "
                        f"extracted={record_count})"
                    ),
                )
            )
            count_status = "pass"
            count_mismatch_warning = True
        elif declared_total and diff / declared_total <= 0.2:
            checks.append(
                _check(
                    "count_cross_check",
                    "warn",
                    f"records={record_count}, declared={declared_total}",
                )
            )
            count_status = "warn"
            count_mismatch_warning = False
        else:
            checks.append(
                _check(
                    "count_cross_check",
                    "pending_review",
                    f"records={record_count}, declared={declared_total}",
                )
            )
            count_status = "pending_review"
            count_mismatch_warning = False

    image_count = len(image_result.image_records)
    if image_count > 0:
        ocr_ratio = image_result.ocr_success_count / image_count
        checks.append(
            _check(
                "image_ocr_success",
                "pass" if ocr_ratio >= 0.9 else "warn",
                f"{image_result.ocr_success_count}/{image_count} images have OCR text",
            )
        )
        link_ratio = image_result.linked_count / image_count
        checks.append(
            _check(
                "image_link_rate",
                "pass" if link_ratio >= 0.6 else "warn",
                f"{image_result.linked_count}/{image_count} images linked",
            )
        )
        expected_ratio = profile.get("image_stats", {}).get("evidence_image_page_ratio")
        if expected_ratio is not None and doc.page_count:
            actual_ratio = (
                len({record.source_page for record in image_result.image_records})
                / doc.page_count
            )
            deviation = (
                abs(actual_ratio - expected_ratio) / expected_ratio
                if expected_ratio
                else 0
            )
            checks.append(
                _check(
                    "image_extract_consistency",
                    "pass" if deviation <= 0.3 else "warn",
                    f"actual_page_ratio={actual_ratio:.2f}, "
                    f"profile={expected_ratio:.2f}",
                )
            )

    status = base_status
    if count_status == "pending_review" and base_status == "pass":
        status = "pending_review"
    elif count_status == "fail":
        status = "fail"

    return QualityGateResult(
        parse_status=status,  # type: ignore[arg-type]
        checks=checks,
        summary={
            "record_count": record_count if report_type == "pentest" else 0,
            "retest_count": record_count if report_type == "retest" else 0,
            "declared_count": declared_total,
            "extracted_count": record_count,
            "count_mismatch_warning": count_mismatch_warning,
            "image_count": image_count,
            "image_ocr_success": image_result.ocr_success_count,
            "image_linked": image_result.linked_count,
        },
    )
