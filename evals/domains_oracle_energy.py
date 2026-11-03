"""Ticket 26: the home energy oracle, apart from the implementation under test.

Stdlib only. It hardcodes the energy column names instead of reading
pack.json, so a reviewer can rerun it to check the expected answers.
It computes answers; it checks nothing.

Regenerate examples/domains/energy/expected.json with:
.venv/bin/python evals/domains_oracle_energy.py examples/domains/energy/data/energydata_extract.csv --windows 2016-01-18,2016-01-25,2016-02-01,2016-02-08,2016-02-15,2016-02-22,2016-02-29,2016-03-07,2016-03-14,2016-03-21,2016-03-28,2016-04-04,2016-04-11,2016-04-18,2016-04-25,2016-05-02,2016-05-09,2016-05-16 > examples/domains/energy/expected.json
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
    csv_path: str,
    starts: list[str],
    high_above: int,
    light_above: int,
    heavy_above: int,
) -> dict[str, Any]:
    """Per-window answers: per-date counts, week total, heavy days, commitment."""
    by_day: dict[str, list[dict[str, str]]] = {}
    for row in _read_rows(csv_path):
        day = row["date"][:10]
        by_day.setdefault(day, []).append(row)
    result: dict[str, Any] = {}
    for start in starts:
        first = date.fromisoformat(start)
        dates = [(first + timedelta(days=offset)).isoformat() for offset in range(7)]
        days: dict[str, dict[str, int]] = {}
        for day in dates:
            if day not in by_day:
                raise ValueError(f"oracle is missing data for {day}")
            rows = by_day[day]
            high = sum(1 for row in rows if int(row["Appliances"].strip()) > high_above)
            light = sum(1 for row in rows if int(row["lights"].strip()) > light_above)
            days[day] = {
                "rows": len(rows),
                "high_use_intervals": high,
                "light_intervals": light,
            }
        week_high = sum(days[day]["high_use_intervals"] for day in dates)
        heavy = sum(1 for day in dates if days[day]["high_use_intervals"] > heavy_above)
        result[start] = {
            "dates": dates,
            "days": days,
            "week_high_use_intervals": week_high,
            "heavy_days": heavy,
            "expected_commitment": (
                "inspect-appliances" if heavy >= 3 else "keep-monitoring"
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    """Run the energy oracle on one CSV and print the JSON answers."""
    parser = argparse.ArgumentParser(description="Home energy oracle for domain packs.")
    parser.add_argument("csv_path")
    parser.add_argument("--high-above", type=int, default=100)
    parser.add_argument("--light-above", type=int, default=0)
    parser.add_argument("--heavy-above", type=int, default=36)
    parser.add_argument("--windows", required=True)
    args = parser.parse_args(argv)
    starts = [piece.strip() for piece in str(args.windows).split(",") if piece.strip()]
    try:
        result = compute(
            str(args.csv_path),
            starts,
            int(args.high_above),
            int(args.light_above),
            int(args.heavy_above),
        )
    except (OSError, ValueError) as exc:
        print(f"oracle failed: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
