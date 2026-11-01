"""Ticket 15a: frozen scores, blindness, log gating, replay bytes."""

import json
import math
import os
import subprocess
import sys
from datetime import UTC, datetime
from fractions import Fraction
from typing import Literal

from framework.learner.policy import initial_state, state_json, update
from framework.learner.schemas import (
    Bucket,
    PolicyState,
    ProfileId,
    Proposal,
    Ruling,
    Target,
)
from framework.learner.scoring import (
    observe,
    predict,
    replay,
    score_before_update,
    score_report,
)

SLOT = datetime(2026, 1, 2, 18, 0, tzinfo=UTC)
AFTERNOON_SLOT = datetime(2026, 1, 3, 14, 0, tzinfo=UTC)


def _prop(label: Literal["A", "B"], profile: ProfileId, commitment: str) -> Proposal:
    return Proposal(
        label=label,
        profile_id=profile,
        commitment_id=commitment,
        policy_pick=commitment,
        policy_alternative=None,
    )


def _ruling(
    card: str,
    slot: datetime,
    bucket: Bucket,
    target: Target,
    n: int = 0,
) -> Ruling:
    tag = "" if n == 0 else f"-{n}"
    return Ruling(
        card_id=card,
        slot=slot,
        bucket=bucket,
        proposals=(
            _prop("A", "builder", f"b-1{tag}"),
            _prop("B", "disconnect", f"d-1{tag}"),
        ),
        target=target,
    )


def _frozen_rulings() -> list[Ruling]:
    return [
        _ruling("card-001", SLOT, "evening", "A", 1),
        _ruling("card-002", SLOT, "evening", "A", 2),
        _ruling("card-003", AFTERNOON_SLOT, "afternoon", "B", 3),
        _ruling("card-004", SLOT, "evening", "B", 4),
    ]


def _scored_state() -> PolicyState:
    return replay(initial_state(), _frozen_rulings())


def test_frozen_table_rows() -> None:
    state = _scored_state()
    assert len(state.score_log) == 4
    learner = [
        (e.learner.prediction, e.learner.brier, e.learner.log_loss)
        for e in state.score_log
    ]
    assert learner[0] == (0.5, 0.25, 0.69314718056)
    assert learner[1] == (0.666666666667, 0.111111111111, 0.405465108108)
    assert learner[2] == (0.5, 0.25, 0.69314718056)
    assert learner[3] == (0.75, 0.5625, 1.38629436112)


def test_frozen_table_other_predictors() -> None:
    state = _scored_state()
    half = [(e.always_half.brier, e.always_half.log_loss) for e in state.score_log]
    assert all(h == (0.25, 0.69314718056) for h in half)
    majority = [
        (e.majority.prediction, e.majority.brier, e.majority.log_loss)
        for e in state.score_log
    ]
    assert majority[0] == (0.5, 0.25, 0.69314718056)
    assert majority[1] == (1.0, 0.0, 0.010050335854)
    assert majority[2] == (1.0, 1.0, 4.605170185988)
    assert majority[3] == (1.0, 1.0, 4.605170185988)
    pooled = [
        (e.pooled_rate.prediction, e.pooled_rate.brier, e.pooled_rate.log_loss)
        for e in state.score_log
    ]
    assert pooled[0] == (0.5, 0.25, 0.69314718056)
    assert pooled[1] == (0.666666666667, 0.111111111111, 0.405465108108)
    assert pooled[2] == (0.75, 0.5625, 1.38629436112)
    assert pooled[3] == (0.6, 0.36, 0.916290731874)


def test_frozen_means() -> None:
    report = score_report(_scored_state())
    assert report.n == 4
    lb, ll = report.learner.mean_brier, report.learner.mean_log_loss
    hb, hl = report.always_half.mean_brier, report.always_half.mean_log_loss
    mb, ml = report.majority.mean_brier, report.majority.mean_log_loss
    pb, pl = report.pooled_rate.mean_brier, report.pooled_rate.mean_log_loss
    assert lb is not None and ll is not None
    assert hb is not None and hl is not None
    assert mb is not None and ml is not None
    assert pb is not None and pl is not None
    assert abs(lb - 0.293402777778) < 1e-9
    assert abs(ll - 0.794513457587) < 1e-9
    assert abs(hb - 0.25) < 1e-12
    assert abs(hl - 0.69314718056) < 1e-12
    assert abs(mb - 0.5625) < 1e-12
    assert abs(ml - 2.478384472097) < 1e-9
    assert abs(pb - 0.320902777778) < 1e-9
    assert abs(pl - 0.850299345416) < 1e-9


