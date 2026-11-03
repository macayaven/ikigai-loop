"""Ticket 26, pack 2: the home energy pack, declared in JSON with its own oracle.

The real energy data runs cold here: tests compare numbers (adapter against
the oracle) and never check a claim on a real energy window.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ENERGY = ROOT / "examples" / "domains" / "energy"
PACK = ENERGY / "pack.json"
DATA = ENERGY / "data" / "energydata_extract.csv"
EXPECTED = ENERGY / "expected.json"
ORACLE = ROOT / "evals" / "domains_oracle_energy.py"
CASES = ROOT / "evals" / "domains_cases" / "energy.json"
MINI = ROOT / "tests" / "fixtures" / "domains" / "energy_mini"

PINNED_WINDOWS = [
    "2016-01-18",
    "2016-01-25",
    "2016-02-01",
    "2016-02-08",
    "2016-02-15",
    "2016-02-22",
    "2016-02-29",
    "2016-03-07",
    "2016-03-14",
    "2016-03-21",
    "2016-03-28",
    "2016-04-04",
    "2016-04-11",
    "2016-04-18",
    "2016-04-25",
    "2016-05-02",
    "2016-05-09",
    "2016-05-16",
]

PLANTED_KINDS = [
    "wrong_value",
    "wrong_label",
    "wrong_period",
    "wrong_unit",
    "wrong_source",
    "wrong_direction",
]


def _fresh_oracle() -> dict[str, Any]:
    from evals.domains_oracle_energy import compute

    result = compute(str(DATA), PINNED_WINDOWS, 100, 0, 36)
    assert isinstance(result, dict)
    return result


def test_load_pack_and_window_starts() -> None:
    from framework.domains.csv_adapter import window_starts
    from framework.domains.schema import load_pack

    pack = load_pack(PACK)
    assert pack.pack_id == "energy"
    assert pack.goal.id == "spot-heavy-weeks"
    assert [c.id for c in pack.commitments] == [
        "inspect-appliances",
        "keep-monitoring",
    ]
    # window_starts is presence based (see the plan): the opening week of
    # 2016-01-11 counts because its dates exist, even though 2016-01-11
    # holds only 42 rows and fails the rows_per_date identity. The 18
    # pinned evaluation weeks are the complete ones.
    assert window_starts(pack, ENERGY) == ["2016-01-11"] + PINNED_WINDOWS


def test_adapter_agrees_with_oracle_numbers_only() -> None:
    from evals.domains_oracle_energy import compute
    from framework.domains.csv_adapter import build_reference
    from framework.domains.schema import load_pack

    pack = load_pack(PACK)
    result = compute(str(DATA), PINNED_WINDOWS, 100, 0, 36)
    assert sorted(result) == PINNED_WINDOWS
    for start in PINNED_WINDOWS:
        ref = build_reference(pack, ENERGY, start)
        entry = result[start]
        assert entry["dates"] == list(ref.dates)
        for day in ref.dates:
            assert entry["days"][day]["rows"] == 144
            assert (
                entry["days"][day]["high_use_intervals"]
                == ref.metrics[f"high_use_intervals.{day}"]
            )
            assert (
                entry["days"][day]["light_intervals"]
                == ref.metrics[f"light_intervals.{day}"]
            )
        assert (
            entry["week_high_use_intervals"] == ref.metrics["week_high_use_intervals"]
        )
        assert entry["heavy_days"] == ref.metrics["heavy_days"]


def test_expected_json_matches_fresh_oracle() -> None:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert expected == _fresh_oracle()


def test_energy_oracle_imports_only_stdlib() -> None:
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


def _mini_expected(tmp_path: Path) -> Path:
    from evals.domains_oracle_energy import compute

    result = compute(str(MINI / "energy.csv"), ["2030-01-07", "2030-01-14"], 100, 0, 36)
    out = tmp_path / "mini_expected.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return out


def _freeze_mini(tmp_path: Path) -> Path:
    from evals.domains import main

    out = tmp_path / "mini_cases.json"
    code = main(
        [
            "freeze",
            "--pack",
            str(MINI / "pack.json"),
            "--expected",
            str(_mini_expected(tmp_path)),
            "--seed",
            "20261104",
            "--windows",
            "2030-01-07,2030-01-14",
            "--planted-per-kind",
            "2",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    return out


def _claim_key(claim: dict[str, Any]) -> tuple[str, tuple[Any, ...], tuple[str, ...]]:
    refs = tuple(
        (str(item["metric_id"]), int(item["value"])) for item in claim["metric_refs"]
    )
    facts = tuple(str(item) for item in claim.get("fact_ids", []))
    return str(claim["text"]), refs, facts


def test_mini_reference_matches_pack_and_twins_pass(tmp_path: Path) -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.schema import load_pack
    from framework.verify.hardened import check_claims

    pack = load_pack(MINI / "pack.json")
    assert [m.prefix for m in pack.daily_metrics] == [
        "high_use_intervals",
        "light_intervals",
    ]
    assert [m.id for m in pack.window_metrics] == [
        "week_high_use_intervals",
        "heavy_days",
    ]
    windows = ["2030-01-07", "2030-01-14"]
    refs = {start: build_reference(pack, MINI, start) for start in windows}
    for start in windows:
        ref = refs[start]
        assert ref.dates == tuple(
            f"2030-01-{day:02d}" for day in range(int(start[-2:]), int(start[-2:]) + 7)
        )
        want_ids = (
            {f"high_use_intervals.{day}" for day in ref.dates}
            | {f"light_intervals.{day}" for day in ref.dates}
            | {"week_high_use_intervals", "heavy_days"}
        )
        assert set(ref.metrics) == want_ids
        for metric in pack.daily_metrics:
            for day in ref.dates:
                metric_id = f"{metric.prefix}.{day}"
                assert ref.labels[metric_id] == list(metric.labels)
                assert ref.units[metric_id] == metric.unit
                assert ref.periods[metric_id] == day
        for metric in pack.window_metrics:
            assert ref.labels[metric.id] == list(metric.labels)
            assert ref.units[metric.id] == metric.unit
            assert ref.periods[metric.id] == f"week of {start}"
        assert [item.kind for item in ref.identities] == ["rows_per_date"]
        assert all(item.held for item in ref.identities)

    payload = json.loads(_freeze_mini(tmp_path).read_text(encoding="utf-8"))
    assert payload["pack_id"] == "energy"
    cases = payload["cases"]
    controls = [c for c in cases if c["expect"] == "pass"]
    planted = [c for c in cases if c["expect"] == "fail"]
    assert len(controls) == 2
    assert len(planted) == 12
    assert Counter(c["kind"] for c in planted) == Counter(
        {kind: 2 for kind in PLANTED_KINDS}
    )
    keys = [_claim_key(c["claim"]) for c in cases]
    assert len(set(keys)) == len(keys)
    for case in planted:
        assert case.get("twin")
        ref = refs[case["window_start"]]
        report = check_claims(ref.check_input([case["twin"]]))
        assert report.passed, case["case_id"]
        assert report.complete, case["case_id"]


def test_lint_mini_passes_every_subject(capsys: Any) -> None:
    from framework.domains.__main__ import main as domains_main

    code = domains_main(
        [
            "lint",
            "--pack",
            str(MINI / "pack.json"),
            "--window",
            "2030-01-07",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "FAIL" not in out


def test_energy_cases_file_matches_fresh_freeze(tmp_path: Path) -> None:
    from evals.domains import main

    assert CASES.exists()
    out = tmp_path / "fresh.json"
    code = main(
        [
            "freeze",
            "--pack",
            str(PACK),
            "--expected",
            str(EXPECTED),
            "--seed",
            "20261104",
            "--windows",
            ",".join(PINNED_WINDOWS),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert CASES.read_bytes() == out.read_bytes()
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    controls = [c for c in cases if c["expect"] == "pass"]
    planted = [c for c in cases if c["expect"] == "fail"]
    assert len(controls) == 18
    assert Counter(c["window_start"] for c in controls) == Counter(
        {start: 1 for start in PINNED_WINDOWS}
    )
    assert len(planted) == 60
    assert Counter(c["kind"] for c in planted) == Counter(
        {kind: 10 for kind in PLANTED_KINDS}
    )
    for case in planted:
        assert case.get("twin")
    keys = [_claim_key(c["claim"]) for c in cases]
    assert len(set(keys)) == len(keys)
