"""Ticket 15b, Step 5: R4 case-building tests (D37-D40).

Pure tests only: hand-written R3 rows and the committed pairs file, no
model, no network, no filesystem beyond the rows passed in.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from evals import r4_scenario
from evals.r3 import load_pairs
from evals.r3_scenario import apply_ops


def _draft(
    pick: str,
    claims: list[tuple[list[str], list[str], str]],
    *,
    section: str = "overall_state",
) -> str:
    """One minimal draft: claims go in ``section``, the rest stay empty."""
    sections = {"overall_state": [], "working": [], "not_working": []}
    sections[section] = [
        {"text": text, "fact_ids": list(fact_ids), "metric_refs": list(refs)}
        for fact_ids, refs, text in claims
    ]
    return json.dumps(
        {
            "commitment_id": pick,
            "overall_state": sections["overall_state"],
            "working": sections["working"],
            "not_working": sections["not_working"],
            "since_last": [],
        }
    )


def _r3_row(
    pair_id: str,
    arm: str,
    repeat: int,
    raw_text: str,
    *,
    execution: int = 1,
    drawn: bool = True,
) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "arm": arm,
        "repeat": repeat,
        "execution": execution,
        "drawn": drawn,
        "unavailable_reason": None if drawn else "timeout",
        "prompt_hash": "p" * 64,
        "attempts": [{"raw_text": raw_text}],
    }


def _cited_only(fact: str = "f1", pick: str = "b-ship") -> str:
    return _draft(pick, [([fact], [], f"Something about {fact} holds here")])


def _doc() -> dict[str, Any]:
    doc, _sha = load_pairs()
    return doc


def test_traversal_takes_five_per_profile_in_pair_file_order() -> None:
    doc = _doc()
    rows: list[dict[str, Any]] = []
    for pair in doc["pairs"]:
        profile = str(pair["profile"])
        pick = "b-ship" if profile == "builder" else "d-family"
        for repeat in (1, 2, 3):
            rows.append(
                _r3_row(str(pair["id"]), "base", repeat, _cited_only("f1", pick))
            )
    cases = r4_scenario.build_cases(rows, doc)
    assert len(cases) == 10
    assert [case.case_id for case in cases] == [f"r4-{n:02d}" for n in range(1, 11)]
    builder_ids = [p["id"] for p in doc["pairs"] if p["profile"] == "builder"]
    disconnect_ids = [p["id"] for p in doc["pairs"] if p["profile"] == "disconnect"]
    assert builder_ids == ["D1", "D2", "D3", "D4", "D5", "I1", "I3", "I5", "I7", "I9"]
    assert disconnect_ids == [
        "D6",
        "D7",
        "D8",
        "D9",
        "D10",
        "I2",
        "I4",
        "I6",
        "I8",
        "I10",
    ]
    order = [(case.pair_id, case.repeat) for case in cases]
    assert order == [
        ("D1", 1),
        ("D1", 2),
        ("D1", 3),
        ("D2", 1),
        ("D2", 2),
        ("D6", 1),
        ("D6", 2),
        ("D6", 3),
        ("D7", 1),
        ("D7", 2),
    ]
    assert [c.profile for c in cases[:5]] == ["builder"] * 5
    assert [c.profile for c in cases[5:]] == ["disconnect"] * 5
    assert all(c.cited_fact == "f1" and c.control_fact == "f2" for c in cases)


def test_first_five_eligible_stand_and_discards_count_by_reason() -> None:
    doc = _doc()
    weird = _draft("b-ship", [(["f1", "f2", "f3", "f4", "f5"], [], "All cited here")])
    rows = [
        _r3_row("D1", "base", 1, "not json at all"),
        _r3_row("D1", "base", 2, _draft("b-ship", [])),
        _r3_row("D1", "base", 3, _draft("b-ship", [(["f6"], [], "Feed stuff here")])),
        _r3_row("D2", "base", 1, weird),
        _r3_row("D2", "base", 2, _cited_only("f3")),
        _r3_row("D2", "base", 3, _cited_only("f1")),
        _r3_row("D3", "base", 1, _cited_only("f1")),
        _r3_row("D3", "base", 2, _cited_only("f1")),
        _r3_row("D3", "base", 3, _cited_only("f1")),
        _r3_row("D4", "base", 1, _cited_only("f1")),
        _r3_row("D6", "base", 1, _cited_only("f1", "d-family")),
    ]
    cases = r4_scenario.build_cases(rows, doc)
    builder = [c for c in cases if c.profile == "builder"]
    assert [(c.pair_id, c.repeat) for c in builder] == [
        ("D2", 2),
        ("D2", 3),
        ("D3", 1),
        ("D3", 2),
        ("D3", 3),
    ]
    report = r4_scenario.case_build_report(rows, doc)
    assert report["builder"]["eligible"] == 6
    assert report["builder"]["discards"] == {
        "unparseable": 1,
        "no_fact_cited": 1,
        "only_feed_fact": 1,
        "no_matched_control": 1,
    }
    assert report["disconnect"]["eligible"] == 1
    assert report["disconnect"]["discards"] == {}


def test_cited_fact_is_the_lowest_eligible_id() -> None:
    doc = _doc()
    rows = [
        _r3_row("D1", "base", 1, _draft("b-ship", [(["f3", "f1"], [], "Both cited")])),
        _r3_row(
            "D1",
            "base",
            2,
            _draft("b-ship", [(["f6", "f2"], [], "Feed plus screen")]),
        ),
    ]
    cases = r4_scenario.build_cases(rows, doc)
    assert cases[0].cited_fact == "f1"
    assert cases[1].cited_fact == "f2"


def test_control_skips_facts_cited_by_family() -> None:
    doc = _doc()
    draft = _draft(
        "b-ship",
        [
            (
                ["f1"],
                ["period.last.pushes", "period.last.screen_hours.Work/Programming"],
                "Pushes and programming cited together",
            )
        ],
    )
    cases = r4_scenario.build_cases([_r3_row("D1", "base", 1, draft)], doc)
    assert cases[0].cited_fact == "f1"
    assert cases[0].control_fact == "f3"


def test_control_skips_facts_cited_by_id() -> None:
    doc = _doc()
    draft = _draft("b-ship", [(["f1", "f2"], [], "Two facts cited")])
    cases = r4_scenario.build_cases([_r3_row("D1", "base", 1, draft)], doc)
    assert cases[0].control_fact == "f3"


def test_fact_cited_only_in_not_working_counts_as_cited() -> None:
    doc = _doc()
    raw = _draft(
        "b-ship",
        [(["f1"], [], "Something about f1 holds here")],
        section="not_working",
    )
    assert r4_scenario.cited_facts(r4_scenario.parse_base_draft(raw)) == ["f1"]  # type: ignore[union-attr]
    cases = r4_scenario.build_cases([_r3_row("D1", "base", 1, raw)], doc)
    assert len(cases) == 1
    assert cases[0].cited_fact == "f1"


def test_metric_ref_only_in_working_excludes_control_family() -> None:
    doc = _doc()
    draft = json.dumps(
        {
            "commitment_id": "b-ship",
            "overall_state": [
                {
                    "text": "Pushes carry the week here",
                    "fact_ids": ["f1"],
                    "metric_refs": [],
                }
            ],
            "working": [
                {
                    "text": "Programming context here",
                    "fact_ids": ["f1"],
                    "metric_refs": ["period.last.screen_hours.Work/Programming"],
                }
            ],
            "not_working": [],
            "since_last": [],
        }
    )
    assert "screen_hours.Work/Programming" in r4_scenario.metric_families(
        r4_scenario.parse_base_draft(draft)  # type: ignore[arg-type]
    )
    cases = r4_scenario.build_cases([_r3_row("D1", "base", 1, draft)], doc)
    assert cases[0].cited_fact == "f1"
    assert cases[0].control_fact == "f3"


def test_case_ids_follow_pair_file_order_across_profiles() -> None:
    doc = _doc()
    rows = [
        _r3_row("I1", "base", 1, _cited_only("f1", "b-ship")),
        _r3_row("D6", "base", 1, _cited_only("f1", "d-family")),
    ]
    cases = r4_scenario.build_cases(rows, doc)
    assert [(case.case_id, case.pair_id) for case in cases] == [
        ("r4-01", "D6"),
        ("r4-02", "I1"),
    ]


def test_case_carries_its_provenance() -> None:
    doc = _doc()
    raw = _cited_only("f1")
    cases = r4_scenario.build_cases([_r3_row("D2", "base", 3, raw)], doc)
    assert len(cases) == 1
    case = cases[0]
    assert case.profile == "builder"
    assert case.pair_id == "D2"
    assert case.repeat == 3
    assert case.base_prompt_hash == "p" * 64
    assert case.base_draft_json == raw


def test_first_drawn_execution_stands_for_case_building() -> None:
    doc = _doc()
    rows = [
        _r3_row("D1", "base", 1, _cited_only("f4"), execution=1),
        _r3_row("D1", "base", 1, _cited_only("f1"), execution=2),
    ]
    cases = r4_scenario.build_cases(rows, doc)
    assert len(cases) == 1
    assert cases[0].cited_fact == "f4"


def test_slot_without_a_draw_counts_as_unparseable() -> None:
    doc = _doc()
    rows = [
        _r3_row("D1", "base", 1, "", drawn=False),
        _r3_row("D1", "base", 1, "", execution=2, drawn=False),
    ]
    assert r4_scenario.build_cases(rows, doc) == ()
    report = r4_scenario.case_build_report(rows, doc)
    assert report["builder"]["discards"] == {"unparseable": 1}


def test_perturbed_rows_never_build_cases() -> None:
    doc = _doc()
    rows = [_r3_row("D1", "perturbed", 1, _cited_only("f1"))]
    assert r4_scenario.build_cases(rows, doc) == ()


def _base_scenario(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "slot": doc["slot"],
        "hour": copy.deepcopy(doc["hour"]),
        "commitments": copy.deepcopy(doc["commitments"]),
        "facts": copy.deepcopy(doc["facts"]),
        "metrics": dict(doc["metrics"]),
    }


@pytest.mark.parametrize("fact_id", ["f1", "f2", "f3", "f4", "f5"])
def test_changed_scenario_rewrites_statement_and_metric_together(fact_id: str) -> None:
    doc = _doc()
    changed = r4_scenario.changed_scenario(_base_scenario(doc), fact_id)
    label, family = r4_scenario.FAMILY_BY_FACT[fact_id]
    prior = doc["metrics"][f"period.prior.{family}"]
    expected = f"{label} fell from {prior} in prior to 0 in last."
    statements = {fact["id"]: fact["statement"] for fact in changed["facts"]}
    assert statements[fact_id] == expected
    assert changed["metrics"][f"period.last.{family}"] == 0
    assert [fact["id"] for fact in changed["facts"]] == [
        fact["id"] for fact in doc["facts"]
    ]
    for key, value in doc["metrics"].items():
        if key != f"period.last.{family}":
            assert changed["metrics"][key] == value


def test_changed_statements_match_the_registered_phrasing() -> None:
    doc = _doc()
    changed_f1 = r4_scenario.changed_scenario(_base_scenario(doc), "f1")
    changed_f5 = r4_scenario.changed_scenario(_base_scenario(doc), "f5")
    by_id_f1 = {f["id"]: f["statement"] for f in changed_f1["facts"]}
    by_id_f5 = {f["id"]: f["statement"] for f in changed_f5["facts"]}
    assert by_id_f1["f1"] == "Pushes fell from 2 in prior to 0 in last."
    assert (
        by_id_f5["f5"] == "iki-family calendar hours fell from 1 in prior to 0 in last."
    )


def _gate_shell(
    arm: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """The same gate-as-claims check tests/test_r3_pairs.py applies to an arm."""
    from evals.briefing_cases import base_case

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
                for metric_id in _fact_metric_ids(
                    str(fact["statement"]), arm["metrics"]
                )
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
            "evidence": ["synthetic r4 log"],
            "tier": "public",
        }
        for fact in arm["facts"]
    }
    dump = case.context.model_dump(mode="python")
    dump["facts"] = {**dump["facts"], **facts}
    dump["metrics"] = {"values": dict(arm["metrics"])}
    context = type(case.context).model_validate(dump)
    return briefing, context


def _fact_metric_ids(statement: str, metrics: dict[str, Any]) -> list[str]:
    import re

    families = {family: label for label, family in r4_scenario.FAMILY_BY_FACT.values()}
    for family, label in families.items():
        if statement.startswith(label):
            ids = []
            for period in ("earlier", "prior", "last"):
                if re.search(rf"\b{period}\b", statement):
                    ids.append(f"period.{period}.{family}")
            assert ids, statement
            return ids
    if "feed items" in statement:
        return ["feed.item.count"]
    pytest.fail(f"statement matches no metric family: {statement!r}")


@pytest.mark.parametrize("fact_id", ["f1", "f2", "f3", "f4", "f5"])
def test_every_changed_scenario_passes_the_gate_as_claims(fact_id: str) -> None:
    from framework.briefing.gate import evaluate_briefing

    doc = _doc()
    changed = r4_scenario.changed_scenario(_base_scenario(doc), fact_id)
    briefing, context = _gate_shell(changed)
    result = evaluate_briefing(briefing, context)
    assert result.violations == (), (fact_id, result.violations)


def test_changed_scenarios_use_the_same_ops_as_r3_arms() -> None:
    doc = _doc()
    changed = r4_scenario.changed_scenario(_base_scenario(doc), "f1")
    via_ops = apply_ops(
        _base_scenario(doc),
        [
            {
                "op": "set_fact",
                "id": "f1",
                "statement": changed["facts"][0]["statement"],
            },
            {"op": "set_metric", "id": "period.last.pushes", "value": 0},
        ],
    )
    assert changed == via_ops
