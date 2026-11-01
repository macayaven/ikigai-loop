"""Pre-reg R3 pairs: JSON shape, op semantics, and gate conformance.

No model, no network. The JSON holds the base scenario and the 20 pairs
from docs/PREREG.md; apply_ops in evals/r3_scenario.py is the exact code the
later harness uses to build each pair arm.
"""

from __future__ import annotations

import copy
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from evals.briefing_cases import base_case
from evals.r3_scenario import apply_ops
from framework.briefing import (
    Commitment,
    action_targets_repo,
    metric_label_binding,
    text_check_codes,
)
from framework.briefing.context import GateContext
from framework.briefing.gate import evaluate_briefing

R3_PATH = Path(__file__).resolve().parents[1] / "evals" / "r3_pairs.json"
PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "PREREG.md"

EXPECTED_IDS = [f"D{i}" for i in range(1, 11)] + [f"I{i}" for i in range(1, 11)]
DIRECTIONAL_IDS = [f"D{i}" for i in range(1, 11)]
INVARIANCE_IDS = [f"I{i}" for i in range(1, 11)]

# Sentence start -> metric family. A statement containing "feed items"
# cites feed.item.count.<suffix> when the arm has such a metric and the
# suffix appears in the statement, else feed.item.count. A statement
# matching nothing fails the test, so a typo in a label is caught here
# rather than passing quietly.
STATEMENT_FAMILIES = (
    ("Pushes", "pushes"),
    ("Programming screen hours", "screen_hours.Work/Programming"),
    ("Video screen hours", "screen_hours.Media/Video"),
    ("Chat screen hours", "screen_hours.Comms/Chat"),
    ("iki-family calendar hours", "tag_hours.iki-family"),
    ("iki-date calendar hours", "tag_hours.iki-date"),
    ("Cancelled iki-deep blocks", "cancelled.iki-deep"),
    ("Cancelled iki-family blocks", "cancelled.iki-family"),
)
PERIODS = ("earlier", "prior", "last")


def _load() -> dict[str, Any]:
    return json.loads(R3_PATH.read_text(encoding="utf-8"))


def _base_doc() -> dict[str, Any]:
    doc = _load()
    return {
        "slot": doc["slot"],
        "hour": doc["hour"],
        "commitments": doc["commitments"],
        "facts": doc["facts"],
        "metrics": doc["metrics"],
    }


def _arms() -> dict[str, dict[str, Any]]:
    doc = _load()
    base = _base_doc()
    return {pair["id"]: apply_ops(base, pair["perturb"]) for pair in doc["pairs"]}


def _statement_family(statement: str) -> str:
    if "feed items" in statement:
        return "feed.item.count"
    for start, family in STATEMENT_FAMILIES:
        if statement.startswith(start):
            return family
    pytest.fail(f"statement matches no metric family: {statement!r}")


def _fact_metric_ids(statement: str, metrics: dict[str, Any]) -> list[str]:
    """Metric ids backing one fact statement; unknown labels fail the test."""
    family = _statement_family(statement)
    if family == "feed.item.count":
        sub = sorted(
            metric_id
            for metric_id in metrics
            if metric_id.startswith(family + ".")
            and metric_id.removeprefix(family + ".").lower() in statement.lower()
        )
        if sub:
            return sub
        if family not in metrics:
            pytest.fail(f"arm is missing metric {family}")
        return [family]
    ids: list[str] = []
    for period in PERIODS:
        if re.search(rf"\b{period}\b", statement):
            metric_id = f"period.{period}.{family}"
            if metric_id not in metrics:
                pytest.fail(f"arm is missing metric {metric_id}")
            ids.append(metric_id)
    if not ids:
        pytest.fail(f"statement names no period: {statement!r}")
    return ids