def test_blind_predictions_ignore_target() -> None:
    state = _scored_state()
    pairs: tuple[tuple[Bucket, str, datetime], ...] = (
        ("evening", "card-010", SLOT),
        ("afternoon", "card-011", AFTERNOON_SLOT),
    )
    for bucket, card, slot in pairs:
        base = _ruling(card, slot, bucket, "A", 10)
        other = base.model_copy(update={"target": "B"})
        entry_a = score_before_update(state, base).score_log[-1]
        entry_b = score_before_update(state, other).score_log[-1]
        want = predict(state, bucket)
        for name in ("learner", "always_half", "majority", "pooled_rate"):
            assert (
                getattr(entry_a, name).prediction == getattr(entry_b, name).prediction
            )
            assert getattr(entry_a, name).prediction == round(getattr(want, name), 12)


def test_frozen_table_builder_outside_evening() -> None:
    state = replay(
        initial_state(),
        [
            _ruling("card-001", AFTERNOON_SLOT, "afternoon", "A", 1),
            _ruling("card-002", SLOT, "evening", "B", 2),
            _ruling("card-003", SLOT, "evening", "A", 3),
        ],
    )
    assert [e.outcome for e in state.score_log] == [1, 0, 1]
    assert len(state.score_log) == 3
    first, second, third = state.score_log
    for entry in (first, second, third):
        assert (
            entry.always_half.prediction,
            entry.always_half.brier,
            entry.always_half.log_loss,
        ) == (0.5, 0.25, 0.69314718056)
    assert (
        first.learner.prediction,
        first.learner.brier,
        first.learner.log_loss,
    ) == (0.5, 0.25, 0.69314718056)
    assert (
        first.majority.prediction,
        first.majority.brier,
        first.majority.log_loss,
    ) == (0.5, 0.25, 0.69314718056)
    assert (
        first.pooled_rate.prediction,
        first.pooled_rate.brier,
        first.pooled_rate.log_loss,
    ) == (0.5, 0.25, 0.69314718056)
    assert (
        second.learner.prediction,
        second.learner.brier,
        second.learner.log_loss,
    ) == (0.5, 0.25, 0.69314718056)
    assert (
        second.majority.prediction,
        second.majority.brier,
        second.majority.log_loss,
    ) == (1.0, 1.0, 4.605170185988)
    assert (
        second.pooled_rate.prediction,
        second.pooled_rate.brier,
        second.pooled_rate.log_loss,
    ) == (0.666666666667, 0.444444444444, 1.098612288668)
    assert (
        third.learner.prediction,
        third.learner.brier,
        third.learner.log_loss,
    ) == (0.333333333333, 0.444444444444, 1.098612288668)
    assert (
        third.majority.prediction,
        third.majority.brier,
        third.majority.log_loss,
    ) == (0.5, 0.25, 0.69314718056)
    assert (
        third.pooled_rate.prediction,
        third.pooled_rate.brier,
        third.pooled_rate.log_loss,
    ) == (0.5, 0.25, 0.69314718056)


def test_blind_predict_reads_the_named_bucket() -> None:
    state = replay(
        initial_state(),
        [
            _ruling("card-001", AFTERNOON_SLOT, "afternoon", "A", 1),
            _ruling("card-002", SLOT, "evening", "A", 2),
        ],
    )
    evening = predict(state, "evening")
    assert evening.learner == float(Fraction(2, 3))
    assert evening.majority == 1.0
    assert evening.pooled_rate == float(Fraction(3, 4))
    night = predict(state, "night")
    assert night.learner == 0.5
    assert night.majority == 1.0
    assert night.pooled_rate == float(Fraction(3, 4))


def test_no_entry_for_non_choice_rulings() -> None:
    for target in ("neither", "wrong", "why"):
        state = observe(
            initial_state(), _ruling("card-001", SLOT, "evening", target, 1)
        )
        assert state.score_log == ()
    lone = Ruling(
        card_id="card-001",
        slot=SLOT,
        bucket="evening",
        proposals=(_prop("A", "builder", "b-1"),),
        target="A",
    )
    assert observe(initial_state(), lone).score_log == ()


def test_no_entry_for_duplicate() -> None:
    first = _ruling("card-001", SLOT, "evening", "A", 1)
    state = observe(initial_state(), first)
    assert len(state.score_log) == 1
    again = observe(state, first)
    assert len(again.score_log) == 1
    assert again.duplicates == 1
    neither_first = observe(
        initial_state(), _ruling("card-001", SLOT, "evening", "neither", 1)
    )
    assert neither_first.score_log == ()
    assert (
        observe(neither_first, _ruling("card-001", SLOT, "evening", "A", 1)).score_log
        == ()
    )


