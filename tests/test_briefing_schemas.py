"""Ticket 8: briefing + context schema round-trips and pinned rejections."""

import copy
from datetime import datetime, time

import pytest
from pydantic import ValidationError

from evals.briefing_cases import base_case
from framework.briefing.context import (
    GateContext,
    MetricSnapshot,
    ProfileLimits,
    TimeInterval,
    load_private_terms,
)
from framework.briefing.schemas import (
    Action,
    Briefing,
    Claim,
    MetricRef,
    Section,
)


def _valid_briefing_dict() -> dict:
    return copy.deepcopy(base_case("builder").briefing)


def test_briefing_models_round_trip() -> None:
    briefing = Briefing.model_validate(_valid_briefing_dict())
    assert Briefing.model_validate(briefing.model_dump(mode="json")) == briefing


def test_section_claim_action_metric_ref_round_trip() -> None:
    section = Section.model_validate(_valid_briefing_dict()["sections"][0])
    assert Section.model_validate(section.model_dump(mode="json")) == section
    claim = Claim(
        id="claim-x",
        text="Synthetic claim",
        fact_ids=["fact:synthetic-1"],
        metric_refs=[MetricRef(metric_id="agg.tasks_done", value=3.0)],
    )
    assert Claim.model_validate(claim.model_dump(mode="json")) == claim
    action = Action(
        id="act-x",
        commitment_id="cm-builder-parser",
        kind="build",
        text="Build the synthetic thing",
        dimension="good_at",
        proposed_start=datetime.fromisoformat("2026-10-31T14:00:00+01:00"),
        proposed_end=datetime.fromisoformat("2026-10-31T15:00:00+01:00"),
    )
    assert Action.model_validate(action.model_dump(mode="json")) == action


def test_context_models_round_trip() -> None:
    context = base_case("builder").context
    assert GateContext.model_validate(context.model_dump(mode="json")) == context
    assert context.check_slot is True


def test_check_slot_false_round_trips() -> None:
    context = base_case("builder").context.model_copy(update={"check_slot": False})
    assert context.check_slot is False
    assert GateContext.model_validate(context.model_dump(mode="json")) == context


def test_metric_snapshot_empty_is_valid() -> None:
    assert MetricSnapshot(values={}).values == {}


def test_extra_field_rejected() -> None:
    raw = _valid_briefing_dict()
    raw["sections"][0]["claims"][0]["proof"] = "nope"
    with pytest.raises(ValidationError):
        Briefing.model_validate(raw)


def test_unknown_action_kind_rejected() -> None:
    raw = _valid_briefing_dict()
    raw["sections"][3]["actions"][0]["kind"] = "teleport"
    with pytest.raises(ValidationError):
        Briefing.model_validate(raw)


def test_unknown_section_type_rejected_by_schema() -> None:
    raw = _valid_briefing_dict()
    raw["sections"][1]["type"] = "mystery"
    with pytest.raises(ValidationError):
        Briefing.model_validate(raw)


def test_naive_slot_rejected() -> None:
    raw = _valid_briefing_dict()
    raw["slot"] = "2026-10-31T13:00:00"
    with pytest.raises(ValidationError):
        Briefing.model_validate(raw)


def test_action_end_before_start_rejected() -> None:
    raw = _valid_briefing_dict()
    action = raw["sections"][3]["actions"][0]
    action["proposed_start"] = "2026-10-31T15:00:00+01:00"
    action["proposed_end"] = "2026-10-31T14:00:00+01:00"
    with pytest.raises(ValidationError):
        Briefing.model_validate(raw)


def test_non_finite_metric_value_rejected() -> None:
    with pytest.raises(ValidationError):
        MetricRef(metric_id="agg.tasks_done", value=float("nan"))
    with pytest.raises(ValidationError):
        MetricSnapshot(values={"agg.tasks_done": float("inf")})


def test_profile_limits_window_must_be_same_day() -> None:
    with pytest.raises(ValidationError):
        ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start="23:30:00",  # type: ignore[arg-type]
            allowed_end="13:00:00",  # type: ignore[arg-type]
        )


def test_profile_limits_max_actions_bounds() -> None:
    with pytest.raises(ValidationError):
        ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start="13:00:00",  # type: ignore[arg-type]
            allowed_end="23:30:00",  # type: ignore[arg-type]
            max_actions=0,
        )
    with pytest.raises(ValidationError):
        ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start="13:00:00",  # type: ignore[arg-type]
            allowed_end="23:30:00",  # type: ignore[arg-type]
            max_actions=4,
        )


def test_profile_limits_unknown_timezone_rejected() -> None:
    with pytest.raises(ValueError):
        ProfileLimits(
            timezone="Nowhere/Unknown",
            allowed_start="13:00:00",  # type: ignore[arg-type]
            allowed_end="23:30:00",  # type: ignore[arg-type]
        )


def test_gate_context_facts_key_must_match_id() -> None:
    context = base_case("builder").context
    facts = dict(context.model_dump(mode="json")["facts"])
    first_key = next(iter(facts))
    facts["fact:renamed"] = facts.pop(first_key)
    with pytest.raises(ValidationError):
        GateContext.model_validate({**context.model_dump(), "facts": facts})


def test_gate_context_parent_pair_half_present_rejected() -> None:
    context = base_case("builder").context
    raw = context.model_dump()
    raw["parent_metrics"] = {"values": {}}
    with pytest.raises(ValidationError):
        GateContext.model_validate(raw)


def test_time_interval_end_must_exceed_start() -> None:
    with pytest.raises(ValidationError):
        TimeInterval(
            start="2026-10-31T15:00:00+01:00",  # type: ignore[arg-type]
            end="2026-10-31T15:00:00+01:00",  # type: ignore[arg-type]
        )


def test_load_private_terms_missing_env_needs_test_flag() -> None:
    assert load_private_terms({}).available is False
    assert load_private_terms({}, allow_missing_for_tests=True).available is True


def test_gate_context_terms_unavailable_by_default() -> None:
    context = GateContext(
        facts={},
        metrics=MetricSnapshot(values={}),
        limits=ProfileLimits(
            timezone="Europe/Madrid",
            allowed_start=time(13, 0),
            allowed_end=time(23, 30),
        ),
    )
    assert context.private_terms_available is False


def test_action_requires_commitment_id() -> None:
    with pytest.raises(ValidationError):
        Action.model_validate(
            {
                "id": "act-x",
                "kind": "build",
                "text": "Build the synthetic thing",
                "dimension": "good_at",
                "proposed_start": "2026-10-31T14:00:00+01:00",
                "proposed_end": "2026-10-31T15:00:00+01:00",
            }
        )
