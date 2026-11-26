#!/usr/bin/env python3
"""Validate monthly ESG evidence relationships without network access or mutations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit


SOURCE_KINDS = {"official", "company_disclosure", "rating_provider", "industry_media", "other"}
CATEGORIES = {"policy", "rating", "standard", "company", "industry", "peer", "background"}
TOPICS = {"policy", "rating", "standard", "company", "industry_peer"}


class Checker:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, path, message):
        self.errors.append({"path": path, "message": message})

    def warn(self, path, message):
        self.warnings.append({"path": path, "message": message})

    def text(self, value, path):
        if not isinstance(value, str) or not value.strip():
            self.error(path, "Expected a non-empty string.")
            return False
        return True

    def items(self, value, path):
        if not isinstance(value, list):
            self.error(path, "Expected an array.")
            return []
        return value

    def choice(self, value, options, path):
        if not isinstance(value, str) or value not in options:
            self.error(path, "Expected one of: " + ", ".join(sorted(options)))

    def day(self, value, path, nullable=False):
        if value is None and nullable:
            return None
        if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
        self.error(path, "Expected a valid YYYY-MM-DD date" + (" or null." if nullable else "."))
        return None

    def timestamp(self, value, path):
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if "T" in value and parsed.tzinfo is not None:
                    return parsed
            except ValueError:
                pass
        self.error(path, "Expected an ISO timestamp with timezone.")
        return None

    def records(self, value, path, prefix):
        result = {}
        for index, record in enumerate(self.items(value, path)):
            item_path = f"{path}[{index}]"
            if not isinstance(record, dict):
                self.error(item_path, "Expected an object.")
                continue
            record_id = record.get("id")
            if not isinstance(record_id, str) or not re.fullmatch(prefix + r"\d{3,}", record_id):
                self.error(item_path + ".id", f"Expected {prefix} followed by at least three digits.")
                continue
            if record_id in result:
                self.error(item_path + ".id", "Duplicate ID: " + record_id)
                continue
            result[record_id] = record
        return result


def validate(ledger, ledger_path, report_text=None):
    check = Checker()
    if not isinstance(ledger, dict):
        return {"valid": False, "errors": [{"path": "$", "message": "Expected an object."}], "warnings": [], "counts": {}}
    if type(ledger.get("schema_version")) is not int or ledger.get("schema_version") != 1:
        check.error("schema_version", "Expected integer 1.")
    check.text(ledger.get("company"), "company")
    period = ledger.get("period")
    if not isinstance(period, dict):
        check.error("period", "Expected an object with start and exclusive end.")
        period = {}
    start = check.day(period.get("start"), "period.start")
    end = check.day(period.get("end"), "period.end")
    if start and end and start >= end:
        check.error("period", "Start must precede exclusive end.")
    cutoff = check.timestamp(ledger.get("cutoff"), "cutoff")
    sources = check.records(ledger.get("sources"), "sources", "S")
    claims = check.records(ledger.get("claims"), "claims", "C")
    actions = check.records(ledger.get("actions"), "actions", "A")
    source_dates = {}

    for source_id, source in sources.items():
        path = "sources." + source_id
        for field in ("title", "publisher", "url"):
            check.text(source.get(field), path + "." + field)
        try:
            parts = urlsplit(source.get("url", "") if isinstance(source.get("url"), str) else "")
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
                check.error(path + ".url", "Expected an HTTP(S) source URL without embedded credentials.")
        except ValueError:
            check.error(path + ".url", "Invalid URL.")
        if "published_date" not in source:
            check.error(path + ".published_date", "Use a date or explicit null when unavailable.")
        published = check.day(source.get("published_date"), path + ".published_date", nullable=True)
        source_dates[source_id] = published
        if published is None:
            check.warn(path + ".published_date", "Publication date unavailable; month attribution needs original evidence.")
        retrieved = check.timestamp(source.get("retrieved_at"), path + ".retrieved_at")
        if cutoff and retrieved and retrieved > cutoff:
            check.error(path + ".retrieved_at", "Retrieval occurred after the research cutoff.")
        if published and retrieved and published > retrieved.date():
            check.error(path + ".published_date", "Publication date is after retrieval.")
        check.choice(source.get("kind"), SOURCE_KINDS, path + ".kind")
        check.choice(source.get("verification"), {"full_text", "snippet", "unavailable"}, path + ".verification")
        if "local_path" in source:
            if check.text(source["local_path"], path + ".local_path"):
                local_path = Path(source["local_path"])
                if not local_path.is_absolute():
                    local_path = Path(ledger_path).parent / local_path
                if not local_path.is_file():
                    check.error(path + ".local_path", "Saved original file does not exist.")

    for claim_id, claim in claims.items():
        path = "claims." + claim_id
        check.text(claim.get("text"), path + ".text")
        category_value = claim.get("category")
        check.choice(category_value, CATEGORIES, path + ".category")
        category = category_value if isinstance(category_value, str) else ""
        check.choice(claim.get("status"), {"verified", "lead", "disputed"}, path + ".status")
        check.choice(claim.get("entity_scope"), {"company", "parent", "subsidiary", "peer", "general"}, path + ".entity_scope")
        basis = claim.get("date_basis")
        check.choice(basis, {"publication", "event", "effective", "background"}, path + ".date_basis")
        is_background = category == "background"
        if is_background != (basis == "background"):
            check.error(path + ".date_basis", "Background category and date basis must be used together.")
        if "period_date" not in claim:
            check.error(path + ".period_date", "Use an attribution date or explicit null for background/unverified leads.")
        verified = claim.get("status") == "verified"
        period_date = check.day(claim.get("period_date"), path + ".period_date", nullable=is_background or not verified)
        if is_background and claim.get("period_date") is not None:
            check.error(path + ".period_date", "Background must not count as a monthly event; use null.")
        if verified and not is_background and start and end and period_date and not (start <= period_date < end):
            check.error(path + ".period_date", "Verified monthly fact lies outside the half-open reporting period.")
        if cutoff and period_date and period_date > cutoff.date():
            check.error(path + ".period_date", "Attribution date is after research cutoff.")
        for field, expected_basis in (("event_date", "event"), ("effective_date", "effective")):
            if field in claim:
                actual = check.day(claim[field], path + "." + field, nullable=True)
                if actual and period_date and basis == expected_basis and actual != period_date:
                    check.error(path + "." + field, "Attribution date disagrees with the selected date basis.")
        refs = check.items(claim.get("source_refs"), path + ".source_refs")
        if verified and not refs:
            check.error(path + ".source_refs", "Verified facts need original evidence.")
        kinds = set()
        dates = []
        for index, ref in enumerate(refs):
            ref_path = f"{path}.source_refs[{index}]"
            if not isinstance(ref, dict):
                check.error(ref_path, "Expected an object.")
                continue
            source_id = ref.get("source_id")
            if not isinstance(source_id, str) or source_id not in sources:
                check.error(ref_path + ".source_id", "Unknown source ID.")
                continue
            source = sources[source_id]
            if isinstance(source.get("kind"), str):
                kinds.add(source["kind"])
            if source_dates[source_id]:
                dates.append(source_dates[source_id])
            if verified:
                if source.get("verification") != "full_text":
                    check.error(ref_path, "Verified facts cannot rely on snippet or unavailable sources.")
                check.text(ref.get("locator"), ref_path + ".locator")
                check.text(ref.get("excerpt"), ref_path + ".excerpt")
        if verified and basis == "publication" and period_date and dates and period_date not in dates:
            check.error(path + ".period_date", "Publication attribution matches none of the cited source dates.")
        if verified and category in {"policy", "standard"}:
            if "official" not in kinds:
                check.error(path + ".source_refs", "Policy/standard facts require an original official source.")
            check.text(claim.get("applicability"), path + ".applicability")
        if verified and category == "rating":
            if not kinds.intersection({"rating_provider", "company_disclosure"}):
                check.error(path + ".source_refs", "Rating needs provider or attributed company disclosure evidence.")
            metadata = claim.get("rating_metadata")
            if not isinstance(metadata, dict):
                check.error(path + ".rating_metadata", "Expected agency, scale and as_of.")
            else:
                check.text(metadata.get("agency"), path + ".rating_metadata.agency")
                check.text(metadata.get("scale"), path + ".rating_metadata.scale")
                check.day(metadata.get("as_of"), path + ".rating_metadata.as_of")
        if "metrics" in claim:
            for index, metric in enumerate(check.items(claim["metrics"], path + ".metrics")):
                metric_path = f"{path}.metrics[{index}]"
                if not isinstance(metric, dict):
                    check.error(metric_path, "Expected an object.")
                    continue
                raw = metric.get("value")
                try:
                    if not isinstance(raw, str) or not re.fullmatch(r"-?\d+(?:\.\d+)?", raw) or not Decimal(raw).is_finite():
                        raise InvalidOperation
                except InvalidOperation:
                    check.error(metric_path + ".value", "Expected a finite decimal string, not a float; record missing data separately.")
                for field in ("unit", "boundary", "method"):
                    check.text(metric.get(field), metric_path + "." + field)
                metric_start = check.day(metric.get("period_start"), metric_path + ".period_start")
                metric_end = check.day(metric.get("period_end"), metric_path + ".period_end")
                if metric_start and metric_end and metric_start >= metric_end:
                    check.error(metric_path, "Metric start must precede exclusive end.")

    for action_id, action in actions.items():
        path = "actions." + action_id
        for field in ("action", "owner_function", "deliverable", "validation"):
            check.text(action.get(field), path + "." + field)
        check.choice(action.get("priority"), {"high", "medium", "low"}, path + ".priority")
        triggers = check.items(action.get("triggered_by"), path + ".triggered_by")
        if not triggers:
            check.error(path + ".triggered_by", "Actions need a verified trigger fact.")
        for claim_id in triggers:
            if not isinstance(claim_id, str) or claim_id not in claims or claims[claim_id].get("status") != "verified":
                check.error(path + ".triggered_by", "Trigger must identify an existing verified fact.")
        for index, dependency in enumerate(check.items(action.get("dependencies"), path + ".dependencies")):
            check.text(dependency, f"{path}.dependencies[{index}]")

    seen_topics = set()
    for index, coverage in enumerate(check.items(ledger.get("coverage"), "coverage")):
        path = f"coverage[{index}]"
        if not isinstance(coverage, dict):
            check.error(path, "Expected an object.")
            continue
        topic = coverage.get("topic")
        check.choice(topic, TOPICS, path + ".topic")
        if isinstance(topic, str):
            if topic in seen_topics:
                check.error(path + ".topic", "Duplicate coverage topic.")
            seen_topics.add(topic)
        status_value = coverage.get("status")
        check.choice(status_value, {"covered", "partial", "failed", "no_verified_updates"}, path + ".status")
        status = status_value if isinstance(status_value, str) else ""
        queries = check.items(coverage.get("queries"), path + ".queries")
        if not queries:
            check.error(path + ".queries", "Record actual search attempts, including failed attempts.")
        for query_index, query in enumerate(queries):
            check.text(query, f"{path}.queries[{query_index}]")
        checked = check.items(coverage.get("checked_source_ids"), path + ".checked_source_ids")
        for source_id in checked:
            if not isinstance(source_id, str) or source_id not in sources:
                check.error(path + ".checked_source_ids", "Unknown checked source ID.")
        if status in {"covered", "no_verified_updates"} and not checked:
            check.error(path + ".checked_source_ids", "Successful checks need recorded sources.")
        gaps = check.items(coverage.get("gaps"), path + ".gaps")
        for gap_index, gap in enumerate(gaps):
            check.text(gap, f"{path}.gaps[{gap_index}]")
        if status in {"partial", "failed"}:
            if not gaps:
                check.error(path + ".gaps", "Partial/failed coverage must disclose specific limitations.")
            check.warn(path, "Coverage is " + status + "; disclose this in the report.")
        if status == "no_verified_updates":
            relevant = {"industry", "peer"} if topic == "industry_peer" else ({topic} if isinstance(topic, str) else set())
            if any(c.get("status") == "verified" and isinstance(c.get("category"), str) and c["category"] in relevant for c in claims.values()):
                check.error(path + ".status", "No-updates declaration conflicts with verified monthly facts.")
    for missing in sorted(TOPICS - seen_topics):
        check.error("coverage", "Missing topic: " + missing)

    if report_text is not None:
        definitions = dict(re.findall(r"^\s{0,3}\[(C\d{3,})\]:\s*<?(https?://[^\s>]+)>?", report_text, re.MULTILINE))
        citations = set(re.findall(r"\[(C\d{3,})\](?!:)", report_text))
        for claim_id in sorted(citations | set(definitions)):
            claim = claims.get(claim_id)
            if claim is None or claim.get("status") != "verified":
                check.error("report." + claim_id, "Report evidence citation must identify a verified fact.")
                continue
            if claim_id not in definitions:
                check.error("report." + claim_id, "Missing Markdown source link definition.")
                continue
            claim_refs = claim.get("source_refs")
            urls = {
                sources[ref["source_id"]].get("url")
                for ref in (claim_refs if isinstance(claim_refs, list) else [])
                if isinstance(ref, dict) and isinstance(ref.get("source_id"), str) and ref["source_id"] in sources
                and isinstance(sources[ref["source_id"]].get("url"), str)
            }
            if definitions[claim_id] not in urls:
                check.error("report." + claim_id, "Markdown citation URL does not match its recorded evidence.")
        if any(c.get("status") == "verified" for c in claims.values()) and not citations:
            check.error("report", "No fact citations found despite verified evidence.")

    if not claims:
        check.warn("claims", "No facts recorded; deliver a coverage/gap report, not substantive conclusions.")
    return {
        "valid": not check.errors,
        "errors": check.errors,
        "warnings": check.warnings,
        "counts": {"sources": len(sources), "claims": len(claims), "verified_claims": sum(c.get("status") == "verified" for c in claims.values()), "actions": len(actions)},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="UTF-8 evidence JSON")
    parser.add_argument("--report", type=Path, help="Check Markdown [C001] source references")
    parser.add_argument("--output", type=Path, help="Write validation JSON; inputs remain unchanged")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        ledger = json.loads(args.ledger.read_text(encoding="utf-8-sig"))
        report = args.report.read_text(encoding="utf-8-sig") if args.report else None
        result = validate(ledger, args.ledger, report)
        rendered = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [{"path": "input/output", "message": str(exc)}]}, ensure_ascii=False))
        return 2
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