def test_no_entry_for_why_then_exactly_one_for_a() -> None:
    why_first = observe(initial_state(), _ruling("card-001", SLOT, "evening", "why", 1))
    assert why_first.score_log == ()
    after = observe(why_first, _ruling("card-001", SLOT, "evening", "A", 1))
    assert len(after.score_log) == 1


def test_ordering_update_then_score_logs_nothing() -> None:
    ruling = _ruling("card-001", SLOT, "evening", "A", 1)
    state = update(initial_state(), ruling)
    assert score_before_update(state, ruling).score_log == ()


def test_score_before_update_changes_no_counters() -> None:
    ruling = _ruling("card-001", SLOT, "evening", "A", 1)
    before = initial_state()
    after = score_before_update(before, ruling)
    assert len(after.score_log) == 1
    assert after.rulings_seen == before.rulings_seen
    assert after.buckets == before.buckets
    assert after.commitments == before.commitments
    assert after.cards == before.cards


def test_update_alone_adds_no_entry() -> None:
    ruling = _ruling("card-001", SLOT, "evening", "A", 1)
    assert update(initial_state(), ruling).score_log == ()


def test_report_counters_correct_wrong_no_call() -> None:
    report = score_report(_scored_state())
    assert report.n == 4
    assert (
        report.learner.correct,
        report.learner.wrong,
        report.learner.no_call,
    ) == (1, 1, 2)
    assert (
        report.always_half.correct,
        report.always_half.wrong,
        report.always_half.no_call,
    ) == (0, 0, 4)
    assert (
        report.majority.correct,
        report.majority.wrong,
        report.majority.no_call,
    ) == (1, 2, 1)
    assert (
        report.pooled_rate.correct,
        report.pooled_rate.wrong,
        report.pooled_rate.no_call,
    ) == (1, 2, 1)


def _swap_ruling(
    card: str,
    slot: datetime,
    bucket: Bucket,
    target: Target,
    n: int = 0,
) -> Ruling:
    tag = "" if n == 0 else f"-{n}"
    return Ruling(
        card_id=card,
        slot=slot,
        bucket=bucket,
        proposals=(
            _prop("A", "disconnect", f"d-1{tag}"),
            _prop("B", "builder", f"b-1{tag}"),
        ),
        target=target,
    )


def test_report_counters_disconnect_first() -> None:
    state = replay(
        initial_state(),
        [
            _swap_ruling("card-001", SLOT, "evening", "A", 1),
            _swap_ruling("card-002", SLOT, "evening", "B", 2),
        ],
    )
    assert [e.outcome for e in state.score_log] == [0, 1]
    second = state.score_log[1]
    assert (
        second.learner.prediction,
        second.learner.brier,
        second.learner.log_loss,
    ) == (0.333333333333, 0.444444444444, 1.098612288668)
    assert (
        second.majority.prediction,
        second.majority.brier,
        second.majority.log_loss,
    ) == (0.0, 1.0, 4.605170185988)
    assert second.pooled_rate == second.learner
    report = score_report(state)
    for name in ("learner", "majority", "pooled_rate"):
        rep = getattr(report, name)
        assert (rep.correct, rep.wrong, rep.no_call) == (0, 1, 1), name
    assert (
        report.always_half.correct,
        report.always_half.wrong,
        report.always_half.no_call,
    ) == (0, 0, 2)


def test_pooled_equals_learner_single_bucket() -> None:
    rulings = [
        _ruling(f"card-{i:03d}", SLOT, "evening", "A" if i % 2 == 0 else "B", i)
        for i in range(1, 7)
    ]
    state = replay(initial_state(), rulings)
    for entry in state.score_log:
        assert entry.pooled_rate == entry.learner


def test_pooled_majority_side_agreement() -> None:
    for taken_b in range(21):
        for taken_d in range(21):
            rulings: list[Ruling] = []
            for i in range(taken_b):
                rulings.append(
                    _ruling(f"card-b{i:03d}", SLOT, "evening", "A", 1000 + i)
                )
            for i in range(taken_d):
                rulings.append(
                    _ruling(f"card-d{i:03d}", SLOT, "evening", "B", 2000 + i)
                )
            state = replay(initial_state(), rulings)
            pred = predict(state, "evening")
            if pred.majority == 1.0:
                assert pred.pooled_rate > 0.5
            elif pred.majority == 0.0:
                assert pred.pooled_rate < 0.5
            else:
                assert pred.pooled_rate == 0.5


