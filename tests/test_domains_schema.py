"""Ticket 26: domain pack schema acceptance tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from framework.domains.schema import PackError, load_pack

ROOT = Path(__file__).resolve().parents[1]
BIKES_PACK = ROOT / "examples" / "domains" / "bikes" / "pack.json"
DAY_SHA = "a6bcf826782d3c0fbfdcbeead17cd0884185a0dafe8ff10cd48a874ee7ba18be"
HOUR_SHA = "e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f"


def _mutated(tmp_path: Path, change: Any) -> Path:
    data = json.loads(BIKES_PACK.read_text(encoding="utf-8"))
    change(data)
    out = tmp_path / "pack.json"
    out.write_text(json.dumps(data), encoding="utf-8")
    return out


def test_bikes_pack_loads_with_pinned_values() -> None:
    pack = load_pack(BIKES_PACK)
    assert pack.pack_id == "bikes"
    assert [c.id for c in pack.commitments] == [
        "review-capacity",
        "continue-monitoring",
    ]
    busy = next(m for m in pack.window_metrics if m.id == "busy_days")
    assert busy.op == "count_above"
    assert busy.above == 7000
    assert pack.sources["day"].sha256 == DAY_SHA
    assert pack.sources["hour"].sha256 == HOUR_SHA


def test_unknown_top_level_key_raises_pack_error(tmp_path: Path) -> None:
    path = _mutated(tmp_path, lambda d: d.__setitem__("bogus", 1))
    with pytest.raises(PackError):
        load_pack(path)


def test_rule_naming_undeclared_metric_raises_pack_error(
    tmp_path: Path,
) -> None:
    def change(data: dict[str, Any]) -> None:
        data["commitments"][0]["when"]["metric"] = "no_such_metric"

    with pytest.raises(PackError):
        load_pack(_mutated(tmp_path, change))


def test_unit_outside_checker_units_raises_pack_error(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["daily_metrics"][0]["unit"] = "kWh"

    with pytest.raises(PackError):
        load_pack(_mutated(tmp_path, change))


def test_label_entry_with_space_raises_pack_error(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["daily_metrics"][0]["labels"] = ["total rentals"]

    with pytest.raises(PackError):
        load_pack(_mutated(tmp_path, change))


def test_count_above_without_above_raises_pack_error(tmp_path: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        del data["window_metrics"][1]["above"]

    with pytest.raises(PackError):
        load_pack(_mutated(tmp_path, change))


def test_pack_error_is_value_error() -> None:
    assert issubclass(PackError, ValueError)
    data = json.loads(BIKES_PACK.read_text(encoding="utf-8"))
    assert isinstance(copy.deepcopy(data), dict)
