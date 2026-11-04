"""Ticket 26: domain pack CSV adapter acceptance tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from framework.domains.csv_adapter import (
    IdentityError,
    SourceHashMismatch,
    WindowError,
    build_reference,
    window_starts,
)
from framework.domains.schema import load_pack
from framework.verify.hardened import check_claims

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "domains" / "mini"
MINI_BAD_SUM = ROOT / "tests" / "fixtures" / "domains" / "mini_bad_sum"
MINI_BAD_HOUR = ROOT / "tests" / "fixtures" / "domains" / "mini_bad_hour"
BIKES = ROOT / "examples" / "domains" / "bikes"

WEEK1_DATES = [
    "2030-01-07",
    "2030-01-08",
    "2030-01-09",
    "2030-01-10",
    "2030-01-11",
    "2030-01-12",
    "2030-01-13",
]
WEEK1_TOTAL = [110, 80, 100, 120, 70, 90, 60]
WEEK1_CASUAL = [30, 20, 25, 40, 15, 35, 10]
WEEK1_REGISTERED = [80, 60, 75, 80, 55, 55, 50]


def _mini_ref(window: str = "2030-01-07") -> Any:
    pack = load_pack(MINI / "pack.json")
    return build_reference(pack, MINI, window)


def _claim(
    text: str, metric_id: str, value: int, claim_id: str = "c1"
) -> dict[str, Any]:
    return {
        "id": claim_id,
        "text": text,
        "metric_refs": [{"metric_id": metric_id, "value": value}],
        "fact_ids": [],
    }


def test_window_starts_mini() -> None:
    pack = load_pack(MINI / "pack.json")
    assert window_starts(pack, MINI) == ["2030-01-07", "2030-01-14"]


def test_build_reference_mini_first_week() -> None:
    ref = _mini_ref()
    assert list(ref.dates) == WEEK1_DATES
    expected: dict[str, int] = {}
    for date, total, casual, registered in zip(
        WEEK1_DATES, WEEK1_TOTAL, WEEK1_CASUAL, WEEK1_REGISTERED, strict=True
    ):
        expected[f"total_rentals.{date}"] = total
        expected[f"casual_rentals.{date}"] = casual
        expected[f"registered_rentals.{date}"] = registered
    expected["week_total_rentals"] = sum(WEEK1_TOTAL)
    expected["busy_days"] = 2
    assert ref.metrics == expected
    assert len(ref.metrics) == 23
    for date in WEEK1_DATES:
        assert ref.periods[f"total_rentals.{date}"] == date
    assert ref.periods["week_total_rentals"] == "week of 2030-01-07"
    assert ref.periods["busy_days"] == "week of 2030-01-07"
    assert ref.order == [
        [f"total_rentals.{d}" for d in WEEK1_DATES],
        [f"casual_rentals.{d}" for d in WEEK1_DATES],
        [f"registered_rentals.{d}" for d in WEEK1_DATES],
    ]
    assert len(ref.identities) == 2
    assert all(item.held for item in ref.identities)
    assert [item.kind for item in ref.identities] == [
        "columns_sum",
        "daily_matches",
    ]


def test_wrong_sha256_raises_source_hash_mismatch(tmp_path: Path) -> None:
    for name in ("pack.json", "day.csv", "hour.csv"):
        shutil.copy(MINI / name, tmp_path / name)
    data = json.loads((tmp_path / "pack.json").read_text(encoding="utf-8"))
    old = data["sources"]["day"]["sha256"]
    data["sources"]["day"]["sha256"] = ("0" if old[0] != "0" else "1") + old[1:]
    (tmp_path / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    pack = load_pack(tmp_path / "pack.json")
    with pytest.raises(SourceHashMismatch) as excinfo:
        build_reference(pack, tmp_path, "2030-01-07")
    assert "day" in str(excinfo.value)


def test_bad_sum_raises_identity_error() -> None:
    pack = load_pack(MINI_BAD_SUM / "pack.json")
    with pytest.raises(IdentityError) as excinfo:
        build_reference(pack, MINI_BAD_SUM, "2030-01-07")
    assert "columns_sum" in str(excinfo.value)


def test_bad_hour_raises_identity_error() -> None:
    pack = load_pack(MINI_BAD_HOUR / "pack.json")
    with pytest.raises(IdentityError) as excinfo:
        build_reference(pack, MINI_BAD_HOUR, "2030-01-07")
    assert "daily_matches" in str(excinfo.value)


def test_unknown_window_raises_window_error() -> None:
    pack = load_pack(MINI / "pack.json")
    with pytest.raises(WindowError):
        build_reference(pack, MINI, "2030-01-08")


def test_check_claims_pass_and_value_mismatch() -> None:
    ref = _mini_ref()
    value = ref.metrics["total_rentals.2030-01-07"]
    good = _claim(
        f"Total rentals were {value} on 2030-01-07.",
        "total_rentals.2030-01-07",
        value,
    )
    report = check_claims(ref.check_input([good]))
    assert report.passed
    assert report.complete is True
    bad = _claim(
        f"Total rentals were {value} on 2030-01-07.",
        "total_rentals.2030-01-07",
        value + 1,
    )
    report = check_claims(ref.check_input([bad]))
    assert not report.passed
    assert "L1B_METRIC_VALUE_MISMATCH" in [v.code for v in report.violations]


def test_known_blind_spot_kilometres_passes() -> None:
    ref = _mini_ref()
    value = ref.metrics["total_rentals.2030-01-07"]
    claim = _claim(
        f"Total rentals were {value} kilometres on 2030-01-07.",
        "total_rentals.2030-01-07",
        value,
    )
    report = check_claims(ref.check_input([claim]))
    assert report.passed


def test_known_blind_spot_label_day_fails() -> None:
    ref = _mini_ref()
    claim = _claim("Busy day count was 2 in the week of 2030-01-07.", "busy_days", 2)
    report = check_claims(ref.check_input([claim]))
    assert not report.passed
    assert "L1B_METRIC_LABEL_MISSING" in [v.code for v in report.violations]
    good = _claim("Busy days numbered 2 in the week of 2030-01-07.", "busy_days", 2)
    assert check_claims(ref.check_input([good])).passed


def test_bikes_window_starts() -> None:
    pack = load_pack(BIKES / "pack.json")
    starts = window_starts(pack, BIKES)
    assert len(starts) == 104
    assert starts[0] == "2011-01-03"
    assert starts[-1] == "2012-12-24"


def test_bikes_development_window_2011_06_06() -> None:
    pack = load_pack(BIKES / "pack.json")
    ref = build_reference(pack, BIKES, "2011-06-06")
    assert ref.metrics["total_rentals.2011-06-06"] == 4548
    assert ref.metrics["casual_rentals.2011-06-06"] == 673
    assert ref.metrics["week_total_rentals"] == 31709
    assert ref.metrics["busy_days"] == 0


def test_bikes_development_window_2012_06_04() -> None:
    pack = load_pack(BIKES / "pack.json")
    ref = build_reference(pack, BIKES, "2012-06-04")
    assert ref.metrics["total_rentals.2012-06-04"] == 6998
    assert ref.metrics["total_rentals.2012-06-05"] == 7001
    assert ref.metrics["week_total_rentals"] == 50380
    assert ref.metrics["busy_days"] == 5