def test_one_sided_stays_inside_unit_interval() -> None:
    rulings = [
        _ruling(f"card-{i:04d}", SLOT, "evening", "A", i) for i in range(1, 2001)
    ]
    probed = observe(
        replay(initial_state(), rulings),
        _ruling("card-9000", SLOT, "evening", "B", 9000),
    )
    entry = probed.score_log[-1]
    assert (entry.learner.prediction, entry.learner.log_loss) == (
        0.9995004995,
        7.601901959875,
    )
    assert (entry.pooled_rate.prediction, entry.pooled_rate.log_loss) == (
        0.9995004995,
        7.601901959875,
    )
    assert (
        entry.majority.prediction,
        entry.majority.brier,
        entry.majority.log_loss,
    ) == (1.0, 1.0, 4.605170185988)

    mirror_rulings = [
        _ruling(f"card-{i:04d}", SLOT, "evening", "B", i) for i in range(1, 2001)
    ]
    mirrored = observe(
        replay(initial_state(), mirror_rulings),
        _ruling("card-9000", SLOT, "evening", "A", 9000),
    )
    mirror = mirrored.score_log[-1]
    assert (mirror.learner.prediction, mirror.learner.log_loss) == (
        0.0004995005,
        7.601901959875,
    )
    assert (mirror.pooled_rate.prediction, mirror.pooled_rate.log_loss) == (
        0.0004995005,
        7.601901959875,
    )
    assert (
        mirror.majority.prediction,
        mirror.majority.brier,
        mirror.majority.log_loss,
    ) == (0.0, 1.0, 4.605170185988)

    for logged in (entry, mirror):
        for name in ("learner", "pooled_rate"):
            scored = getattr(logged, name)
            assert math.isfinite(scored.prediction)
            assert math.isfinite(scored.brier)
            assert math.isfinite(scored.log_loss)
            assert 0.0 < scored.prediction < 1.0


def test_scores_finite_and_json_safe() -> None:
    state = _scored_state()
    text = state_json(state)
    assert "Infinity" not in text
    assert "NaN" not in text
    parsed = json.loads(text)
    for entry in parsed["score_log"]:
        for name in ("learner", "always_half", "majority", "pooled_rate"):
            for field in ("prediction", "brier", "log_loss"):
                value = entry[name][field]
                assert value is not None
                assert math.isfinite(value)


def test_replay_bytes_identical() -> None:
    rulings = _frozen_rulings()
    assert state_json(replay(initial_state(), rulings)) == state_json(
        replay(initial_state(), rulings)
    )


