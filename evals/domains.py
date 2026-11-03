"""Ticket 26: frozen evaluation commands for domain packs.

freeze builds cases from the oracle expected values only (never the
CSV adapter); score checks them with the checker; wonder runs one real
window at a time with resume and limit; summary prints the tables.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

PINNED_WINDOWS = [
    "2011-01-03",
    "2011-01-17",
    "2011-01-24",
    "2011-03-07",
    "2011-07-04",
    "2011-07-25",
    "2011-10-17",
    "2011-11-28",
    "2011-12-05",
    "2011-12-12",
    "2012-02-06",
    "2012-02-13",
    "2012-03-19",
    "2012-04-30",
    "2012-06-11",
    "2012-07-09",
    "2012-07-16",
    "2012-08-06",
    "2012-09-10",
    "2012-10-22",
]

PINNED_SEED = 20261104

PLANTED_KINDS = [
    "wrong_value",
    "wrong_label",
    "wrong_period",
    "wrong_unit",
    "wrong_source",
    "wrong_direction",
]

CONTROL_KINDS = [
    "daily_total",
    "daily_casual",
    "daily_registered",
    "week_total",
    "busy_days",
    "comparison",
]

UNIT_CYCLE = ["hours", "minutes", "seconds", "days", "percent"]

DIRECTION_PAIRS = [
    ("rose", "fell"),
    ("increased", "decreased"),
    ("went up", "went down"),
]

_LABEL_SWAP = {"Total": "Casual", "Casual": "Registered", "Registered": "Total"}


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _read_json(path: str) -> Any | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _claim(
    text: str, refs: list[tuple[str, int]], fact_ids: list[str] | None = None
) -> dict[str, Any]:
    return {
        "id": "c1",
        "text": text,
        "metric_refs": [
            {"metric_id": metric_id, "value": value} for metric_id, value in refs
        ],
        "fact_ids": list(fact_ids or []),
    }


def _comparison_pairs(entry: dict[str, Any]) -> list[tuple[str, str, int, int]]:
    """Every consecutive date pair whose totals differ, in window order."""
    dates = entry["dates"]
    pairs: list[tuple[str, str, int, int]] = []
    for left, right in itertools.pairwise(dates):
        first = entry["days"][left]["cnt"]
        second = entry["days"][right]["cnt"]
        if first != second:
            pairs.append((left, right, first, second))
    if not pairs:
        raise ValueError("no differing consecutive dates for a comparison")
    return pairs


def _comparison_pair(entry: dict[str, Any]) -> tuple[str, str, int, int]:
    return _comparison_pairs(entry)[0]


def _claim_key(
    claim: dict[str, Any],
) -> tuple[str, tuple[tuple[str, int], ...], tuple[str, ...]]:
    refs = tuple(
        (str(item["metric_id"]), int(item["value"])) for item in claim["metric_refs"]
    )
    facts = tuple(str(item) for item in claim.get("fact_ids", []))
    return str(claim["text"]), refs, facts


def _true_word(first: int, second: int, pair: tuple[str, str]) -> str:
    return pair[0] if second > first else pair[1]


def _control_claim(
    kind: str, start: str, entry: dict[str, Any], index: int, phrase: str
) -> dict[str, Any]:
    dates = entry["dates"]
    if kind == "week_total":
        value = entry["week_total"]
        return _claim(
            f"Total rentals were {value:,} in the {phrase}.",
            [("week_total_rentals", value)],
        )
    if kind == "busy_days":
        value = entry["busy_days"]
        return _claim(
            f"Busy days numbered {value:,} in the {phrase}.",
            [("busy_days", value)],
        )
    if kind == "comparison":
        left, right, first, second = _comparison_pair(entry)
        word = _true_word(first, second, DIRECTION_PAIRS[0])
        return _claim(
            f"Total rentals {word} from {first:,} on {left} to {second:,} on {right}.",
            [(f"total_rentals.{left}", first), (f"total_rentals.{right}", second)],
        )
    prefix = {"daily_total": "total_rentals", "daily_casual": "casual_rentals"}.get(
        kind, "registered_rentals"
    )
    column = {"daily_total": "cnt", "daily_casual": "casual"}.get(kind, "registered")
    label = {"daily_total": "Total", "daily_casual": "Casual"}.get(kind, "Registered")
    day = dates[index % len(dates)]
    value = entry["days"][day][column]
    return _claim(
        f"{label} rentals were {value:,} on {day}.",
        [(f"{prefix}.{day}", value)],
    )


def _daily_base(
    rng: random.Random, entry: dict[str, Any]
) -> tuple[str, str, str, int, str]:
    kind = rng.choice(["daily_total", "daily_casual", "daily_registered"])
    prefix = {
        "daily_total": "total_rentals",
        "daily_casual": "casual_rentals",
        "daily_registered": "registered_rentals",
    }[kind]
    column = {"daily_total": "cnt", "daily_casual": "casual"}.get(kind, "registered")
    label = {"daily_total": "Total", "daily_casual": "Casual"}.get(kind, "Registered")
    day = rng.choice(entry["dates"])
    return kind, prefix, label, entry["days"][day][column], day


def _planted_case(
    kind: str,
    number: int,
    start: str,
    entry: dict[str, Any],
    windows: list[str],
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if kind == "wrong_value":
        _, prefix, label, value, day = _daily_base(rng, entry)
        delta = rng.randint(1, 9)
        wrong = value + delta
        twin = _claim(
            f"{label} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        if number < 5:
            claim = _claim(
                f"{label} rentals were {wrong:,} on {day}.",
                [(f"{prefix}.{day}", wrong)],
            )
        else:
            claim = _claim(
                f"{label} rentals were {wrong:,} on {day}.",
                [(f"{prefix}.{day}", value)],
            )
        return claim, twin
    if kind == "wrong_label":
        _, prefix, label, value, day = _daily_base(rng, entry)
        twin = _claim(
            f"{label} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        swapped = _LABEL_SWAP[label]
        claim = _claim(
            f"{swapped} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        return claim, twin
    if kind == "wrong_period":
        _, prefix, label, value, day = _daily_base(rng, entry)
        twin = _claim(
            f"{label} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        dates = entry["dates"]
        other = dates[(dates.index(day) + 1) % len(dates)]
        claim = _claim(
            f"{label} rentals were {value:,} on {other}.", [(f"{prefix}.{day}", value)]
        )
        return claim, twin
    if kind == "wrong_unit":
        word = UNIT_CYCLE[number % len(UNIT_CYCLE)]
        if word == "days":
            value = entry["busy_days"]
            phrase = "week of " + start
            twin = _claim(
                f"Busy days numbered {value:,} in the {phrase}.", [("busy_days", value)]
            )
            claim = _claim(
                f"Busy days numbered {value:,} weeks in the {phrase}.",
                [("busy_days", value)],
            )
            return claim, twin
        _, prefix, label, value, day = _daily_base(rng, entry)
        twin = _claim(
            f"{label} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        claim = _claim(
            f"{label} rentals were {value:,} {word} on {day}.",
            [(f"{prefix}.{day}", value)],
        )
        return claim, twin
    if kind == "wrong_source":
        _, prefix, label, value, day = _daily_base(rng, entry)
        twin = _claim(
            f"{label} rentals were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        if number < 5:
            outside = next(candidate for candidate in windows if candidate != start)
            claim = _claim(
                f"{label} rentals were {value:,} on {day}.",
                [(f"{prefix}.{outside}", value)],
            )
            return claim, twin
        claim = _claim(
            f"{label} rentals were {value:,} on {day}.",
            [(f"{prefix}.{day}", value)],
            [f"unknown_fact_{number}"],
        )
        return claim, twin
    if kind == "wrong_direction":
        pair = DIRECTION_PAIRS[number % len(DIRECTION_PAIRS)]
        pairs = _comparison_pairs(entry)
        left, right, first, second = rng.choice(pairs)
        twin = _claim(
            f"Total rentals {_true_word(first, second, pair)} from {first:,} on {left} "
            f"to {second:,} on {right}.",
            [(f"total_rentals.{left}", first), (f"total_rentals.{right}", second)],
        )
        flipped = pair[1] if _true_word(first, second, pair) == pair[0] else pair[0]
        claim = _claim(
            f"Total rentals {flipped} from {first:,} on {left} to {second:,} on {right}.",
            [(f"total_rentals.{left}", first), (f"total_rentals.{right}", second)],
        )
        return claim, twin
    raise ValueError(f"unknown planted kind: {kind}")


def _display_name(labels: list[str]) -> str:
    name = " ".join(labels)
    return name[:1].upper() + name[1:] if name else name


def _generic_control_kinds(pack: dict[str, Any]) -> list[tuple[str, str]]:
    """One control kind per metric in pack order, then the comparison."""
    kinds = [("daily", str(item["prefix"])) for item in pack["daily_metrics"]]
    kinds += [("window", str(item["id"])) for item in pack["window_metrics"]]
    kinds.append(("comparison", "comparison"))
    return kinds


def _generic_pairs(
    entry: dict[str, Any], prefix: str
) -> list[tuple[str, str, int, int]]:
    """Every consecutive date pair whose first-series values differ."""
    dates = entry["dates"]
    pairs: list[tuple[str, str, int, int]] = []
    for left, right in itertools.pairwise(dates):
        first = entry["days"][left][prefix]
        second = entry["days"][right][prefix]
        if first != second:
            pairs.append((left, right, first, second))
    if not pairs:
        raise ValueError("no differing consecutive dates for a comparison")
    return pairs


def _generic_daily_labels(pack: dict[str, Any]) -> dict[str, list[str]]:
    return {str(item["prefix"]): list(item["labels"]) for item in pack["daily_metrics"]}


def _generic_window_specs(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["id"]): item for item in pack["window_metrics"]}


def _generic_control_claim(
    slot: tuple[str, str],
    start: str,
    entry: dict[str, Any],
    index: int,
    phrase: str,
    pack: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    kind, name = slot
    if kind == "comparison":
        first_metric = pack["daily_metrics"][0]
        prefix = str(first_metric["prefix"])
        display = _display_name(list(first_metric["labels"]))
        left, right, first, second = _generic_pairs(entry, prefix)[0]
        word = _true_word(first, second, DIRECTION_PAIRS[0])
        return "comparison", _claim(
            f"{display} {word} from {first:,} on {left} to {second:,} on {right}.",
            [(f"{prefix}.{left}", first), (f"{prefix}.{right}", second)],
        )
    if kind == "daily":
        display = _display_name(_generic_daily_labels(pack)[name])
        day = entry["dates"][index % len(entry["dates"])]
        value = entry["days"][day][name]
        return f"daily_{name}", _claim(
            f"{display} were {value:,} on {day}.", [(f"{name}.{day}", value)]
        )
    specs = _generic_window_specs(pack)
    display = _display_name(list(specs[name]["labels"]))
    value = entry[name]
    if str(specs[name]["op"]) == "sum":
        text = f"{display} were {value:,} in the {phrase}."
    else:
        text = f"{display} numbered {value:,} in the {phrase}."
    return name, _claim(text, [(name, value)])


def _generic_daily_base(
    rng: random.Random, pack: dict[str, Any], entry: dict[str, Any]
) -> tuple[str, str, int, str]:
    item = rng.choice(list(pack["daily_metrics"]))
    prefix = str(item["prefix"])
    day = rng.choice(entry["dates"])
    return prefix, _display_name(list(item["labels"])), entry["days"][day][prefix], day


def _generic_planted_case(
    kind: str,
    number: int,
    per_kind: int,
    start: str,
    entry: dict[str, Any],
    windows: list[str],
    pack: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if kind == "wrong_value":
        prefix, display, value, day = _generic_daily_base(rng, pack, entry)
        delta = rng.randint(1, 9)
        wrong = value + delta
        twin = _claim(
            f"{display} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        if number * 2 < per_kind:
            claim = _claim(
                f"{display} were {wrong:,} on {day}.",
                [(f"{prefix}.{day}", wrong)],
            )
        else:
            claim = _claim(
                f"{display} were {wrong:,} on {day}.",
                [(f"{prefix}.{day}", value)],
            )
        return claim, twin
    if kind == "wrong_label":
        prefix, display, value, day = _generic_daily_base(rng, pack, entry)
        twin = _claim(
            f"{display} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        others = [
            str(item["prefix"])
            for item in pack["daily_metrics"]
            if str(item["prefix"]) != prefix
        ]
        other = rng.choice(others)
        swapped = _display_name(_generic_daily_labels(pack)[other])
        claim = _claim(
            f"{swapped} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        return claim, twin
    if kind == "wrong_period":
        prefix, display, value, day = _generic_daily_base(rng, pack, entry)
        twin = _claim(
            f"{display} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        dates = entry["dates"]
        other = dates[(dates.index(day) + 1) % len(dates)]
        claim = _claim(
            f"{display} were {value:,} on {other}.", [(f"{prefix}.{day}", value)]
        )
        return claim, twin
    if kind == "wrong_unit":
        word = UNIT_CYCLE[number % len(UNIT_CYCLE)]
        if word == "days":
            targets = [
                str(item["id"])
                for item in pack["window_metrics"]
                if str(item["unit"]) == "days"
            ]
            if targets:
                metric_id = targets[0]
                display = _display_name(
                    list(_generic_window_specs(pack)[metric_id]["labels"])
                )
                value = entry[metric_id]
                phrase = "week of " + start
                twin = _claim(
                    f"{display} numbered {value:,} in the {phrase}.",
                    [(metric_id, value)],
                )
                claim = _claim(
                    f"{display} numbered {value:,} weeks in the {phrase}.",
                    [(metric_id, value)],
                )
                return claim, twin
        prefix, display, value, day = _generic_daily_base(rng, pack, entry)
        twin = _claim(
            f"{display} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        claim = _claim(
            f"{display} were {value:,} {word} on {day}.",
            [(f"{prefix}.{day}", value)],
        )
        return claim, twin
    if kind == "wrong_source":
        prefix, display, value, day = _generic_daily_base(rng, pack, entry)
        twin = _claim(
            f"{display} were {value:,} on {day}.", [(f"{prefix}.{day}", value)]
        )
        if number * 2 < per_kind:
            outside = next(candidate for candidate in windows if candidate != start)
            claim = _claim(
                f"{display} were {value:,} on {day}.",
                [(f"{prefix}.{outside}", value)],
            )
            return claim, twin
        claim = _claim(
            f"{display} were {value:,} on {day}.",
            [(f"{prefix}.{day}", value)],
            [f"unknown_fact_{number}"],
        )
        return claim, twin
    if kind == "wrong_direction":
        pair = DIRECTION_PAIRS[number % len(DIRECTION_PAIRS)]
        prefix = str(pack["daily_metrics"][0]["prefix"])
        display = _display_name(list(pack["daily_metrics"][0]["labels"]))
        left, right, first, second = rng.choice(_generic_pairs(entry, prefix))
        twin = _claim(
            f"{display} {_true_word(first, second, pair)} from {first:,} on {left} "
            f"to {second:,} on {right}.",
            [(f"{prefix}.{left}", first), (f"{prefix}.{right}", second)],
        )
        flipped = pair[1] if _true_word(first, second, pair) == pair[0] else pair[0]
        claim = _claim(
            f"{display} {flipped} from {first:,} on {left} to {second:,} on {right}.",
            [(f"{prefix}.{left}", first), (f"{prefix}.{right}", second)],
        )
        return claim, twin
    raise ValueError(f"unknown planted kind: {kind}")


def _freeze_cases_generic(
    pack: dict[str, Any],
    expected: dict[str, Any],
    windows: list[str],
    per_kind: int,
    seed: int,
) -> list[dict[str, Any]]:
    kinds = _generic_control_kinds(pack)
    cases: list[dict[str, Any]] = []
    for index, start in enumerate(windows):
        entry = expected[start]
        period = str(pack["window"]["period_phrase"]).replace("{start}", start)
        kind, claim = _generic_control_claim(
            kinds[index % len(kinds)], start, entry, index, period, pack
        )
        cases.append(
            {
                "case_id": f"control-{start}",
                "window_start": start,
                "kind": kind,
                "expect": "pass",
                "claim": claim,
            }
        )
    seen = {_claim_key(case["claim"]) for case in cases}
    rng = random.Random(seed)
    for kind in PLANTED_KINDS:
        for number in range(per_kind):
            for _ in range(100):
                start = rng.choice(windows)
                entry = expected[start]
                claim, twin = _generic_planted_case(
                    kind, number, per_kind, start, entry, windows, pack, rng
                )
                if _claim_key(claim) not in seen:
                    break
            else:
                raise ValueError(
                    f"freeze cannot place a distinct {kind} claim after 100 draws"
                )
            seen.add(_claim_key(claim))
            cases.append(
                {
                    "case_id": f"{kind}-{number:02d}-{start}",
                    "window_start": start,
                    "kind": kind,
                    "expect": "fail",
                    "claim": claim,
                    "twin": twin,
                }
            )
    return cases


def _freeze_cases(
    pack: dict[str, Any],
    expected: dict[str, Any],
    windows: list[str],
    per_kind: int,
    seed: int,
) -> list[dict[str, Any]]:
    if pack.get("pack_id") != "bikes":
        return _freeze_cases_generic(pack, expected, windows, per_kind, seed)
    cases: list[dict[str, Any]] = []
    for index, start in enumerate(windows):
        kind = CONTROL_KINDS[index % len(CONTROL_KINDS)]
        entry = expected[start]
        period = str(pack["window"]["period_phrase"]).replace("{start}", start)
        claim = _control_claim(kind, start, entry, index, period)
        cases.append(
            {
                "case_id": f"control-{start}",
                "window_start": start,
                "kind": kind,
                "expect": "pass",
                "claim": claim,
            }
        )
    seen = {_claim_key(case["claim"]) for case in cases}
    rng = random.Random(seed)
    for kind in PLANTED_KINDS:
        for number in range(per_kind):
            for _ in range(100):
                start = rng.choice(windows)
                entry = expected[start]
                claim, twin = _planted_case(kind, number, start, entry, windows, rng)
                if _claim_key(claim) not in seen:
                    break
            else:
                raise ValueError(
                    f"freeze cannot place a distinct {kind} claim after 100 draws"
                )
            seen.add(_claim_key(claim))
            cases.append(
                {
                    "case_id": f"{kind}-{number:02d}-{start}",
                    "window_start": start,
                    "kind": kind,
                    "expect": "fail",
                    "claim": claim,
                    "twin": twin,
                }
            )
    return cases


def _cmd_freeze(args: Any) -> int:
    pack = _read_json(str(args.pack))
    expected = _read_json(str(args.expected))
    if pack is None or expected is None:
        return _fail("pack or expected file cannot be read")
    seed = int(args.seed)
    per_kind = int(args.planted_per_kind)
    if args.windows:
        windows = [
            piece.strip() for piece in str(args.windows).split(",") if piece.strip()
        ]
    else:
        windows = list(PINNED_WINDOWS)
    for start in windows:
        if start not in expected:
            return _fail(f"window is missing from the expected file: {start}")
    out = Path(str(args.out))
    if out.exists() and not args.force:
        print("refusing to overwrite the cases file without --force", file=sys.stderr)
        return 1
    try:
        cases = _freeze_cases(pack, expected, windows, per_kind, seed)
    except (ValueError, KeyError) as exc:
        return _fail(f"cases cannot be built from the expected file: {exc}")
    payload = {
        "pack_id": pack.get("pack_id"),
        "seed": seed,
        "windows": windows,
        "cases": cases,
    }
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        return _fail("cases file cannot be written")
    return 0


def _check_one(
    check_claims: Any, ref: Any, claim: dict[str, Any]
) -> tuple[bool, bool | None, list[dict[str, str]]]:
    from framework.verify.core import VerifyInputError

    try:
        report = check_claims(ref.check_input([claim]))
    except VerifyInputError:
        return False, None, [{"code": "DOMAIN_CHECK_INPUT", "claim_id": "c1"}]
    codes = [
        {"code": item.code, "claim_id": item.claim_id} for item in report.violations
    ]
    return report.passed, report.complete, codes


def _cmd_score(args: Any) -> int:
    from framework.domains.csv_adapter import (
        IdentityError,
        SourceHashMismatch,
        WindowError,
        build_reference,
    )
    from framework.domains.runner import git_commit
    from framework.domains.schema import PackError, load_pack
    from framework.verify.hardened import check_claims

    try:
        pack = load_pack(str(args.pack))
    except PackError:
        return _fail("pack is invalid")
    payload = _read_json(str(args.cases))
    if payload is None:
        return _fail("cases file cannot be read")
    cases = payload["cases"] if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        return _fail("cases file must hold a list of cases")
    pack_dir = str(Path(str(args.pack)).parent)
    try:
        digest = hashlib.sha256(Path(str(args.cases)).read_bytes()).hexdigest()
    except OSError:
        return _fail("cases file cannot be read")
    refs: dict[str, Any] = {}
    try:
        for case in cases:
            start = case["window_start"]
            if start not in refs:
                refs[start] = build_reference(pack, pack_dir, start)
    except (WindowError, SourceHashMismatch, IdentityError, KeyError):
        return _fail("window cannot be built")
    results: list[dict[str, Any]] = []
    for case in cases:
        ref = refs[case["window_start"]]
        passed, complete, codes = _check_one(check_claims, ref, case["claim"])
        twin_passed: bool | None = None
        twin_complete: bool | None = None
        twin_codes: list[dict[str, str]] = []
        if case.get("twin") is not None:
            twin_passed, twin_complete, twin_codes = _check_one(
                check_claims, ref, case["twin"]
            )
        results.append(
            {
                "case_id": case["case_id"],
                "window_start": case["window_start"],
                "kind": case["kind"],
                "expect": case["expect"],
                "passed": passed,
                "complete": complete,
                "codes": codes,
                "twin_passed": twin_passed,
                "twin_complete": twin_complete,
                "twin_codes": twin_codes,
            }
        )
    controls = [entry for entry in results if entry["expect"] == "pass"]
    planted = [entry for entry in results if entry["expect"] == "fail"]

    def _rate(items: list[dict[str, Any]], good: Any) -> str:
        hits = sum(1 for item in items if good(item))
        return f"{hits}/{len(items)}"

    per_kind: dict[str, str] = {}
    for kind in sorted({entry["kind"] for entry in planted}):
        group = [entry for entry in planted if entry["kind"] == kind]
        per_kind[kind] = _rate(group, lambda item: not item["passed"])
    codes_by_kind: dict[str, dict[str, int]] = {}
    for kind in sorted({entry["kind"] for entry in results}):
        group = [entry for entry in results if entry["kind"] == kind]
        counts: dict[str, int] = {}
        for entry in group:
            for code in {item["code"] for item in entry["codes"]}:
                counts[code] = counts.get(code, 0) + 1
        codes_by_kind[kind] = counts
    twins = [entry for entry in results if entry["twin_passed"] is not None]
    misses = [
        {
            "case_id": entry["case_id"],
            "window_start": entry["window_start"],
            "kind": entry["kind"],
            "expect": entry["expect"],
            "passed": entry["passed"],
        }
        for entry in results
        if (entry["expect"] == "pass") != bool(entry["passed"])
    ]
    misses.extend(
        {
            "case_id": entry["case_id"],
            "window_start": entry["window_start"],
            "kind": entry["kind"],
            "expect": "twin-pass",
            "passed": entry["twin_passed"],
        }
        for entry in results
        if entry["twin_passed"] is False
    )
    summary = {
        "controls_total": len(controls),
        "controls_accepted": _rate(controls, lambda item: item["passed"]),
        "planted_total": len(planted),
        "planted_caught": _rate(planted, lambda item: not item["passed"]),
        "per_kind_caught": per_kind,
        "codes_by_kind": codes_by_kind,
        "twins_total": len(twins),
        "twins_accepted": _rate(twins, lambda item: item["twin_passed"]),
        "misses": misses,
    }
    output = {
        "pack_id": pack.pack_id,
        "windows": sorted(refs),
        "git_commit": git_commit(),
        "case_sha256": digest,
        "summary": summary,
        "results": results,
    }
    try:
        out = Path(str(args.out))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        return _fail("score file cannot be written")
    return 0


def _cmd_wonder(args: Any, client_factory: Any | None) -> int:
    from framework.domains.csv_adapter import (
        IdentityError,
        SourceHashMismatch,
        WindowError,
        build_reference,
    )
    from framework.domains.runner import git_commit, run_window
    from framework.domains.schema import PackError, load_pack

    try:
        pack = load_pack(str(args.pack))
    except PackError:
        return _fail("pack is invalid")
    payload = _read_json(str(args.cases))
    if payload is None:
        return _fail("cases file cannot be read")
    cases = payload["cases"] if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        return _fail("cases file must hold a list of cases")
    try:
        digest = hashlib.sha256(Path(str(args.cases)).read_bytes()).hexdigest()
    except OSError:
        return _fail("cases file cannot be read")
    pack_dir = str(Path(str(args.pack)).parent)
    windows = sorted({case["window_start"] for case in cases})
    out = Path(str(args.out))
    done: set[str] = set()
    if out.exists():
        try:
            for line in out.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    entry = json.loads(line)
                    if isinstance(entry, dict) and entry.get("window_start"):
                        done.add(str(entry["window_start"]))
        except (OSError, ValueError):
            return _fail("wonder output file cannot be read")
    todo = [start for start in windows if start not in done]
    if args.limit is not None:
        todo = todo[: int(args.limit)]
    if client_factory is None:
        from framework.proposal.muse_client import MuseExecClient

        client = MuseExecClient(private_terms=(), private_terms_available=True)
    else:
        client = client_factory()
    commit = git_commit()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "a", encoding="utf-8") as handle:
            for start in todo:
                try:
                    ref = build_reference(pack, pack_dir, start)
                except (WindowError, SourceHashMismatch, IdentityError):
                    return _fail(f"window cannot be built: {start}")
                run = run_window(
                    pack, ref, client, model=str(args.model), effort=str(args.effort)
                )
                line = dict(run.to_json())
                line["git_commit"] = commit
                line["case_sha256"] = digest
                handle.write(json.dumps(line, sort_keys=True) + "\n")
                handle.flush()
    except OSError:
        return _fail("wonder output file cannot be written")
    return 0


def _cmd_summary(args: Any) -> int:
    score = _read_json(str(args.score))
    if score is None or not isinstance(score, dict):
        return _fail("score file cannot be read")
    summary = score.get("summary")
    if not isinstance(summary, dict):
        return _fail("score file has no summary")
    oracle = _read_json(str(args.expected))
    if oracle is None or not isinstance(oracle, dict):
        return _fail("expected file cannot be read")
    try:
        raw_lines = Path(str(args.wonder)).read_text(encoding="utf-8").splitlines()
    except OSError:
        return _fail("wonder file cannot be read")
    lines: list[dict[str, Any]] = []
    for raw in raw_lines:
        if raw.strip():
            try:
                entry = json.loads(raw)
            except ValueError:
                return _fail("wonder file is not valid JSON lines")
            if isinstance(entry, dict):
                lines.append(entry)
    total = len(lines)

    def _wonder_attempts(entry: dict[str, Any]) -> list[Any]:
        attempts = entry.get("attempts", [])
        return list(attempts) if isinstance(attempts, list) else []

    def _oracle_commitment(entry: dict[str, Any]) -> str | None:
        record = oracle.get(str(entry.get("window_start")))
        if not isinstance(record, dict):
            return None
        want = record.get("expected_commitment")
        return str(want) if isinstance(want, str) else None

    def _commitment_matches(entry: dict[str, Any], position: int) -> bool:
        attempts = _wonder_attempts(entry)
        if not attempts:
            return False
        want = _oracle_commitment(entry)
        if want is None:
            return False
        first = attempts[position] if isinstance(attempts[position], dict) else {}
        return first.get("commitment_id") == want

    def _wonder_rate(good: Any) -> str:
        return f"{sum(1 for entry in lines if good(entry))}/{total}"

    latencies = [int(entry.get("latency_ms_total", 0)) for entry in lines]
    first_latencies: list[int] = []
    for entry in lines:
        attempts = _wonder_attempts(entry)
        if attempts:
            first = attempts[0] if isinstance(attempts[0], dict) else {}
            first_latencies.append(int(first.get("latency_ms", 0)))
    median_first_ms = statistics.median(first_latencies) if first_latencies else 0
    median_ms = statistics.median(latencies) if latencies else 0
    max_ms = max(latencies) if latencies else 0
    code_counts: dict[str, int] = {}
    for entry in lines:
        attempts = _wonder_attempts(entry)
        if attempts:
            first = attempts[0] if isinstance(attempts[0], dict) else {}
            codes = first.get("codes", [])
            if isinstance(codes, list):
                for item in codes:
                    if isinstance(item, dict) and isinstance(item.get("code"), str):
                        code = str(item["code"])
                        code_counts[code] = code_counts.get(code, 0) + 1

    def _seconds(value: float) -> str:
        return f"{value / 1000:.1f}s"

    print("| kind | caught |")
    print("| --- | --- |")
    per_kind = summary.get("per_kind_caught", {})
    if isinstance(per_kind, dict):
        for kind in sorted(per_kind):
            print(f"| {kind} | {per_kind[kind]} |")
    print(f"| controls accepted | {summary.get('controls_accepted')} |")
    print(f"| twins accepted | {summary.get('twins_accepted')} |")
    print(f"| planted caught | {summary.get('planted_caught')} |")
    print()
    print("| measure | value |")
    print("| --- | --- |")
    print(
        f"| first-pass acceptance | {_wonder_rate(lambda e: e.get('first_pass_accepted'))} |"
    )
    print(f"| repaired | {_wonder_rate(lambda e: e.get('repaired'))} |")
    print(
        "| residual failures | "
        f"{_wonder_rate(lambda e: not e.get('final_passed') and not e.get('transport_error'))} |"
    )
    print(f"| transport errors | {_wonder_rate(lambda e: e.get('transport_error'))} |")
    print(
        f"| first-attempt commitment matches oracle | {_wonder_rate(lambda e: _commitment_matches(e, 0))} |"
    )
    print(
        f"| final-attempt commitment matches oracle | {_wonder_rate(lambda e: _commitment_matches(e, -1))} |"
    )
    print(f"| median first-attempt latency | {_seconds(median_first_ms)} |")
    print(f"| median total latency | {_seconds(median_ms)} |")
    print(f"| maximum total latency | {_seconds(max_ms)} |")
    print()
    print("| code | first attempts |")
    print("| --- | --- |")
    if code_counts:
        for code in sorted(code_counts):
            print(f"| {code} | {code_counts[code]} |")
    else:
        print("(no codes on first attempts)")
    return 0


def main(argv: list[str] | None = None, client_factory: Any | None = None) -> int:
    """Run the frozen evaluation commands; returns the exit code."""
    from framework.proposal.defaults import DEFAULT_EFFORT, DEFAULT_MODEL

    parser = argparse.ArgumentParser(description="Frozen domain pack evaluation.")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--pack", required=True)
    freeze.add_argument("--expected", required=True)
    freeze.add_argument("--seed", default=str(PINNED_SEED))
    freeze.add_argument("--windows", default=",".join(PINNED_WINDOWS))
    freeze.add_argument("--planted-per-kind", default="10")
    freeze.add_argument("--out", required=True)
    freeze.add_argument("--force", action="store_true")
    score = sub.add_parser("score")
    score.add_argument("--pack", required=True)
    score.add_argument("--cases", required=True)
    score.add_argument("--out", required=True)
    wonder = sub.add_parser("wonder")
    wonder.add_argument("--pack", required=True)
    wonder.add_argument("--cases", required=True)
    wonder.add_argument("--out", required=True)
    wonder.add_argument("--limit", default=None)
    wonder.add_argument("--model", default=DEFAULT_MODEL)
    wonder.add_argument("--effort", default=DEFAULT_EFFORT)
    summary = sub.add_parser("summary")
    summary.add_argument("--score", required=True)
    summary.add_argument("--wonder", required=True)
    summary.add_argument("--expected", required=True)
    args = parser.parse_args(argv)
    command: str = args.command
    if command == "freeze":
        return _cmd_freeze(args)
    if command == "score":
        return _cmd_score(args)
    if command == "wonder":
        return _cmd_wonder(args, client_factory)
    if command == "summary":
        return _cmd_summary(args)
    return _fail("unknown command")


if __name__ == "__main__":
    sys.exit(main())
