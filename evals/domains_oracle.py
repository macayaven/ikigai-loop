"""Ticket 26: the bikes oracle, apart from the implementation under test.

Stdlib only. It hardcodes the bikes column names instead of reading
pack.json, so a reviewer can rerun it to check the expected answers.
It computes answers; it checks nothing.

Regenerate examples/domains/bikes/expected.json with:
.venv/bin/python evals/domains_oracle.py examples/domains/bikes/data/day.csv examples/domains/bikes/data/hour.csv --threshold 7000 --windows 2011-01-03,2011-01-17,2011-01-24,2011-03-07,2011-06-06,2011-07-04,2011-07-25,2011-10-17,2011-11-28,2011-12-05,2011-12-12,2012-02-06,2012-02-13,2012-03-19,2012-04-30,2012-06-04,2012-06-11,2012-07-09,2012-07-16,2012-08-06,2012-09-10,2012-10-22 > examples/domains/bikes/expected.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from typing import Any


def _read_rows(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return [dict(record) for record in csv.DictReader(handle)]


def compute(
    day_csv: str, hour_csv: str, starts: list[str], threshold: int
) -> dict[str, Any]:
    """Per-window answers: per-date counts, week total, busy days, commitment."""
    by_day: dict[str, dict[str, int]] = {}
    for row in _read_rows(day_csv):
        by_day[row["dteday"]] = {
            "cnt": int(row["cnt"]),
            "casual": int(row["casual"]),
            "registered": int(row["registered"]),
        }
    hour_sums: dict[str, int] = {}
    for row in _read_rows(hour_csv):
        day = row["dteday"]
        hour_sums[day] = hour_sums.get(day, 0) + int(row["cnt"])
    result: dict[str, Any] = {}
    for start in starts:
        first = date.fromisoformat(start)
        dates = [(first + timedelta(days=offset)).isoformat() for offset in range(7)]
        days: dict[str, dict[str, int]] = {}
        for day in dates:
            if day not in by_day or day not in hour_sums:
                raise ValueError(f"oracle is missing data for {day}")
            entry = by_day[day]
            days[day] = {
                "cnt": entry["cnt"],
                "casual": entry["casual"],
                "registered": entry["registered"],
                "hour_cnt_sum": hour_sums[day],
            }
        week_total = sum(days[day]["cnt"] for day in dates)
        busy_days = sum(1 for day in dates if days[day]["cnt"] > threshold)
        result[start] = {
            "dates": dates,
            "days": days,
            "week_total": week_total,
            "busy_days": busy_days,
            "expected_commitment": (
                "review-capacity" if busy_days >= 1 else "continue-monitoring"
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the oracle on two CSVs and print the JSON answers."""
    parser = argparse.ArgumentParser(description="Bikes oracle for domain packs.")
    parser.add_argument("day_csv")
    parser.add_argument("hour_csv")
    parser.add_argument("--threshold", type=int, default=7000)
    parser.add_argument("--windows", required=True)
    args = parser.parse_args(argv)
    starts = [piece.strip() for piece in str(args.windows).split(",") if piece.strip()]
    try:
        result = compute(
            str(args.day_csv), str(args.hour_csv), starts, int(args.threshold)
        )
    except (OSError, ValueError) as exc:
        print(f"oracle failed: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
