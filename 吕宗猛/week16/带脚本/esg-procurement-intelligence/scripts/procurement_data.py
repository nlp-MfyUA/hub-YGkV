#!/usr/bin/env python3
"""Deterministic evidence normalization, stratified statistics and one-shot monitoring.

Python 3.10+, standard library; no network access or notification credentials.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from urllib.parse import urlparse


SCHEMA_VERSION = 1
CATEGORIES = {
    "service": "专业服务", "software_data": "软件与数据",
    "equipment_engineering": "设备与工程", "mixed": "混合项目",
}
STATUSES = {"tender", "candidate", "awarded", "contracted", "terminated",
            "award_revoked", "retender", "expired", "unknown"}
KINDS = {"budget", "ceiling", "candidate_quote", "award", "contract",
         "unit_price", "framework_cap"}
UNITS = {"元": Decimal(1), "万元": Decimal(10000), "亿元": Decimal(100000000),
         "base": Decimal(1), "thousand": Decimal(1000), "million": Decimal(1000000),
         "billion": Decimal(1000000000)}
TAXES = {"included", "excluded", "unspecified"}
SCOPES = {"lot_total", "project_total", "unit_price", "framework", "unknown"}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
RAW_MONEY = re.compile(r"^(?P<prefix>人民币|CNY|RMB|￥|¥)?\s*(?P<value>" + NUMBER +
                       r")\s*(?P<unit>亿元|万元|元|base|thousand|million|billion)$")
OPEN_STATUSES = {"tender", "retender"}


def clean(value):
    return unicodedata.normalize("NFKC", str(value if value is not None else "")).strip()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def plain(value: Decimal):
    return format(value, "f")


def number_key(value):
    """Compare decimals by value while retaining original precision in evidence."""
    if value is None:
        return None
    text = plain(Decimal(value))
    return text.rstrip("0").rstrip(".") if "." in text else text


def read_json(path):
    def reject_constant(value):
        raise ValueError("JSON does not accept " + value)
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream, parse_constant=reject_constant)


def atomic_write(path, content):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix="." + target.name + ".",
                                         delete=False) as stream:
            temp_name = stream.name
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def parse_day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected ISO date YYYY-MM-DD, got " + repr(value))
    return date.fromisoformat(value)


def deadline_day(value):
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)):
        return parse_day(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("deadline datetime requires an explicit time zone")
    from datetime import timezone
    return parsed.astimezone(timezone(timedelta(hours=8))).date()


def today_china():
    from datetime import timezone
    return datetime.now(timezone(timedelta(hours=8))).date()


def month_shift(day, months):
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def window(as_of, start=None, end=None, months=24):
    if months <= 0:
        raise ValueError("months must be positive")
    finish = parse_day(end) if end else as_of
    begin = parse_day(start) if start else month_shift(finish, -months)
    if begin > finish:
        raise ValueError("window start is after end")
    return {"start": begin.isoformat(), "end": finish.isoformat(),
            "endpoints": "inclusive", "months_default": months, "timezone": "Asia/Shanghai"}


def decimal_number(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("amount values must be decimal strings or integers, never floats")
    text = clean(value)
    if not re.fullmatch(NUMBER, text):
        raise ValueError("not a single nonnegative decimal number with valid comma grouping")
    if len(text) > 60:
        raise ValueError("amount has more than 60 characters; review precision")
    return Decimal(text.replace(",", ""))


def normalize_amount(amount):
    if not isinstance(amount, dict):
        raise ValueError("amounts entries must be objects")
    result = dict(amount)
    issues = []
    kind = clean(amount.get("kind"))
    raw = clean(amount.get("raw"))
    currency = clean(amount.get("currency")).upper()
    unit = clean(amount.get("unit"))
    tax = clean(amount.get("tax_basis")) or "unspecified"
    scope = clean(amount.get("scope")) or "unknown"
    parsed_raw = RAW_MONEY.fullmatch(raw)
    value = amount.get("value")
    if value is None and parsed_raw:
        value = parsed_raw.group("value")
        unit = unit or parsed_raw.group("unit")
    if kind not in KINDS:
        issues.append("unknown_amount_kind")
    if not raw:
        issues.append("missing_amount_original")
    if re.search(r"约|预计|不超过|不少于|以上|以下|至|~|～|%|％|\d\s*[-—–]\s*\d", raw):
        issues.append("ambiguous_amount_original")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        issues.append("missing_or_invalid_currency")
    if parsed_raw and parsed_raw.group("prefix") and currency != "CNY":
        issues.append("currency_conflicts_with_original")
    if unit not in UNITS:
        issues.append("unknown_amount_unit")
    if tax not in TAXES:
        issues.append("unknown_tax_basis")
    if scope not in SCOPES:
        issues.append("unknown_amount_scope")
    base = None
    try:
        if value is None:
            raise ValueError("missing explicit amount")
        number = decimal_number(value)
        if unit in UNITS:
            with localcontext() as context:
                context.prec = 90
                base = number * UNITS[unit]
                if parsed_raw:
                    raw_base = decimal_number(parsed_raw.group("value")) * UNITS[parsed_raw.group("unit")]
                    if raw_base != base:
                        issues.append("value_conflicts_with_original")
    except (ValueError, InvalidOperation) as error:
        issues.append("invalid_amount: " + str(error))
    result.update(kind=kind, raw=raw, currency=currency, unit=unit, tax_basis=tax,
                  scope=scope, base_amount=plain(base) if base is not None and not issues else None,
                  issues=issues)
    return result


def business_payload(record):
    fields = ("project_number", "project_id", "buyer", "lot_id", "procurement_round",
              "title", "category", "region", "status", "deadline", "award_date",
              "requirements", "qualifications", "procurement_method", "contract_period",
              "rate_ceiling")
    payload = {key: record.get(key) for key in fields}
    payload["winners"] = sorted(record.get("winners", []))
    payload["amounts"] = sorted([
        {key: number_key(amount.get(key)) if key == "base_amount" else amount.get(key)
         for key in ("kind", "base_amount", "currency", "tax_basis", "scope", "issues")}
        for amount in record.get("amounts", [])
    ], key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
    payload["rates"] = sorted([
        {key: number_key(rate.get(key)) if key == "normalized_value" else rate.get(key)
         for key in ("kind", "normalized_value", "unit", "basis", "scope", "issues")}
        for rate in record.get("rates", [])
    ], key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
    return payload


def normalize_rate(rate):
    """Keep fee percentages separate from money and include their business terms."""
    if not isinstance(rate, dict):
        raise ValueError("rates entries must be objects")
    result = dict(rate)
    issues = []
    for field in ("kind", "raw", "unit", "basis", "scope"):
        result[field] = clean(rate.get(field))
    if result["kind"] not in {"ceiling", "quote", "award"}:
        issues.append("unknown_rate_kind")
    if not result["raw"]:
        issues.append("missing_rate_original")
    if result["unit"] != "percent":
        issues.append("unknown_rate_unit")
    if not result["basis"]:
        issues.append("missing_rate_basis")
    if result["scope"] not in {"project", "lot", "item"}:
        issues.append("unknown_rate_scope")
    value = None
    try:
        value = decimal_number(rate.get("value"))
    except (ValueError, InvalidOperation) as error:
        issues.append("invalid_rate: " + str(error))
    result["normalized_value"] = plain(value) if value is not None and not issues else None
    result["issues"] = issues
    return result


def normalize(document):
    if not isinstance(document, dict) or not isinstance(document.get("records"), list) or not isinstance(document.get("sources"), list):
        raise ValueError("input must be an object containing records and sources arrays")
    sources = {}
    for source in document["sources"]:
        if not isinstance(source, dict) or not clean(source.get("source_id")):
            raise ValueError("each source requires source_id")
        source_id = clean(source["source_id"])
        if source_id in sources:
            raise ValueError("duplicate source_id: " + source_id)
        sources[source_id] = dict(source, source_id=source_id)
    groups = defaultdict(list)
    record_ids = set()
    issues = []
    for raw in document["records"]:
        if not isinstance(raw, dict):
            raise ValueError("each record must be an object")
        record = dict(raw)
        record_id = clean(record.get("record_id"))
        if not record_id or record_id in record_ids:
            raise ValueError("record_id is missing or duplicated: " + record_id)
        record_ids.add(record_id)
        record["record_id"] = record_id
        problems = []
        for field in ("project_id", "project_number", "buyer", "lot_id", "procurement_round", "title", "category", "status", "region"):
            record[field] = clean(record.get(field))
        identity = ("id", record["project_id"]) if record["project_id"] else ("number", record["project_number"], record["buyer"])
        if not record["project_id"] and (not record["project_number"] or not record["buyer"]):
            identity = ("unresolved", record_id)
            problems.append("unresolved_project_identity")
        if not record["lot_id"]:
            problems.append("unresolved_lot_identity")
        if not record["procurement_round"]:
            problems.append("unresolved_procurement_round")
        record["project_key"] = digest([identity, record["procurement_round"]])
        record["lot_key"] = digest([identity, record["procurement_round"], record["lot_id"] or record_id])
        if record["category"] not in CATEGORIES:
            problems.append("unverified_category")
        if record["status"] not in STATUSES:
            record["status"] = "unknown"
            problems.append("unknown_status")
        if not record["title"]:
            problems.append("missing_title")
        for field in ("published_date", "award_date"):
            if record.get(field):
                try:
                    record[field] = parse_day(record[field]).isoformat()
                except ValueError:
                    record[field] = None
                    problems.append("invalid_" + field)
            else:
                record[field] = None
        if not record["published_date"]:
            problems.append("missing_published_date")
        try:
            deadline_day(record.get("deadline"))
        except ValueError:
            problems.append("invalid_deadline")
        revision = record.get("revision", 1)
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            problems.append("invalid_revision")
            revision = 1
        record["revision"] = revision
        if record.get("is_partial"):
            problems.append("partial_snapshot_requires_reconstruction")
        winners = record.get("winners", [])
        if not isinstance(winners, list) or any(not isinstance(item, str) for item in winners):
            raise ValueError("winners must be an array of names: " + record_id)
        record["winners"] = sorted(set(clean(item) for item in winners if clean(item)))
        source_ids = record.get("source_ids", [])
        if not isinstance(source_ids, list):
            raise ValueError("source_ids must be an array: " + record_id)
        record["source_ids"] = sorted(set(clean(item) for item in source_ids + [record.get("source_id")] if clean(item)))
        valid_sources = [sources[item] for item in record["source_ids"] if item in sources]
        if len(valid_sources) != len(record["source_ids"]) or not valid_sources:
            problems.append("missing_source_reference")
        source_ok = any(item.get("status") == "ok" and urlparse(str(item.get("url", ""))).scheme in {"http", "https"}
                        for item in valid_sources)
        evidence = record.get("evidence", [])
        if not isinstance(evidence, list):
            raise ValueError("evidence must be an array: " + record_id)
        evidence_ok = any(isinstance(item, dict) and clean(item.get("excerpt")) and clean(item.get("locator"))
                          and item.get("source_id") in record["source_ids"] and item.get("source_id") in sources
                          and sources[item["source_id"]].get("status") == "ok" for item in evidence)
        if record.get("verification") != "verified" or not source_ok or not evidence_ok:
            problems.append("unverified_original_evidence")
        if not clean(record.get("inclusion_reason")):
            problems.append("missing_inclusion_reason")
        amounts = record.get("amounts", [])
        if not isinstance(amounts, list):
            raise ValueError("amounts must be an array: " + record_id)
        record["amounts"] = [normalize_amount(amount) for amount in amounts]
        rates = record.get("rates", [])
        if not isinstance(rates, list):
            raise ValueError("rates must be an array: " + record_id)
        record["rates"] = [normalize_rate(rate) for rate in rates]
        if record.get("rate_ceiling") is not None:
            record["rate_ceiling"] = clean(record["rate_ceiling"])
        record["review_reasons"] = sorted(set(problems))
        record["needs_review"] = bool(problems or any(amount["issues"] for amount in record["amounts"]) or
                                      any(rate["issues"] for rate in record["rates"]))
        record["business_fingerprint"] = digest(business_payload(record))
        for problem in record["review_reasons"]:
            issues.append({"record_id": record_id, "issue": problem})
        for index, amount in enumerate(record["amounts"]):
            for problem in amount["issues"]:
                issues.append({"record_id": record_id, "amount_index": index, "issue": problem})
        for index, rate in enumerate(record["rates"]):
            for problem in rate["issues"]:
                issues.append({"record_id": record_id, "rate_index": index, "issue": problem})
        groups[record["lot_key"]].append(record)
    lots = []
    for lot_key, versions in sorted(groups.items()):
        versions.sort(key=lambda item: (item.get("published_date") or "", item["revision"], item["record_id"]))
        highest = max((item.get("published_date") or "", item["revision"]) for item in versions)
        latest = [item for item in versions if (item.get("published_date") or "", item["revision"]) == highest]
        superseded = set()
        for item in latest:
            refs = item.get("supersedes", [])
            if not isinstance(refs, list):
                raise ValueError("supersedes must be an array: " + item["record_id"])
            for ref in refs:
                if ref not in {version["record_id"] for version in versions}:
                    issues.append({"record_id": item["record_id"], "issue": "supersedes_reference_not_in_same_lot", "reference": ref})
                else:
                    superseded.add(ref)
        latest = [item for item in latest if item["record_id"] not in superseded]
        if not latest:
            latest = [versions[-1]]
            conflict = True
        else:
            conflict = len({item["business_fingerprint"] for item in latest}) > 1
        current = dict(latest[0])
        current["source_ids"] = sorted({source for version in versions for source in version["source_ids"]})
        # Keep the original result announcement date; a later correction is not a new award.
        revoked_dates = [(item["published_date"], item["revision"]) for item in versions
                         if item["status"] in {"award_revoked", "terminated"} and item["published_date"]]
        last_revoked = max(revoked_dates, default=("", 0))
        award_notices = [item for item in versions if item["status"] in {"awarded", "contracted"}
                         and item.get("notice_type") in {"award", "result", "成交", "中标"}
                         and item["published_date"] and (item["published_date"], item["revision"]) > last_revoked
                         and not item["review_reasons"]]
        current["award_notice_published_date"] = min((item["published_date"] for item in award_notices), default=None)
        current["award_notice_record_ids"] = [item["record_id"] for item in award_notices
                                              if item["published_date"] == current["award_notice_published_date"]]
        if conflict:
            current["review_reasons"] = sorted(set(current["review_reasons"] + ["unresolved_same_version_conflict"]))
            current["needs_review"] = True
            issues.append({"lot_key": lot_key, "issue": "unresolved_same_version_conflict", "record_ids": [item["record_id"] for item in latest]})
        lots.append({"lot_key": lot_key, "project_key": current["project_key"], "current": current,
                     "conflicts": [item["record_id"] for item in latest] if conflict else [], "versions": versions})
    announcements = set()
    for lot in lots:
        for version in lot["versions"]:
            source = sources.get(version.get("source_id"), {})
            announcements.add(version.get("announcement_id") or digest([
                source.get("url") or version["record_id"], version["published_date"], version.get("notice_type")]))
    return {"schema_version": SCHEMA_VERSION, "kind": "normalized_procurement",
            "coverage": document.get("coverage", {}), "sources": list(sources.values()),
            "lots": lots, "issues": issues, "input_record_count": len(document["records"]),
            "announcement_count": len(announcements)}


def require_normalized(document):
    if not isinstance(document, dict) or document.get("kind") != "normalized_procurement" or document.get("schema_version") != SCHEMA_VERSION or not isinstance(document.get("lots"), list):
        raise ValueError("expected normalized_procurement schema_version 1; run normalize first")


def select_total(record, kind):
    amounts = [amount for amount in record["amounts"] if amount["kind"] == kind]
    if not amounts:
        return None, "missing_" + kind + "_amount"
    if any(amount["base_amount"] is None or amount["issues"] for amount in amounts):
        return None, "unresolved_" + kind + "_amount"
    if any(amount["scope"] != "lot_total" and not (amount["scope"] == "project_total" and record["lot_id"] == "whole") for amount in amounts):
        return None, "not_confirmed_total_scope"
    unique = {(number_key(amount["base_amount"]), amount["currency"], amount["tax_basis"]) for amount in amounts}
    if len(unique) != 1:
        return None, "multiple_conflicting_" + kind + "_totals"
    return amounts[0], None


def median(values):
    n = len(values)
    if not n:
        return None
    middle = n // 2
    return values[middle] if n % 2 else (values[middle - 1] + values[middle]) / Decimal(2)


def amount_summary(records, kind):
    groups = defaultdict(list)
    missing = Counter()
    for record in records:
        amount, reason = select_total(record, kind)
        if amount:
            groups[(amount["currency"], amount["tax_basis"])].append(Decimal(amount["base_amount"]))
        else:
            missing[reason] += 1
    totals = []
    with localcontext() as context:
        context.prec = 100
        for (currency, tax), values in sorted(groups.items()):
            values.sort()
            midpoint = len(values) // 2
            lower = values[:midpoint] or values
            upper = values[midpoint + (len(values) % 2):] or values
            totals.append({"currency": currency, "tax_basis": tax, "count": len(values),
                           "total": plain(sum(values, Decimal(0))), "minimum": plain(values[0]),
                           "q1": plain(median(lower)), "median": plain(median(values)),
                           "q3": plain(median(upper)), "maximum": plain(values[-1]),
                           "unit": "currency_base", "quartile_method": "median of halves, excluding odd central observation"})
        disclosed = sum(item["count"] for item in totals)
        return {"amount_kind": kind, "eligible_lots": len(records), "disclosed_lots": disclosed,
                "missing_lots": len(records) - disclosed,
                "missing_rate": plain(Decimal(len(records) - disclosed) / Decimal(len(records))) if records else None,
                "missing_reasons": dict(missing), "totals_by_currency_and_tax_basis": totals}


def cohort_summary(records):
    return {"project_count": len({item["project_key"] for item in records}), "lot_count": len(records),
            "award": amount_summary(records, "award"), "contract": amount_summary(records, "contract")}


def statistics(document, as_of, start=None, end=None, date_basis="published_date"):
    require_normalized(document)
    interval = window(as_of, start, end)
    records = []
    exclusions = []
    for lot in document["lots"]:
        record = lot["current"]
        reason = None
        if record["status"] not in {"awarded", "contracted"}:
            reason = "not_current_confirmed_award"
        elif record["review_reasons"]:
            reason = "record_requires_verification"
        stamp = record.get("award_notice_published_date") if date_basis == "published_date" else record.get("award_date")
        if not reason and not stamp:
            reason = "missing_confirmed_award_notice_published_date" if date_basis == "published_date" else "missing_award_date"
        if not reason and not (interval["start"] <= stamp <= interval["end"]):
            reason = "outside_window"
        if reason:
            exclusions.append({"lot_key": lot["lot_key"], "record_id": record["record_id"], "reason": reason})
        else:
            records.append(dict(record, statistical_date=stamp))
    layers = {key: dict(label=label, **cohort_summary([item for item in records if item["category"] == key]))
              for key, label in CATEGORIES.items()}
    dimensions = {}
    for name in ("region", "buyer", "quarter", "supplier_group"):
        grouped = defaultdict(list)
        for record in records:
            if name == "quarter":
                stamp = parse_day(record["statistical_date"])
                key = str(stamp.year) + "-Q" + str((stamp.month - 1) // 3 + 1)
            elif name == "supplier_group":
                key = " + ".join(record["winners"]) or "未披露中标人"
            else:
                key = record.get(name) or "未披露"
            grouped[key].append(record)
        dimensions[name] = {key: cohort_summary(value) for key, value in sorted(grouped.items())}
    return {"schema_version": SCHEMA_VERSION, "kind": "procurement_statistics", "window": interval,
            "date_basis": date_basis, "date_basis_label": "已确认中标/成交公告发布日期（更正不移动原结果日期）" if date_basis == "published_date" else "原文明示的实际成交日期",
            "coverage": document.get("coverage", {}), "sources": document["sources"],
            "input_announcement_count": document.get("announcement_count", document["input_record_count"]),
            "input_record_count": document["input_record_count"], "distinct_project_count_all_statuses": len({lot["project_key"] for lot in document["lots"]}),
            "distinct_lot_count_all_statuses": len(document["lots"]), "cohort": cohort_summary(records),
            "layers": layers, "dimensions": dimensions, "included_lot_keys": [item["lot_key"] for item in records],
            "exclusions": exclusions, "issues": document["issues"]}


def cell(value):
    return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")


def statistics_markdown(result):
    lines = ["# ESG 相关项目公开样本统计底稿", "", "本文件是可复算统计底稿，需结合原文研究形成最终判断。", "",
             "研究窗口：" + result["window"]["start"] + " 至 " + result["window"]["end"] + "（两端包含，Asia/Shanghai）。",
             "日期口径：" + result["date_basis_label"] + "。", "",
             "范围：取得的公开样本；不代表全国全量市场规模。预算、候选、合同、单价与框架上限不加入成交总额。", "",
             "| 类别 | 成交项目数 | 成交标包数 | 披露成交金额标包 | 缺失或歧义标包 | 缺失率 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for layer in result["layers"].values():
        info = layer["award"]
        rate = plain(Decimal(info["missing_rate"]) * 100) + "%" if info["missing_rate"] is not None else "—"
        lines.append("| " + " | ".join(map(cell, [layer["label"], layer["project_count"], layer["lot_count"], info["disclosed_lots"], info["missing_lots"], rate])) + " |")
    lines += ["", "## 公开样本中相关项目成交金额", "", "同币种、同税口径分别计算，单位为币种基本单位；未暗自换汇。", "",
              "| 类别 | 币种 | 税口径 | 金额标包数 | 总额 | 中位数 | Q1 | Q3 | 最小 | 最大 |", "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for layer in result["layers"].values():
        for item in layer["award"]["totals_by_currency_and_tax_basis"]:
            lines.append("| " + " | ".join(map(cell, [layer["label"], item["currency"], item["tax_basis"], item["count"], item["total"], item["median"], item["q1"], item["q3"], item["minimum"], item["maximum"]])) + " |")
    lines += ["", "合同金额、地区/采购人/季度/联合供应商分组及排除理由见 statistics JSON；合同不能与成交价重复相加。", "",
              "## 来源与覆盖", "", "覆盖说明：`" + json.dumps(result["coverage"], ensure_ascii=False).replace("`", "'") + "`", ""]
    for source in result["sources"]:
        lines.append("- " + cell(source.get("publisher", source["source_id"])) + "：" + str(source.get("url", "")) + "；状态 " + str(source.get("status", "unknown")))
    lines += ["", "待核实问题数：" + str(len(result["issues"])) + "；未纳入当前窗口标包数：" + str(len(result["exclusions"])) + "。", ""]
    return "\n".join(lines)


def monitor(document, state, as_of, lookback_days=7, due_days=3):
    require_normalized(document)
    if lookback_days < 1 or due_days < 0:
        raise ValueError("lookback_days must be positive and due_days nonnegative")
    if not isinstance(state, dict) or state.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION or not isinstance(state.get("lots", {}), dict):
        raise ValueError("unsupported or malformed monitor state")
    if state.get("last_run_date") and parse_day(state["last_run_date"]) > as_of:
        raise ValueError("as_of precedes last_run_date; use a separate state for backtesting")
    query_start = as_of - timedelta(days=lookback_days)
    if state.get("last_complete_date"):
        query_start = min(query_start, parse_day(state["last_complete_date"]) - timedelta(days=lookback_days))
    if state.get("pending_query_start"):
        query_start = min(query_start, parse_day(state["pending_query_start"]))
    old_lots = state.get("lots", {})
    next_lots = dict(old_lots)
    changes = []
    due = []
    reviews = []
    for lot in document["lots"]:
        record = lot["current"]
        lot_key = lot["lot_key"]
        previous = old_lots.get(lot_key)
        if previous is not None and not isinstance(previous, dict):
            raise ValueError("malformed per-lot monitor state: " + lot_key)
        if record["review_reasons"]:
            reviews.append({"lot_key": lot_key, "record_id": record["record_id"], "reasons": record["review_reasons"]})
            continue
        if not previous or previous.get("fingerprint") != record["business_fingerprint"]:
            change_type = "new" if not previous else "changed"
            if previous and record["status"] in {"terminated", "award_revoked"}:
                change_type = "terminated_or_revoked"
            elif previous and record.get("deadline"):
                old_deadline = previous.get("deadline")
                if old_deadline:
                    try:
                        if deadline_day(record["deadline"]) > deadline_day(old_deadline):
                            change_type = "extended"
                    except ValueError:
                        pass
            changes.append({"type": change_type, "lot_key": lot_key, "record": record})
        notified = list(previous.get("deadline_notifications", [])) if previous else []
        end = deadline_day(record.get("deadline"))
        due_key = str(record.get("deadline") or "")
        if record["status"] in OPEN_STATUSES and end and as_of <= end <= as_of + timedelta(days=due_days) and due_key not in notified:
            due.append({"lot_key": lot_key, "record": record})
            notified.append(due_key)
        next_lots[lot_key] = {"fingerprint": record["business_fingerprint"], "status": record["status"],
                              "deadline": record.get("deadline"), "record_id": record["record_id"],
                              "last_seen_date": as_of.isoformat(), "deadline_notifications": notified}
    failures = [source for source in document["sources"] if source.get("status") != "ok"]
    coverage = document.get("coverage", {})
    if not isinstance(coverage, dict):
        raise ValueError("coverage must be an object")
    declared_start = coverage.get("query_start")
    completed_span = False
    if declared_start and coverage.get("searched_through"):
        completed_span = parse_day(declared_start) <= query_start and parse_day(coverage["searched_through"]) >= as_of
    complete = bool(document["sources"]) and not failures and coverage.get("search_completed") is True and completed_span
    next_state = dict(state, schema_version=SCHEMA_VERSION, lots=next_lots, last_run_date=as_of.isoformat())
    if complete:
        next_state["last_complete_date"] = as_of.isoformat()
        next_state.pop("pending_query_start", None)
    else:
        next_state["pending_query_start"] = query_start.isoformat()
    result = {"schema_version": SCHEMA_VERSION, "kind": "procurement_monitor", "as_of": as_of.isoformat(),
              "query_start": query_start.isoformat(), "query_end": as_of.isoformat(), "coverage": document.get("coverage", {}),
              "coverage_complete_for_supplied_sources": complete, "sources": document["sources"], "source_failures": failures,
              "changes": changes, "upcoming_deadlines": due, "review_records": reviews,
              "notice": "new表示首次见到该标包，需根据公告日期/类型辨别新招标与历史首次发现；来源完整只指提供的来源集合，不代表全国完整。"}
    return result, next_state


def monitor_markdown(result):
    lines = ["# ESG 招投标单次监控日报底稿", "", "研究日：" + result["as_of"] + "（Asia/Shanghai）。建议补查：" + result["query_start"] + " 至 " + result["query_end"] + "。", "",
             result["notice"], "", "## 来源状态", ""]
    if result["source_failures"]:
        lines.append("存在失败或仅取得线索的来源，不能宣称监控完整。")
    elif not result["sources"]:
        lines.append("没有提供来源台账，不能把结果解释为成功检索无新增。")
    elif result["coverage_complete_for_supplied_sources"]:
        lines.append("本次提供的来源均标记检索成功，声明的检索跨度覆盖建议窗口；实际全国覆盖另按台账说明。")
    else:
        lines.append("来源标记可访问，但尚无覆盖建议窗口的完整检索声明；已有历史公告不能证明今日检索完整。")
    for source in result["sources"]:
        lines.append("- " + cell(source.get("publisher", source["source_id"])) + "：" + str(source.get("status", "unknown")) + "；" + str(source.get("url", "")))
    lines += ["", "## 新见项目与变更", "", "| 类型 | 项目 | 状态 | 公告日期 | 截止 | 类别 |", "| --- | --- | --- | --- | --- | --- |"]
    labels = {"new": "首次发现", "changed": "内容变更", "extended": "延期", "terminated_or_revoked": "终止/撤销"}
    for change in result["changes"]:
        record = change["record"]
        lines.append("| " + " | ".join(map(cell, [labels[change["type"]], record["title"], record["status"], record["published_date"], record.get("deadline"), CATEGORIES.get(record["category"], "待核实")])) + " |")
        lines.append("")
        for amount in record["amounts"]:
            lines.append("- 金额口径 " + amount["kind"] + "：" + amount["raw"] + "；币种 " + amount["currency"] + "，税口径 " + amount["tax_basis"] + ("（待核实）" if amount["issues"] else ""))
        lines.append("- 纳入理由：" + cell(record.get("inclusion_reason")))
        for key in ("requirements", "qualifications"):
            lines.append("- " + ("技术需求" if key == "requirements" else "资格条件") + "：" + cell(record.get(key, "原文未提取，需核实")))
        for source_id in record["source_ids"]:
            source = next((source for source in result["sources"] if source["source_id"] == source_id), None)
            if source:
                lines.append("- 原文：" + str(source.get("url", "")))
        lines.append("")
    if not result["changes"]:
        lines += ["", "已提供且成功核验的记录中未发现新的业务变化；来源失败和覆盖缺口见上文。"]
    lines += ["", "## 临近截止", ""]
    for item in result["upcoming_deadlines"]:
        lines.append("- " + cell(item["record"]["title"]) + "：" + cell(item["record"].get("deadline")))
    if not result["upcoming_deadlines"]:
        lines.append("没有新的临近截止提醒；已提醒的同一截止时间不会重复列出。")
    lines += ["", "## 待核实与范围", "", "待核实记录数：" + str(len(result["review_records"])) + "。"]
    for item in result["review_records"]:
        lines.append("- " + item["record_id"] + "：" + ", ".join(item["reasons"]))
    lines += ["", "覆盖说明：`" + json.dumps(result["coverage"], ensure_ascii=False).replace("`", "'") + "`", "",
              "下一步：核验近期机会资格、技术任务与截止时间，形成适配理由和行动建议。此底稿未发送任何外部通知。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    interval = commands.add_parser("window", help="print inclusive 24-calendar-month window")
    interval.add_argument("--as-of")
    interval.add_argument("--months", type=int, default=24)
    normalizer = commands.add_parser("normalize", help="normalize evidence and consolidate explicit lot identities")
    normalizer.add_argument("--input", required=True)
    normalizer.add_argument("--output", required=True)
    stats = commands.add_parser("stats", help="compute stratified confirmed-award statistics")
    stats.add_argument("--input", required=True)
    stats.add_argument("--output", required=True)
    stats.add_argument("--markdown")
    stats.add_argument("--as-of")
    stats.add_argument("--start", "--from", dest="start")
    stats.add_argument("--end", "--to", dest="end")
    stats.add_argument("--date-basis", choices=("published_date", "award_date"), default="published_date")
    daily = commands.add_parser("monitor", help="write one-shot daily report and update local state")
    daily.add_argument("--input", required=True)
    daily.add_argument("--state", required=True)
    daily.add_argument("--output", required=True)
    daily.add_argument("--json-output")
    daily.add_argument("--as-of")
    daily.add_argument("--lookback-days", type=int, default=7)
    daily.add_argument("--due-days", type=int, default=3)
    daily.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        as_of = parse_day(args.as_of) if getattr(args, "as_of", None) else today_china()
        if args.command == "window":
            print(json.dumps(window(as_of, months=args.months), ensure_ascii=False))
        elif args.command == "normalize":
            result = normalize(read_json(args.input))
            write_json(args.output, result)
            print(json.dumps({"output": str(Path(args.output).resolve()), "lots": len(result["lots"]), "issues": len(result["issues"])}, ensure_ascii=False))
        elif args.command == "stats":
            result = statistics(read_json(args.input), as_of, args.start, args.end, args.date_basis)
            write_json(args.output, result)
            if args.markdown:
                atomic_write(args.markdown, statistics_markdown(result))
            print(json.dumps({"output": str(Path(args.output).resolve()), "included_lots": result["cohort"]["lot_count"], "window": result["window"], "date_basis": result["date_basis"]}, ensure_ascii=False))
        else:
            state = read_json(args.state) if Path(args.state).exists() else {"schema_version": SCHEMA_VERSION, "lots": {}}
            result, next_state = monitor(read_json(args.input), state, as_of, args.lookback_days, args.due_days)
            atomic_write(args.output, monitor_markdown(result))
            if args.json_output:
                write_json(args.json_output, result)
            if not args.dry_run:
                write_json(args.state, next_state)
            print(json.dumps({"report": str(Path(args.output).resolve()), "changes": len(result["changes"]), "source_failures": len(result["source_failures"]), "query_start": result["query_start"], "state_updated": not args.dry_run}, ensure_ascii=False))
        return 0
    except (ValueError, TypeError, KeyError, OSError, InvalidOperation) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
