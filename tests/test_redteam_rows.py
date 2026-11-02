"""Ticket 10b: every red-team review row and attack, loaded at run time.

No sentence is typed in this file: rows and attacks load from the JSON
files on disk, and each runs through the runner's own functions, so the
extras land exactly the way the runner applies them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import redteam

ROOT = Path(__file__).resolve().parents[1]
REDTEAM_DIR = ROOT / "docs" / "redteam"

ROUND_FILES = ("round-1.json", "round-2.json")
ADJUDICATED_FILES = ("round-1.adjudicated.json", "round-2.adjudicated.json")


def _read(name: str) -> dict:
    return json.loads((REDTEAM_DIR / name).read_text(encoding="utf-8"))


def _verdicts_by_id(name: str) -> dict[str, str]:
    adjudicated = _read(name.replace(".json", ".adjudicated.json"))
    return {
        verdict["id"]: verdict["verdict"] for verdict in adjudicated.get("verdicts", [])
    }


def _review_params() -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for name in ADJUDICATED_FILES:
        for row in _read(name)["found_in_review"]:
            params.append((name, row["id"]))
    return params


def _attack_params() -> list[tuple[str, str]]:
    params: list[tuple[str, str]] = []
    for name in ROUND_FILES:
        for attack in _read(name)["attacks"]:
            params.append((name, attack["id"]))
    return params


def _review_row(source_name: str, row_id: str) -> tuple[dict, str]:
    """Run one ``found_in_review`` row through the runner's own function."""
    adjudicated = _read(source_name)
    row = next(
        entry for entry in adjudicated["found_in_review"] if entry["id"] == row_id
    )
    source = REDTEAM_DIR / source_name
    rows = redteam.run_review_rows(
        source, {"found_in_review": [row]}, redteam.build_context()
    )
    assert len(rows) == 1
    return rows[0], row.get("verdict", "?")


@pytest.mark.parametrize(("source_name", "row_id"), _review_params())
def test_review_row_verdict_holds(source_name: str, row_id: str) -> None:
    outcome, verdict = _review_row(source_name, row_id)
    assert outcome["id"] == row_id
    assert outcome["raised"] is None, outcome
    if verdict == "real_hole":
        # R30 is a hole in verify_claims, but the gate already stopped
        # it, so it stays in this same assertion.
        assert outcome["passed"] is False, outcome
    elif verdict == "over_block":
        assert outcome["passed"] is True, outcome
    elif verdict == "not_false":
        # R45: text with no letters or digits says nothing, and the gate
        # rejects it as a form.
        assert row_id == "R45"
        assert outcome["passed"] is False, outcome
    else:  # pragma: no cover - the files pin the three verdicts above
        raise AssertionError(f"{source_name} {row_id}: unknown verdict {verdict!r}")


@pytest.mark.parametrize(("source_name", "attack_id"), _attack_params())
def test_attack_verdict_holds(source_name: str, attack_id: str) -> None:
    data = _read(source_name)
    attack = next(entry for entry in data["attacks"] if entry["id"] == attack_id)
    verdict = _verdicts_by_id(source_name).get(attack_id, "real_hole")
    claim = attack["claim"]
    outcome = redteam.run_claim(
        claim["text"],
        list(claim.get("fact_ids", [])),
        list(claim.get("metric_refs", [])),
        redteam.build_context(),
    )
    assert outcome["raised"] is None, outcome
    # A20 is true and A25 is false only in words the checker discloses it
    # leaves out: the reviewer ruled both to pass, read here from the
    # verdicts file rather than a list in this test.
    if verdict in ("not_false", "disclosed_limit"):
        assert outcome["passed"] is True, (attack_id, verdict, outcome)
    else:
        assert outcome["passed"] is False, (attack_id, verdict, outcome)
