"""Ticket 26: domain pack oracle and frozen evaluation tests."""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BIKES = ROOT / "examples" / "domains" / "bikes"
ORACLE = ROOT / "evals" / "domains_oracle.py"
DOMAINS = ROOT / "evals" / "domains.py"
EXPECTED = BIKES / "expected.json"
CASES = ROOT / "evals" / "domains_cases" / "bikes.json"

EVAL_WINDOWS = [
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
DEV_WINDOWS = ["2011-06-06", "2012-06-04"]
PLANTED_KINDS = [
    "wrong_value",
    "wrong_label",
    "wrong_period",
    "wrong_unit",
    "wrong_source",
    "wrong_direction",
]


def _load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        cases = data["cases"]
        assert isinstance(cases, list)
        return cases
    assert isinstance(data, list)
    return data


def test_oracle_imports_only_stdlib() -> None:
    tree = ast.parse(ORACLE.read_text(encoding="utf-8"))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert modules
    for name in modules:
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names
        assert not name.startswith("framework")
        assert not name.startswith("evals")


def test_oracle_agrees_with_adapter_on_all_windows() -> None:
    from evals.domains_oracle import compute
    from framework.domains.csv_adapter import build_reference, window_starts
    from framework.domains.schema import load_pack

    pack = load_pack(BIKES / "pack.json")
    starts = window_starts(pack, BIKES)
    assert len(starts) == 104
    result = compute(
        str(BIKES / "data" / "day.csv"),
        str(BIKES / "data" / "hour.csv"),
        starts,
        7000,
    )
    for start in starts:
        ref = build_reference(pack, BIKES, start)
        entry = result[start]
        for date in ref.dates:
            day = entry["days"][date]
            assert day["cnt"] == ref.metrics[f"total_rentals.{date}"]
            assert day["casual"] == ref.metrics[f"casual_rentals.{date}"]
            assert day["registered"] == ref.metrics[f"registered_rentals.{date}"]
            assert day["hour_cnt_sum"] == day["cnt"]
        assert entry["week_total"] == ref.metrics["week_total_rentals"]
        assert entry["busy_days"] == ref.metrics["busy_days"]


def test_expected_json_matches_oracle() -> None:
    from evals.domains_oracle import compute

    windows = sorted(EVAL_WINDOWS + DEV_WINDOWS)
    result = compute(
        str(BIKES / "data" / "day.csv"),
        str(BIKES / "data" / "hour.csv"),
        windows,
        7000,
    )
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert expected == result


def test_freeze_is_deterministic(tmp_path: Path) -> None:
    from evals.domains import main

    out1 = tmp_path / "cases1.json"
    out2 = tmp_path / "cases2.json"
    args = [
        "freeze",
        "--pack",
        str(BIKES / "pack.json"),
        "--expected",
        str(EXPECTED),
        "--seed",
        "20261104",
    ]
    assert main([*args, "--out", str(out1)]) == 0
    assert main([*args, "--out", str(out2)]) == 0
    assert out1.read_bytes() == out2.read_bytes()
    cases = _load_cases(out1)
    controls = [c for c in cases if c["expect"] == "pass"]
    planted = [c for c in cases if c["expect"] == "fail"]
    assert len(controls) == 20
    assert len(planted) == 60
    assert Counter(c["window_start"] for c in controls) == Counter(EVAL_WINDOWS)
    assert Counter(c["kind"] for c in planted) == Counter(
        {kind: 10 for kind in PLANTED_KINDS}
    )
    for case in planted:
        assert case.get("twin")
    for case in cases:
        assert case["window_start"] not in DEV_WINDOWS


def test_frozen_cases_file_matches_fresh_freeze(tmp_path: Path) -> None:
    from evals.domains import main

    assert CASES.exists()
    out = tmp_path / "fresh.json"
    code = main(
        [
            "freeze",
            "--pack",
            str(BIKES / "pack.json"),
            "--expected",
            str(EXPECTED),
            "--seed",
            "20261104",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert CASES.read_bytes() == out.read_bytes()


def test_freeze_path_does_not_import_csv_adapter_at_top_level() -> None:
    tree = ast.parse(DOMAINS.read_text(encoding="utf-8"))
    top_level: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.append(node.module)
    for name in top_level:
        assert name != "framework.domains.csv_adapter"
        assert not name.startswith("framework.domains.csv_adapter.")