def _gate_shell(arm: dict[str, Any]) -> tuple[dict[str, Any], GateContext]:
    """Briefing + context checking one arm claim by claim.

    Each fact statement becomes one claim citing its own fact id and only
    its own metrics, so a wrong number can no longer pass by coinciding
    with another metric's value. The actions section is left untouched.
    """
    case = base_case("builder")
    briefing = copy.deepcopy(case.briefing)
    working = next(s for s in briefing["sections"] if s["type"] == "working")
    working["claims"] = [
        {
            "id": f"claim-{fact['id']}",
            "text": fact["statement"],
            "fact_ids": [fact["id"]],
            "metric_refs": [
                {"metric_id": metric_id, "value": arm["metrics"][metric_id]}
                for metric_id in _fact_metric_ids(fact["statement"], arm["metrics"])
            ],
        }
        for fact in arm["facts"]
    ]
    window = {"start": "2026-11-03T00:00:00+01:00", "end": "2026-11-03T23:00:00+01:00"}
    facts = {
        fact["id"]: {
            "id": fact["id"],
            "subject_id": "subject-1",
            "window": window,
            "statement": fact["statement"],
            "evidence": ["synthetic r3 log"],
            "tier": "public",
        }
        for fact in arm["facts"]
    }
    dump = case.context.model_dump(mode="python")
    dump["facts"] = {**dump["facts"], **facts}
    dump["metrics"] = {"values": dict(arm["metrics"])}
    context = type(case.context).model_validate(dump)
    return briefing, context


def _arms_with_base() -> dict[str, dict[str, Any]]:
    arms = _arms()
    arms["base"] = _base_doc()
    return arms


@pytest.mark.parametrize("arm_id", ["base", *EXPECTED_IDS])
def test_r3_arm_facts_pass_the_gate_as_claims(arm_id: str) -> None:
    arm = _arms_with_base()[arm_id]
    briefing, context = _gate_shell(arm)
    result = evaluate_briefing(briefing, context)
    assert result.violations == (), (arm_id, result.violations)
    for fact in arm["facts"]:
        statement = str(fact["statement"])
        family = _statement_family(statement)
        if family == "feed.item.count":
            numbers = re.findall(r"\d+(?:\.\d+)?", statement)
            assert len(numbers) == 1, (arm_id, statement, numbers)
            metric_ids = _fact_metric_ids(statement, arm["metrics"])
            assert len(metric_ids) == 1, (arm_id, statement, metric_ids)
            assert Decimal(numbers[0]) == Decimal(str(arm["metrics"][metric_ids[0]])), (
                arm_id,
                statement,
            )
        else:
            dated = re.findall(r"(\d+(?:\.\d+)?) in (earlier|prior|last)", statement)
            assert dated, (arm_id, statement)
            for value, period in dated:
                metric_id = f"period.{period}.{family}"
                assert Decimal(value) == Decimal(str(arm["metrics"][metric_id])), (
                    arm_id,
                    statement,
                    metric_id,
                )


def test_fact_metric_ids_prefers_feed_sub_metric() -> None:
    metrics = {"feed.item.count": 6, "feed.item.count.medieval": 2}
    assert _fact_metric_ids("2 feed items about medieval manuscripts", metrics) == [
        "feed.item.count.medieval"
    ]
    assert _fact_metric_ids("6 feed items about agent evaluation", metrics) == [
        "feed.item.count"
    ]


@pytest.mark.parametrize(
    "commitment",
    json.loads(R3_PATH.read_text(encoding="utf-8"))["commitments"],
    ids=lambda commitment: commitment["id"],
)
def test_r3_commitment_titles_pass_the_public_text_checks(
    commitment: dict[str, Any],
) -> None:
    title = str(commitment["title"])
    assert text_check_codes(title) == (), (commitment["id"], title)
    assert action_targets_repo(title) is False, (commitment["id"], title)


def test_r3_fact_statements_pass_the_public_text_checks() -> None:
    for arm_id, arm in _arms_with_base().items():
        for fact in arm["facts"]:
            statement = str(fact["statement"])
            assert text_check_codes(statement) == (), (arm_id, fact["id"], statement)


def test_r3_metric_ids_have_a_label_binding() -> None:
    for arm_id, arm in _arms_with_base().items():
        for metric_id in arm["metrics"]:
            assert metric_label_binding(metric_id) is not None, (arm_id, metric_id)


def test_r3_json_shape() -> None:
    doc = _load()
    pairs = doc["pairs"]
    assert [p["id"] for p in pairs] == EXPECTED_IDS
    assert len({p["id"] for p in pairs}) == 20
    assert sum(p["kind"] == "directional" for p in pairs) == 10
    assert sum(p["kind"] == "invariance" for p in pairs) == 10
    assert sum(p["profile"] == "builder" for p in pairs) == 10
    assert sum(p["profile"] == "disconnect" for p in pairs) == 10
    assert doc["slot"] == "2026-11-03T15:30:00+01:00"
    assert doc["hour"] == {
        "start": "2026-11-03T15:30:00+01:00",
        "end": "2026-11-03T16:30:00+01:00",
    }
    assert len(doc["commitments"]) == 8
    assert len(doc["facts"]) == 6
    assert len(doc["metrics"]) == 16


