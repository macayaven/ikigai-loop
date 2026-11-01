"""Ticket 15a: round trips and rejections for every learner schema."""

from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from framework.learner.schemas import (
    BUCKETS,
    BucketState,
    CommitmentState,
    PickLogEntry,
    PolicyChange,
    PolicyState,
    Prediction,
    PredictorReport,
    PredictorScore,
    ProfileId,
    Proposal,
    RankedCommitment,
    RecoverCell,
    RecoverTable,
    Ruling,
    ScoreEntry,
    ScoreReport,
    Target,
)

SLOT = datetime(2026, 1, 2, 18, 0, tzinfo=UTC)


def _proposal(
    label: Literal["A", "B"] = "A",
    profile: ProfileId = "builder",
    commitment: str = "b-1",
    pick: str = "b-1",
    alternative: str | None = None,
) -> Proposal:
    return Proposal(
        label=label,
        profile_id=profile,
        commitment_id=commitment,
        policy_pick=pick,
        policy_alternative=alternative,
    )


def _two_proposals() -> tuple[Proposal, Proposal]:
    return (
        _proposal("A", "builder", "b-1", "b-1", "b-2"),
        _proposal("B", "disconnect", "d-1", "d-1", "d-2"),
    )


def _ruling(target: Target = "A") -> Ruling:
    return Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=_two_proposals(),
        target=target,
    )


def test_proposal_round_trip() -> None:
    p = _proposal()
    assert Proposal.model_validate_json(p.model_dump_json()) == p


def test_ruling_round_trip_all_targets() -> None:
    targets: tuple[Target, ...] = ("A", "B", "neither", "wrong", "why")
    for target in targets:
        r = _ruling(target)
        assert Ruling.model_validate_json(r.model_dump_json()) == r


def test_ruling_rejects_empty_proposals() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(),
            target="A",
        )


def test_ruling_rejects_three_proposals() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=_two_proposals() + (_proposal("A", "builder", "b-2"),),
            target="A",
        )


def test_ruling_rejects_lone_label_b() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(_proposal("B", "disconnect", "d-1"),),
            target="A",
        )


def test_ruling_rejects_double_label_a() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(
                _proposal("A", "builder", "b-1"),
                _proposal("A", "disconnect", "d-1"),
            ),
            target="A",
        )


def test_ruling_rejects_same_profile_twice() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(
                _proposal("A", "builder", "b-1"),
                _proposal("B", "builder", "b-2"),
            ),
            target="A",
        )


def test_ruling_rejects_same_commitment_twice() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(
                _proposal("A", "builder", "b-1"),
                _proposal("B", "disconnect", "b-1"),
            ),
            target="A",
        )


def test_ruling_rejects_target_b_on_lone_card() -> None:
    with pytest.raises(ValidationError):
        Ruling(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            proposals=(_proposal("A", "builder", "b-1"),),
            target="B",
        )


def test_ruling_rejects_bad_target_value() -> None:
    with pytest.raises(ValidationError):
        Ruling.model_validate(
            {
                "card_id": "card-001",
                "slot": SLOT,
                "bucket": "evening",
                "proposals": [p.model_dump(mode="json") for p in _two_proposals()],
                "target": "C",
            }
        )


def test_bucket_state_defaults_and_round_trip() -> None:
    b = BucketState()
    assert (b.alpha, b.beta) == (1, 1)
    assert (b.neither, b.wrong, b.why, b.single_taken) == (0, 0, 0, 0)
    assert BucketState.model_validate_json(b.model_dump_json()) == b


def test_bucket_state_rejects_alpha_zero() -> None:
    with pytest.raises(ValidationError):
        BucketState(alpha=0)


def test_bucket_state_rejects_beta_zero() -> None:
    with pytest.raises(ValidationError):
        BucketState(beta=0)


def test_bucket_state_rejects_negative_counts() -> None:
    with pytest.raises(ValidationError):
        BucketState(neither=-1)


def test_commitment_state_round_trip() -> None:
    c = CommitmentState(
        profile_id="builder",
        offered=3,
        taken=2,
        declined=1,
        last_offered_slot=SLOT,
    )
    assert CommitmentState.model_validate_json(c.model_dump_json()) == c


def test_commitment_state_rejects_taken_plus_declined_over_offered() -> None:
    with pytest.raises(ValidationError):
        CommitmentState(
            profile_id="builder",
            offered=2,
            taken=2,
            declined=1,
            last_offered_slot=SLOT,
        )


def test_predictor_score_round_trip() -> None:
    s = PredictorScore(prediction=0.5, brier=0.25, log_loss=0.69314718056)
    assert PredictorScore.model_validate_json(s.model_dump_json()) == s


def test_predictor_score_rejects_out_of_range_prediction() -> None:
    with pytest.raises(ValidationError):
        PredictorScore(prediction=1.5, brier=0.25, log_loss=0.5)


def test_predictor_score_rejects_non_finite() -> None:
    with pytest.raises(ValidationError):
        PredictorScore(prediction=0.5, brier=float("inf"), log_loss=0.5)
    with pytest.raises(ValidationError):
        PredictorScore(prediction=float("nan"), brier=0.25, log_loss=0.5)


