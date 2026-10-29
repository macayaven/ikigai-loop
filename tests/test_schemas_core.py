"""Ticket 3: Fact/Profile/Criterion/Manifest/BlockConfig/Decision tests."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from framework.schemas import (
    BlockConfig,
    Criterion,
    Decision,
    Fact,
    Manifest,
    Profile,
)

NOW = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)


def make_fact(**overrides: object) -> Fact:
    raw: dict[str, object] = {
        "id": "fact_synthetic_1",
        "subject_id": "subject-1",
        "window": {"start": NOW, "end": LATER},
        "statement": "Synthetic fact statement.",
        "evidence": ["evt_synthetic_1"],
        "tier": "private",
    }
    raw.update(overrides)
    return Fact.model_validate(raw)


def make_profile(weights: dict[str, float] | None = None) -> Profile:
    return Profile.model_validate(
        {
            "subject_id": "subject-1",
            "profile_id": "profile-a",
            "label": "Synthetic profile",
            "version": 1,
            "weights": weights
            or {"love": 0.25, "good_at": 0.25, "world_needs": 0.25, "paid_for": 0.25},
        }
    )


def make_manifest() -> Manifest:
    return Manifest.model_validate(
        {
            "version": "synthetic-v2",
            "parent": "synthetic-v1",
            "layout": ["checklist#synthetic"],
            "blocks": {
                "checklist#synthetic": {
                    "type": "checklist",
                    "dimension": "love",
                    "config": {"label": "Synthetic"},
                    "rationale": "Synthetic rationale.",
                }
            },
            "changelog": [
                {
                    "from": "synthetic-v1",
                    "change": "added checklist#synthetic",
                    "why": "Synthetic reason.",
                    "evidence": ["fact_synthetic_1"],
                }
            ],
        }
    )


def test_fact_round_trip() -> None:
    fact = make_fact()
    assert Fact.model_validate(fact.model_dump()) == fact
    assert Fact.model_validate_json(fact.model_dump_json()) == fact


def test_profile_round_trip() -> None:
    profile = make_profile(
        {"love": 0.30, "good_at": 0.30, "world_needs": 0.30, "paid_for": 0.10}
    )
    assert Profile.model_validate(profile.model_dump()) == profile
    assert Profile.model_validate_json(profile.model_dump_json()) == profile


def test_criterion_round_trip() -> None:
    criterion = Criterion.model_validate(
        {
            "id": "crit_synthetic_1",
            "profile_id": "profile-a",
            "dimension": "limit",
            "text": "No synthetic block proposes an unavailable slot.",
            "hidden": False,
            "version": 1,
        }
    )
    assert Criterion.model_validate(criterion.model_dump()) == criterion
    contrast = criterion.model_copy(update={"dimension": "contrast"})
    assert contrast.dimension == "contrast"


def test_manifest_and_block_config_round_trip() -> None:
    manifest = make_manifest()
    assert Manifest.model_validate(manifest.model_dump(by_alias=True)) == manifest
    assert (
        Manifest.model_validate_json(manifest.model_dump_json(by_alias=True))
        == manifest
    )
    block = BlockConfig.model_validate({"type": "checklist", "dimension": "love"})
    assert block.config == {}
    assert BlockConfig.model_validate(block.model_dump()) == block


def test_decision_round_trip() -> None:
    manifest = make_manifest()
    decision = Decision.model_validate(
        {
            "kind": "evolve",
            "rationale": "Synthetic rationale.",
            "evidence": ["fact_synthetic_1"],
            "manifest_diff": {
                "base_version": "synthetic-v1",
                "candidate": manifest.model_dump(by_alias=True),
            },
        }
    )
    assert Decision.model_validate(decision.model_dump()) == decision
    noop = Decision.model_validate(
        {"kind": "noop", "rationale": "", "evidence": [], "manifest_diff": None}
    )
    assert noop.kind == "noop"


def test_reject_fact_without_evidence() -> None:
    with pytest.raises(ValidationError):
        make_fact(evidence=[])


def test_reject_weights_not_summing_to_one() -> None:
    with pytest.raises(ValidationError):
        make_profile({"love": 0.3, "good_at": 0.3, "world_needs": 0.2, "paid_for": 0.1})


def test_reject_weight_out_of_range() -> None:
    with pytest.raises(ValidationError):
        make_profile({"love": 1.5, "good_at": 0.0, "world_needs": 0.0, "paid_for": 0.0})


def test_reject_inverted_fact_window() -> None:
    with pytest.raises(ValidationError):
        make_fact(window={"start": LATER, "end": NOW})


def test_reject_evolve_without_diff() -> None:
    with pytest.raises(ValidationError):
        Decision.model_validate(
            {
                "kind": "evolve",
                "rationale": "x",
                "evidence": ["fact_synthetic_1"],
                "manifest_diff": None,
            }
        )


def test_reject_diff_on_noop() -> None:
    manifest = make_manifest()
    with pytest.raises(ValidationError):
        Decision.model_validate(
            {
                "kind": "noop",
                "rationale": "",
                "evidence": [],
                "manifest_diff": {
                    "base_version": "synthetic-v1",
                    "candidate": manifest.model_dump(by_alias=True),
                },
            }
        )


def test_reject_changelog_without_evidence() -> None:
    with pytest.raises(ValidationError):
        Manifest.model_validate(
            {
                "version": "synthetic-v1",
                "parent": None,
                "layout": [],
                "blocks": {},
                "changelog": [{"change": "x", "why": "y", "evidence": []}],
            }
        )


def test_reject_extra_fields_on_core_models() -> None:
    with pytest.raises(ValidationError):
        Fact.model_validate({**make_fact().model_dump(), "unexpected": 1})
    with pytest.raises(ValidationError):
        Profile.model_validate({**make_profile().model_dump(), "unexpected": 1})