def test_r3_apply_ops_is_pure_and_effective() -> None:
    doc = _load()
    base = _base_doc()
    snapshot = copy.deepcopy(base)
    for pair in doc["pairs"]:
        arm = apply_ops(base, pair["perturb"])
        assert base == snapshot
        assert set(arm) == {"slot", "hour", "commitments", "facts", "metrics"}
    arms = _arms()
    assert arms["D1"]["metrics"]["period.last.pushes"] == 0
    assert "0 in last" in next(
        f["statement"] for f in arms["D1"]["facts"] if f["id"] == "f1"
    )
    assert [f["id"] for f in arms["I3"]["facts"]] == [
        "f6",
        "f5",
        "f4",
        "f3",
        "f2",
        "f1",
    ]
    assert [f["id"] for f in arms["I5"]["facts"]] == [
        f"pre-{f}" for f in ["f1", "f2", "f3", "f4", "f5", "f6"]
    ]
    assert [c["id"] for c in arms["I6"]["commitments"]] == [
        c["id"] for c in reversed(_base_doc()["commitments"])
    ]
    assert arms["I8"]["slot"] == "2026-11-03T14:30:00+00:00"
    assert arms["I8"]["hour"] == {
        "start": "2026-11-03T14:30:00+00:00",
        "end": "2026-11-03T15:30:00+00:00",
    }
    assert arms["D5"]["metrics"]["period.last.pushes"] == 8
    assert arms["D5"]["metrics"]["period.last.screen_hours.Work/Programming"] == 10


def test_r3_apply_ops_rejects_unknown_and_duplicate_ids() -> None:
    base = _base_doc()
    with pytest.raises(KeyError):
        apply_ops(base, [{"op": "set_metric", "id": "period.last.nope", "value": 1}])
    with pytest.raises(KeyError):
        apply_ops(base, [{"op": "set_fact", "id": "f99", "statement": "nope"}])
    with pytest.raises(KeyError):
        apply_ops(base, [{"op": "add_fact", "id": "f1", "statement": "taken"}])
    with pytest.raises(KeyError):
        apply_ops(base, [{"op": "add_metric", "id": "feed.item.count", "value": 1}])
    with pytest.raises(KeyError):
        apply_ops(base, [{"op": "frobnicate"}])


def test_r3_commitments_have_valid_fields() -> None:
    doc = _load()
    profiles = []
    for c in doc["commitments"]:
        Commitment.model_validate(
            {
                "id": c["id"],
                "profile_id": c["profile"],
                "title": c["title"],
                "kind": c["kind"],
                "dimension": c["dimension"],
                "evidence": c["evidence"],
            }
        )
        assert c["profile"] in {"builder", "disconnect"}, c["id"]
        profiles.append(c["profile"])
    assert profiles.count("builder") == 4
    assert profiles.count("disconnect") == 4


def test_r3_perturbs_are_nonempty_and_change_the_base() -> None:
    doc = _load()
    base = _base_doc()
    for pair in doc["pairs"]:
        assert pair["perturb"], pair["id"]
        assert apply_ops(base, pair["perturb"]) != base, pair["id"]


def test_r3_directional_expects_name_one_commitment_of_the_pair_profile() -> None:
    doc = _load()
    by_id = {p["id"]: p for p in doc["pairs"]}
    allowed = {
        profile: {c["id"] for c in doc["commitments"] if c["profile"] == profile}
        for profile in ("builder", "disconnect")
    }
    for pid in DIRECTIONAL_IDS:
        pair = by_id[pid]
        assert (pair["expect_pick"] is None) != (pair["expect_avoid"] is None), pid
        named = pair["expect_pick"] or pair["expect_avoid"]
        assert named in allowed[pair["profile"]], pid
    for pid in INVARIANCE_IDS:
        pair = by_id[pid]
        assert pair["expect_pick"] is None and pair["expect_avoid"] is None, pid


def _doc_section(heading: str) -> list[str]:
    lines = PREREG_PATH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == heading)
    section = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        section.append(line)
    return section


def _doc_table(section: list[str]) -> list[list[str]]:
    rows = []
    for line in section:
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and all(set(cell) <= set("-: ") for cell in cells):
            continue
        rows.append(cells)
    return rows[1:]


def _doc_metric_value(raw: str) -> int | float:
    return float(raw) if "." in raw else int(raw)


