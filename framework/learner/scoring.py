"""Predictions, pre-ruling scoring, replay and reports."""

import math
from collections.abc import Iterable
from fractions import Fraction
from typing import Literal

from framework.learner.policy import update
from framework.learner.schemas import (
    Bucket,
    PolicyState,
    Prediction,
    PredictorReport,
    PredictorScore,
    Ruling,
    ScoreEntry,
    ScoreReport,
)

_CLIP_LOW = Fraction(1, 100)
_CLIP_HIGH = Fraction(99, 100)


def _choice_counts(state: PolicyState) -> tuple[int, int]:
    taken_b = sum(bucket.alpha - 1 for bucket in state.buckets.values())
    taken_d = sum(bucket.beta - 1 for bucket in state.buckets.values())
    return taken_b, taken_d


def _probabilities(
    state: PolicyState, bucket: Bucket
) -> tuple[Fraction, Fraction, Fraction]:
    """Exact learner, majority and pooled-rate values, from state only."""
    bucket_state = state.buckets[bucket]
    learner = Fraction(bucket_state.alpha, bucket_state.alpha + bucket_state.beta)
    taken_b, taken_d = _choice_counts(state)
    if taken_b > taken_d:
        majority = Fraction(1)
    elif taken_b < taken_d:
        majority = Fraction(0)
    else:
        majority = Fraction(1, 2)
    pooled = Fraction(taken_b + 1, taken_b + taken_d + 2)
    return learner, majority, pooled


def predict(state: PolicyState, bucket: Bucket) -> Prediction:
    """Four probabilities that Builder is taken, from state only."""
    learner, majority, pooled = _probabilities(state, bucket)
    return Prediction(
        learner=float(learner),
        always_half=0.5,
        majority=float(majority),
        pooled_rate=float(pooled),
    )


def _round12(value: float) -> float:
    return round(value, 12)


def _score_one(probability: Fraction, outcome: int, clip: bool) -> PredictorScore:
    forecast = min(_CLIP_HIGH, max(_CLIP_LOW, probability)) if clip else probability
    chance = forecast if outcome == 1 else 1 - forecast
    distance = probability - outcome
    return PredictorScore(
        prediction=_round12(float(probability)),
        brier=_round12(float(distance * distance)),
        log_loss=_round12(-math.log(float(chance))),
    )


def _would_move_posterior(state: PolicyState, ruling: Ruling) -> bool:
    if ruling.target not in ("A", "B"):
        return False
    if len(ruling.proposals) != 2:
        return False
    return state.cards.get(ruling.card_id) is None


def score_before_update(state: PolicyState, ruling: Ruling) -> PolicyState:
    """Log one score entry when the ruling would move the posterior."""
    if not _would_move_posterior(state, ruling):
        return state
    chosen = next(p for p in ruling.proposals if p.label == ruling.target)
    outcome: Literal[0, 1] = 1 if chosen.profile_id == "builder" else 0
    learner_p, majority_p, pooled_p = _probabilities(state, ruling.bucket)
    entry = ScoreEntry(
        card_id=ruling.card_id,
        bucket=ruling.bucket,
        outcome=outcome,
        learner=_score_one(learner_p, outcome, False),
        always_half=_score_one(Fraction(1, 2), outcome, False),
        majority=_score_one(majority_p, outcome, True),
        pooled_rate=_score_one(pooled_p, outcome, False),
    )
    return state.model_copy(update={"score_log": state.score_log + (entry,)})


def observe(state: PolicyState, ruling: Ruling) -> PolicyState:
    """Score before the ruling, then fold it in; the live loop calls this."""
    return update(score_before_update(state, ruling), ruling)


def replay(initial: PolicyState, rulings: Iterable[Ruling]) -> PolicyState:
    """Fold observe in order; identical inputs give identical bytes."""
    state = initial
    for ruling in rulings:
        state = observe(state, ruling)
    return state


def _report_one(calls: list[tuple[PredictorScore, int]]) -> PredictorReport:
    if not calls:
        return PredictorReport(
            mean_brier=None, mean_log_loss=None, correct=0, wrong=0, no_call=0
        )
    correct = sum(
        1
        for score, outcome in calls
        if (score.prediction > 0.5) == (outcome == 1) and score.prediction != 0.5
    )
    wrong = sum(
        1
        for score, outcome in calls
        if (score.prediction > 0.5) != (outcome == 1) and score.prediction != 0.5
    )
    no_call = sum(1 for score, _ in calls if score.prediction == 0.5)
    return PredictorReport(
        mean_brier=math.fsum(score.brier for score, _ in calls) / len(calls),
        mean_log_loss=math.fsum(score.log_loss for score, _ in calls) / len(calls),
        correct=correct,
        wrong=wrong,
        no_call=no_call,
    )


def score_report(state: PolicyState) -> ScoreReport:
    """Per-predictor means and call counts over the score log."""
    entries = list(state.score_log)
    return ScoreReport(
        n=len(entries),
        learner=_report_one([(e.learner, e.outcome) for e in entries]),
        always_half=_report_one([(e.always_half, e.outcome) for e in entries]),
        majority=_report_one([(e.majority, e.outcome) for e in entries]),
        pooled_rate=_report_one([(e.pooled_rate, e.outcome) for e in entries]),
    )
