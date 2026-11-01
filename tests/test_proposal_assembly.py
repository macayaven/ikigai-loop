"""Ticket 11: briefing assembly from a narrow draft."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from evals.proposal_cases import BASE_ELIGIBLE, BASE_FACTS
from framework.briefing.context import GateContext, MetricSnapshot, TimeInterval
from framework.briefing.gate import evaluate_briefing
from framework.proposal.assembly import assemble_briefing
from framework.proposal.hour import allowed_windows
from framework.proposal.prompt import compute_deltas
from framework.proposal.schemas import ProposalDraft, parse_draft

MADRID = ZoneInfo("Europe/Madrid")
SLOT = datetime(2026, 10, 31, 15, 7, 0, tzinfo=MADRID)
HOUR = TimeInterval(
    start=datetime(2026, 10, 31, 15, 15, 0, tzinfo=MADRID),
    end=datetime(2026, 10, 31, 16, 15, 0, tzinfo=MADRID),
)
SNAPSHOT = {
    "calendar.busy_hours": 2.5,
    "period.earlier.pushes": 1.0,
    "period.prior.pushes": 2.0,
    "period.last.pushes": 3.0,
}


def _draft(payload: dict) -> ProposalDraft:  # type: ignore[no-untyped-def]
    draft = parse_draft(
        json.dumps(payload), has_facts=True, has_metrics=True, has_parent=False
    )
    assert isinstance(draft, ProposalDraft)
    return draft


def _good_payload() -> dict:  # type: ignore[no-untyped-def]
    return {
        "commitment_id": "cm-builder-parser",
        "overall_state": [
            {
                "text": "Pushes were 3 in last",
                "fact_ids": [],
                "metric_refs": ["period.last.pushes"],
            }
        ],
        "working": [
            {
                "text": "The synthetic focus session finished yesterday",
                "fact_ids": ["fact:synthetic-1"],
                "metric_refs": [],
            }
        ],
        "not_working": [],
    }


def test_code_filled_fields_and_ids() -> None:
    briefing = assemble_briefing(
        _draft(_good_payload()),
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT,
        parent=None,
        commitments_by_id={c.id: c for c in BASE_ELIGIBLE},
        snapshot=SNAPSHOT,
        parent_snapshot=None,
        deltas={},
        hour=HOUR,
    )
    assert briefing.id.startswith("brf-builder-20261031T140700Z-")
    assert briefing.profile_id == "builder"
    assert briefing.parent_briefing_id is None
    types = [section.type for section in briefing.sections]
    assert types == ["overall_state", "working", "not_working", "actions"]
    claim_ids = [claim.id for section in briefing.sections for claim in section.claims]
    assert claim_ids == ["c-overall_state-1", "c-working-1"]
    (action_section,) = [
        section for section in briefing.sections if section.type == "actions"
    ]
    (action,) = action_section.actions
    assert action.id == "act-1"
    assert action.commitment_id == "cm-builder-parser"
    assert action.kind == "build"
    assert action.text == "Build the synthetic parser sketch"
    assert action.dimension == "good_at"
    assert action.proposed_start == HOUR.start
    assert action.proposed_end == HOUR.end


def test_dedupe_keeps_order() -> None:
    payload = _good_payload()
    payload["overall_state"][0]["fact_ids"] = [
        "fact:synthetic-1",
        "fact:synthetic-1",
    ]
    payload["overall_state"][0]["metric_refs"] = [
        "period.last.pushes",
        "period.last.pushes",
    ]
    briefing = assemble_briefing(
        _draft(payload),
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT,
        parent=None,
        commitments_by_id={c.id: c for c in BASE_ELIGIBLE},
        snapshot=SNAPSHOT,
        parent_snapshot=None,
        deltas={},
        hour=HOUR,
    )
    claim = briefing.sections[0].claims[0]
    assert claim.fact_ids == ["fact:synthetic-1"]
    assert [ref.metric_id for ref in claim.metric_refs] == ["period.last.pushes"]


def test_full_precision_refs_pass_gate_with_rounded_sentence() -> None:
    from evals.proposal_cases import LIMITS

    snapshot = dict(SNAPSHOT)
    snapshot["period.last.screen_hours.video"] = 1.75
    payload = _good_payload()
    payload["overall_state"].append(
        {
            "text": "Video was 1.8 in last",
            "fact_ids": [],
            "metric_refs": ["period.last.screen_hours.video"],
        }
    )
    draft = parse_draft(
        json.dumps(payload), has_facts=True, has_metrics=True, has_parent=False
    )
    assert isinstance(draft, ProposalDraft)
    briefing = assemble_briefing(
        draft,
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT,
        parent=None,
        commitments_by_id={c.id: c for c in BASE_ELIGIBLE},
        snapshot=snapshot,
        parent_snapshot=None,
        deltas={},
        hour=HOUR,
    )
    ref = briefing.sections[0].claims[1].metric_refs[0]
    assert ref.value == 1.75
    context = GateContext(
        facts={fact.id: fact for fact in BASE_FACTS},
        metrics=MetricSnapshot(values=snapshot),
        limits=LIMITS,
        free_intervals=allowed_windows(SLOT, LIMITS),
        busy_intervals=(),
        private_terms=(),
        private_terms_available=True,
        commitments=tuple(BASE_ELIGIBLE),
        commitments_available=True,
    )
    assert evaluate_briefing(briefing, context).passed


def test_unknown_ids_become_gate_violations() -> None:
    from evals.proposal_cases import LIMITS

    payload = _good_payload()
    payload["commitment_id"] = "cm-unknown-9"
    payload["overall_state"][0]["metric_refs"] = ["period.last.nope"]
    briefing = assemble_briefing(
        _draft(payload),
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT,
        parent=None,
        commitments_by_id={c.id: c for c in BASE_ELIGIBLE},
        snapshot=SNAPSHOT,
        parent_snapshot=None,
        deltas={},
        hour=HOUR,
    )
    (action_section,) = [
        section for section in briefing.sections if section.type == "actions"
    ]
    assert action_section.actions[0].kind == "plan"
    assert action_section.actions[0].dimension == "limit"
    context = GateContext(
        facts={fact.id: fact for fact in BASE_FACTS},
        metrics=MetricSnapshot(values=dict(SNAPSHOT)),
        limits=LIMITS,
        free_intervals=allowed_windows(SLOT, LIMITS),
        busy_intervals=(),
        private_terms=(),
        private_terms_available=True,
        commitments=tuple(BASE_ELIGIBLE),
        commitments_available=True,
    )
    codes = {
        (v.code, v.location) for v in evaluate_briefing(briefing, context).violations
    }
    assert (
        "L1_ACTION_NOT_COMMITTED",
        "sections[actions].actions[act-1]",
    ) in codes


def test_delta_offer_rule_and_offered_deltas_pass_gate() -> None:
    assert compute_deltas({"m": 143.0 / 60.0}, {"m": 7.0 / 60.0}) == ()
    offered = compute_deltas({"m": 1.5}, {"m": 1.25})
    assert [d.metric_id for d in offered] == ["m"]
    assert offered[0].value == 0.25
    offered = compute_deltas({"m": 3.0}, {"m": 1.0})
    assert offered[0].value == 2.0


def test_parent_arms() -> None:
    from evals.proposal_cases import LIMITS
    from framework.briefing.schemas import Briefing

    parent = Briefing(
        id="brf-builder-parent",
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT - timedelta(hours=24),
        sections=[],
    )
    parent_snapshot = {"period.last.pushes": 2.0}
    deltas = {
        delta.metric_id: delta.value
        for delta in compute_deltas(dict(SNAPSHOT), parent_snapshot)
    }
    assert deltas == {"period.last.pushes": 1.0}
    payload = _good_payload()
    payload["since_last"] = [
        {
            "text": "Pushes rose 1 in last",
            "fact_ids": [],
            "metric_refs": ["period.last.pushes"],
        }
    ]
    draft = parse_draft(
        json.dumps(payload), has_facts=True, has_metrics=True, has_parent=True
    )
    assert isinstance(draft, ProposalDraft)
    briefing = assemble_briefing(
        draft,
        profile_id="builder",
        subject_id="subject-1",
        slot=SLOT,
        parent=parent,
        commitments_by_id={c.id: c for c in BASE_ELIGIBLE},
        snapshot=dict(SNAPSHOT),
        parent_snapshot=parent_snapshot,
        deltas=deltas,
        hour=HOUR,
    )
    assert briefing.parent_briefing_id == "brf-builder-parent"
    types = [section.type for section in briefing.sections]
    assert types == [
        "overall_state",
        "since_last",
        "working",
        "not_working",
        "actions",
    ]
    context = GateContext(
        facts={fact.id: fact for fact in BASE_FACTS},
        metrics=MetricSnapshot(values=dict(SNAPSHOT)),
        parent_briefing=parent,
        parent_metrics=MetricSnapshot(values=parent_snapshot),
        limits=LIMITS,
        free_intervals=allowed_windows(SLOT, LIMITS),
        busy_intervals=(),
        private_terms=(),
        private_terms_available=True,
        commitments=tuple(BASE_ELIGIBLE),
        commitments_available=True,
    )
    assert evaluate_briefing(briefing, context).passed