_CHANGE_RE = re.compile(
    r"(?P<verb>add )?(?P<fid>f\d+)(?: becomes)? \"(?P<stmt>[^\"]+)\""
    r"|(?P<metric>[A-Za-z_][\w./-]*) = (?P<value>[\d.]+)"
)


def _doc_change_to_ops(
    pid: str, change: str, by_id: dict[str, Any], base_metrics: dict[str, Any]
) -> list[dict[str, Any]]:
    if change.startswith("same_as "):
        return copy.deepcopy(by_id[change.removeprefix("same_as ")]["perturb"])
    if change == "facts in reverse order":
        return [{"op": "reverse_facts"}]
    if change == "commitments in reverse order":
        return [{"op": "reverse_commitments"}]
    if change == "the same slot instant written in UTC":
        return [{"op": "slot_in_utc"}]
    if change == "every fact id gets a new prefix":
        perturb = by_id[pid]["perturb"]
        assert len(perturb) == 1 and perturb[0]["op"] == "rename_facts"
        assert perturb[0]["prefix"], "rename_facts needs a non-empty prefix"
        return copy.deepcopy(perturb)
    ops = []
    for match in _CHANGE_RE.finditer(change):
        if match.group("fid") is not None:
            op = "add_fact" if match.group("verb") else "set_fact"
            ops.append(
                {
                    "op": op,
                    "id": match.group("fid"),
                    "statement": match.group("stmt"),
                }
            )
        else:
            metric_id = match.group("metric")
            op = "set_metric" if metric_id in base_metrics else "add_metric"
            ops.append(
                {
                    "op": op,
                    "id": metric_id,
                    "value": _doc_metric_value(match.group("value")),
                }
            )
    return ops


def test_r3_json_matches_the_document() -> None:
    doc = _load()
    base_section = _doc_section("## The R3 base scenario")
    tables = [block for block in "\n".join(base_section).split("\n\n") if "|" in block]
    commitment_rows = _doc_table(tables[0].splitlines())
    fact_rows = _doc_table(tables[1].splitlines())
    assert [row[0] for row in commitment_rows] == [c["id"] for c in doc["commitments"]]
    for row, commitment in zip(commitment_rows, doc["commitments"]):
        assert row == [
            commitment["id"],
            commitment["profile"],
            commitment["title"],
            commitment["kind"],
            commitment["dimension"],
            commitment["evidence"],
        ], row[0]
    assert [row[0] for row in fact_rows] == [f["id"] for f in doc["facts"]]
    for row, fact in zip(fact_rows, doc["facts"]):
        assert row == [fact["id"], fact["statement"]], row[0]
    metrics_line = next(line for line in base_section if line.startswith("Metrics:"))
    expected_metrics: dict[str, int | float] = {}
    for family, raw in re.findall(
        r"period\.\{earlier,prior,last\}\.(\S+) = ([\d.]+)", metrics_line
    ):
        for period in PERIODS:
            expected_metrics[f"period.{period}.{family}"] = _doc_metric_value(raw)
    braced = re.sub(r"period\.\{earlier,prior,last\}\.\S+ = [\d.]+;?", "", metrics_line)
    for metric_id, raw in re.findall(r"([A-Za-z_][\w./-]*) = ([\d.]+)", braced):
        expected_metrics[metric_id] = _doc_metric_value(raw)
    assert expected_metrics == doc["metrics"]

    pair_rows = _doc_table(_doc_section("## The R3 pairs"))
    assert [row[0] for row in pair_rows] == EXPECTED_IDS
    by_id = {p["id"]: p for p in doc["pairs"]}
    for pid, kind, profile, change, expected in pair_rows:
        pair = by_id[pid]
        assert pair["kind"] == kind, pid
        assert pair["profile"] == profile, pid
        if expected == "same pick":
            assert pair["expect_pick"] is None and pair["expect_avoid"] is None, pid
        elif expected.startswith("pick "):
            assert pair["expect_pick"] == expected.removeprefix("pick "), pid
            assert pair["expect_avoid"] is None, pid
        elif expected.startswith("avoid "):
            assert pair["expect_avoid"] == expected.removeprefix("avoid "), pid
            assert pair["expect_pick"] is None, pid
        else:
            pytest.fail(f"unexpected expected cell: {expected!r} ({pid})")
        assert (
            _doc_change_to_ops(pid, change, by_id, doc["metrics"]) == pair["perturb"]
        ), pid