def test_golden_state_json() -> None:
    state = replay(initial_state(), _frozen_rulings())
    assert state_json(state) == (
        '{"buckets":{"afternoon":{"alpha":1,"beta":2,"neither":0,'
        '"single_taken":0,"why":0,"wrong":0},"evening":{"alpha":3,"beta":2,'
        '"neither":0,"single_taken":0,"why":0,"wrong":0},"night":{"alpha":1,'
        '"beta":1,"neither":0,"single_taken":0,"why":0,"wrong":0}},'
        '"cards":{"card-001":"A","card-002":"A","card-003":"B","card-004":"B"},'
        '"commitments":{"b-1-1":{"declined":0,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"builder","taken":1},'
        '"b-1-2":{"declined":0,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"builder","taken":1},'
        '"b-1-3":{"declined":1,"last_offered_slot":"2026-01-03T14:00:00Z",'
        '"offered":1,"profile_id":"builder","taken":0},'
        '"b-1-4":{"declined":1,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"builder","taken":0},'
        '"d-1-1":{"declined":1,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"disconnect","taken":0},'
        '"d-1-2":{"declined":1,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"disconnect","taken":0},'
        '"d-1-3":{"declined":0,"last_offered_slot":"2026-01-03T14:00:00Z",'
        '"offered":1,"profile_id":"disconnect","taken":1},'
        '"d-1-4":{"declined":0,"last_offered_slot":"2026-01-02T18:00:00Z",'
        '"offered":1,"profile_id":"disconnect","taken":1}},'
        '"duplicates":0,"pick_log":[{"alternative":null,"bucket":"evening",'
        '"card_id":"card-001","label":"A","offered":"b-1-1","pick":"b-1-1","profile_id":"builder",'
        '"slot":"2026-01-02T18:00:00Z"},{"alternative":null,"bucket":"evening",'
        '"card_id":"card-001","label":"B","offered":"d-1-1","pick":"d-1-1","profile_id":"disconnect",'
        '"slot":"2026-01-02T18:00:00Z"},{"alternative":null,"bucket":"evening",'
        '"card_id":"card-002","label":"A","offered":"b-1-2","pick":"b-1-2","profile_id":"builder",'
        '"slot":"2026-01-02T18:00:00Z"},{"alternative":null,"bucket":"evening",'
        '"card_id":"card-002","label":"B","offered":"d-1-2","pick":"d-1-2","profile_id":"disconnect",'
        '"slot":"2026-01-02T18:00:00Z"},{"alternative":null,"bucket":"afternoon",'
        '"card_id":"card-003","label":"A","offered":"b-1-3","pick":"b-1-3","profile_id":"builder",'
        '"slot":"2026-01-03T14:00:00Z"},{"alternative":null,"bucket":"afternoon",'
        '"card_id":"card-003","label":"B","offered":"d-1-3","pick":"d-1-3","profile_id":"disconnect",'
        '"slot":"2026-01-03T14:00:00Z"},{"alternative":null,"bucket":"evening",'
        '"card_id":"card-004","label":"A","offered":"b-1-4","pick":"b-1-4","profile_id":"builder",'
        '"slot":"2026-01-02T18:00:00Z"},{"alternative":null,"bucket":"evening",'
        '"card_id":"card-004","label":"B","offered":"d-1-4","pick":"d-1-4","profile_id":"disconnect",'
        '"slot":"2026-01-02T18:00:00Z"}],'
        '"preference":"builder_over_disconnect","rulings_seen":4,'
        '"score_log":[{"always_half":{"brier":0.25,"log_loss":0.69314718056,'
        '"prediction":0.5},"bucket":"evening","card_id":"card-001","learner":'
        '{"brier":0.25,"log_loss":0.69314718056,"prediction":0.5},"majority":'
        '{"brier":0.25,"log_loss":0.69314718056,"prediction":0.5},"outcome":1,'
        '"pooled_rate":{"brier":0.25,"log_loss":0.69314718056,"prediction":0.5}},'
        '{"always_half":{"brier":0.25,"log_loss":0.69314718056,"prediction":0.5},'
        '"bucket":"evening","card_id":"card-002","learner":{"brier":0.111111111111,'
        '"log_loss":0.405465108108,"prediction":0.666666666667},"majority":'
        '{"brier":0.0,"log_loss":0.010050335854,"prediction":1.0},"outcome":1,'
        '"pooled_rate":{"brier":0.111111111111,"log_loss":0.405465108108,'
        '"prediction":0.666666666667}},{"always_half":{"brier":0.25,'
        '"log_loss":0.69314718056,"prediction":0.5},"bucket":"afternoon",'
        '"card_id":"card-003","learner":{"brier":0.25,"log_loss":0.69314718056,'
        '"prediction":0.5},"majority":{"brier":1.0,"log_loss":4.605170185988,'
        '"prediction":1.0},"outcome":0,"pooled_rate":{"brier":0.5625,'
        '"log_loss":1.38629436112,"prediction":0.75}},{"always_half":{"brier":0.25,'
        '"log_loss":0.69314718056,"prediction":0.5},"bucket":"evening",'
        '"card_id":"card-004","learner":{"brier":0.5625,"log_loss":1.38629436112,'
        '"prediction":0.75},"majority":{"brier":1.0,"log_loss":4.605170185988,'
        '"prediction":1.0},"outcome":0,"pooled_rate":{"brier":0.36,'
        '"log_loss":0.916290731874,"prediction":0.6}}]}'
    )


def test_replay_prefix_roundtrip() -> None:
    from framework.learner.schemas import PolicyState as _State

    rulings = _frozen_rulings()
    expected = state_json(replay(initial_state(), rulings))
    state = initial_state()
    for i, ruling in enumerate(rulings):
        state = observe(state, ruling)
        revived = _State.model_validate_json(state_json(state))
        rest = rulings[i + 1 :]
        assert state_json(replay(revived, rest)) == expected


def test_replay_hashseed_subprocess() -> None:
    code = (
        "from framework.learner.policy import initial_state, state_json;"
        "from framework.learner.scoring import replay;"
        "from tests.test_learner_scoring import _frozen_rulings;"
        "print(state_json(replay(initial_state(), _frozen_rulings())))"
    )
    outs: list[str] = []
    for seed in ("1", "2"):
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        outs.append(proc.stdout)
    assert outs[0] == outs[1]
    assert outs[0].strip() != ""


def test_replay_equals_observe_fold() -> None:
    rulings = _frozen_rulings()
    folded = initial_state()
    for ruling in rulings:
        folded = observe(folded, ruling)
    assert state_json(replay(initial_state(), rulings)) == state_json(folded)