def _score(predicted: float = 0.5) -> PredictorScore:
    return PredictorScore(prediction=predicted, brier=0.25, log_loss=0.69314718056)


def test_score_entry_round_trip() -> None:
    e = ScoreEntry(
        card_id="card-001",
        bucket="evening",
        outcome=1,
        learner=_score(0.5),
        always_half=_score(0.5),
        majority=_score(0.5),
        pooled_rate=_score(0.5),
    )
    assert ScoreEntry.model_validate_json(e.model_dump_json()) == e


def test_score_entry_rejects_bad_outcome() -> None:
    with pytest.raises(ValidationError):
        ScoreEntry.model_validate(
            {
                "card_id": "card-001",
                "bucket": "evening",
                "outcome": 2,
                "learner": _score().model_dump(mode="json"),
                "always_half": _score().model_dump(mode="json"),
                "majority": _score().model_dump(mode="json"),
                "pooled_rate": _score().model_dump(mode="json"),
            }
        )


def test_pick_log_entry_round_trip() -> None:
    e = PickLogEntry(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        profile_id="builder",
        offered="b-1",
        pick="b-1",
        alternative="b-2",
        label="A",
    )
    assert PickLogEntry.model_validate_json(e.model_dump_json()) == e


def test_pick_log_entry_rejects_bad_label() -> None:
    with pytest.raises(ValidationError):
        PickLogEntry(
            card_id="card-001",
            slot=SLOT,
            bucket="evening",
            profile_id="builder",
            offered="b-1",
            pick="b-1",
            alternative="b-2",
            label="C",  # type: ignore[arg-type]
        )


def test_policy_state_json_rejects_alpha_zero() -> None:
    import json as _json

    from framework.learner.policy import initial_state, state_json

    text = _json.loads(state_json(initial_state()))
    text["buckets"]["evening"]["alpha"] = 0
    with pytest.raises(ValidationError):
        PolicyState.model_validate_json(
            _json.dumps(text, sort_keys=True, separators=(",", ":"))
        )


def test_policy_state_rejects_wrong_bucket_keys() -> None:
    with pytest.raises(ValidationError):
        PolicyState.model_validate(
            {
                "buckets": {
                    "afternoon": BucketState().model_dump(mode="json"),
                    "evening": BucketState().model_dump(mode="json"),
                },
            }
        )
    with pytest.raises(ValidationError):
        PolicyState.model_validate(
            {
                "buckets": {
                    "afternoon": BucketState().model_dump(mode="json"),
                    "evening": BucketState().model_dump(mode="json"),
                    "night": BucketState().model_dump(mode="json"),
                    "dawn": BucketState().model_dump(mode="json"),
                },
            }
        )


def test_policy_state_round_trip() -> None:
    s = PolicyState(buckets={b: BucketState() for b in BUCKETS})
    assert PolicyState.model_validate_json(s.model_dump_json()) == s


def test_policy_state_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        PolicyState(
            buckets={b: BucketState() for b in BUCKETS},
            no_such_field=1,  # type: ignore[call-arg]
        )


def test_policy_state_is_frozen() -> None:
    s = PolicyState(buckets={b: BucketState() for b in BUCKETS})
    with pytest.raises(ValidationError):
        s.rulings_seen = 1  # type: ignore[misc]


def test_report_types_round_trip() -> None:
    rep = PredictorReport(
        mean_brier=0.25, mean_log_loss=0.69, correct=1, wrong=2, no_call=3
    )
    assert PredictorReport.model_validate_json(rep.model_dump_json()) == rep
    full = ScoreReport(
        n=6,
        learner=rep,
        always_half=rep,
        majority=rep,
        pooled_rate=rep,
    )
    assert ScoreReport.model_validate_json(full.model_dump_json()) == full
    pred = Prediction(learner=0.5, always_half=0.5, majority=0.5, pooled_rate=0.5)
    assert Prediction.model_validate_json(pred.model_dump_json()) == pred
    with pytest.raises(ValidationError):
        Prediction(learner=2.0, always_half=0.5, majority=0.5, pooled_rate=0.5)


def test_ranked_commitment_and_policy_change_round_trip() -> None:
    r = RankedCommitment(
        commitment_id="b-1",
        position=1,
        role="pick",
        profile_id="builder",
        bucket="evening",
        offered=1,
        taken=1,
        declined=0,
        smoothed_rate=2 / 3,
        reason="only candidate: 2/3",
    )
    assert RankedCommitment.model_validate_json(r.model_dump_json()) == r
    c = PolicyChange(path="buckets.evening.alpha", kind="changed", before=1, after=2)
    assert PolicyChange.model_validate_json(c.model_dump_json()) == c


def test_recover_types_round_trip() -> None:
    cell = RecoverCell(
        true_p=0.7,
        n_cards=13,
        n_sims=500,
        seed=1,
        correct_side=0.9,
        mean_absolute_error=0.09,
        coverage=0.97,
        mean_interval_width=0.43,
    )
    assert RecoverCell.model_validate_json(cell.model_dump_json()) == cell
    table = RecoverTable(seed=1, n_sims=500, note="n/a", cells=(cell,))
    assert RecoverTable.model_validate_json(table.model_dump_json()) == table
    assert table.label == "simulated"
