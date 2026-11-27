"""Validate an evidence ledger and summarize disclosed RMB award totals."""

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit


FIELDS = {
    "project_key", "lot_key", "announcement_date", "theme",
    "stage", "amount_yuan", "source_url",
}
BANDS = (("10万元以下", 100_000), ("10至不足50万元", 500_000),
         ("50至不足100万元", 1_000_000), ("100至不足500万元", 5_000_000))


def read_ledger(path, start, end):
    latest = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not FIELDS.issubset(reader.fieldnames or ()):
            raise ValueError("CSV is missing required columns")
        for line_number, source in enumerate(reader, 2):
            try:
                row = {key: source[key].strip() for key in FIELDS}
                day = date.fromisoformat(row["announcement_date"])
                if row["stage"] not in {"award", "award_corrected"}:
                    raise ValueError("stage must be award or award_corrected")
                url = urlsplit(row["source_url"])
                if not row["project_key"] or not row["theme"]:
                    raise ValueError("empty project key or theme")
                if url.scheme not in {"https", "http"} or not url.hostname:
                    raise ValueError("a source URL is required")
                raw = row["amount_yuan"]
                amount = None
                if raw:
                    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", raw):
                        raise ValueError("use a decimal RMB total with up to two places")
                    amount = Decimal(raw)
                    if amount <= 0:
                        raise ValueError("disclosed amount must be positive")
                if not start <= day <= end:
                    continue
                key = (row["project_key"], row["lot_key"])
                previous = latest.get(key)
                ranked_date = (day, row["stage"] == "award_corrected")
                if previous and previous[0] > ranked_date:
                    continue
                if previous and previous[0] == ranked_date:
                    if (row["theme"], amount) != previous[1:3]:
                        raise ValueError(f"conflicting records for {key}; verify the notice")
                    continue
                latest[key] = (ranked_date, row["theme"], amount)
            except (ValueError, AttributeError) as error:
                raise ValueError(f"row {line_number}: {error}") from error

    projects_with_lots = {project for project, lot in latest if lot}
    for project in projects_with_lots:
        if (project, "") in latest:
            raise ValueError(f"{project}: resolve overlap between the project total and lots")
    return latest


def describe(rows):
    amounts = sorted(row[2] for row in rows if row[2] is not None)
    return {
        "observations": len(rows),
        "amount_count": len(amounts),
        "amount_total_yuan": str(sum(amounts, Decimal(0))),
        "median_yuan": str(median(amounts)) if amounts else None,
        "min_yuan": str(amounts[0]) if amounts else None,
        "max_yuan": str(amounts[-1]) if amounts else None,
    }


def summarize(ledger):
    rows = list(ledger.values())
    result = describe(rows)
    result["projects"] = len({key[0] for key in ledger})
    result["missing_amount"] = result["observations"] - result["amount_count"]
    by_theme = defaultdict(list)
    by_year = defaultdict(list)
    bands = Counter({label: 0 for label, _ in BANDS})
    bands["500万元及以上"] = 0
    for ranked_date, theme, amount in rows:
        by_theme[theme].append((ranked_date, theme, amount))
        by_year[ranked_date[0].year].append((ranked_date, theme, amount))
        if amount is not None:
            label = next((label for label, limit in BANDS if amount < limit), "500万元及以上")
            bands[label] += 1
    result["by_theme"] = {key: describe(group) for key, group in sorted(by_theme.items())}
    result["by_year"] = {key: describe(group) for key, group in sorted(by_year.items())}
    result["amount_bands"] = dict(bands)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if args.end < args.start:
        parser.error("--end must be on or after --start")
    try:
        output = summarize(read_ledger(args.ledger, args.start, args.end))
    except (ValueError, OSError, csv.Error) as error:
        parser.error(str(error))
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
