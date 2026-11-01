"""Learner data types: every model sits on SchemaModel."""

import math
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from framework.schemas.base import SchemaModel
from framework.schemas.events import NonEmptyStr

Bucket = Literal["afternoon", "evening", "night"]
BUCKETS: tuple[Bucket, ...] = ("afternoon", "evening", "night")
ProfileId = Literal["builder", "disconnect"]
Target = Literal["A", "B", "neither", "wrong", "why"]


def _finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class Proposal(SchemaModel):
    """One labelled offer as shown on a card."""

    label: Literal["A", "B"]
    profile_id: ProfileId
    commitment_id: NonEmptyStr
    policy_pick: NonEmptyStr
    policy_alternative: NonEmptyStr | None = None


class Ruling(SchemaModel):
    """One tap on one card, with the card's slot and bucket attached."""

    card_id: NonEmptyStr
    slot: AwareDatetime
    bucket: Bucket
    proposals: tuple[Proposal, ...]
    target: Target

    @model_validator(mode="after")
    def _card_shape(self) -> "Ruling":
        count = len(self.proposals)
        if count == 1:
            if self.proposals[0].label != "A":
                raise ValueError("a one-proposal card must carry label A")
        elif count == 2:
            first, second = self.proposals
            if {first.label, second.label} != {"A", "B"}:
                raise ValueError("a two-proposal card must carry labels A and B")
            if first.profile_id == second.profile_id:
                raise ValueError("two proposals must show different profiles")
            if first.commitment_id == second.commitment_id:
                raise ValueError("two proposals must show different commitments")
        else:
            raise ValueError("a card holds 1 or 2 proposals")
        if self.target == "B" and count == 1:
            raise ValueError("target B needs a proposal labelled B")
        return self


class BucketState(SchemaModel):
    """Counts for one time bucket; alpha and beta start at the prior."""

    alpha: Annotated[int, Field(ge=1)] = 1
    beta: Annotated[int, Field(ge=1)] = 1
    neither: Annotated[int, Field(ge=0)] = 0
    wrong: Annotated[int, Field(ge=0)] = 0
    why: Annotated[int, Field(ge=0)] = 0
    single_taken: Annotated[int, Field(ge=0)] = 0


class CommitmentState(SchemaModel):
    """Offer counts for one commitment; taken plus declined never pass offered."""

    profile_id: ProfileId
    offered: Annotated[int, Field(ge=0)]
    taken: Annotated[int, Field(ge=0)]
    declined: Annotated[int, Field(ge=0)]
    last_offered_slot: AwareDatetime

    @model_validator(mode="after")
    def _counts_fit(self) -> "CommitmentState":
        if self.taken + self.declined > self.offered:
            raise ValueError("taken + declined must not pass offered")
        return self


class PredictorScore(SchemaModel):
    """One scored probability: the call plus its two losses."""

    prediction: float
    brier: float
    log_loss: float

    @field_validator("prediction", "brier", "log_loss")
    @classmethod
    def _finite_float(cls, value: float) -> float:
        return _finite(value, "score")

    @field_validator("prediction")
    @classmethod
    def _in_unit_interval(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("prediction must lie in [0, 1]")
        return value


class ScoreEntry(SchemaModel):
    """The four predictions made before one posterior-moving ruling."""

    card_id: NonEmptyStr
    bucket: Bucket
    outcome: Literal[0, 1]
    learner: PredictorScore
    always_half: PredictorScore
    majority: PredictorScore
    pooled_rate: PredictorScore


class PickLogEntry(SchemaModel):
    """What one proposal on one card showed, kept for card checks."""

    card_id: NonEmptyStr
    slot: AwareDatetime
    bucket: Bucket
    profile_id: ProfileId
    label: Literal["A", "B"]
    offered: NonEmptyStr
    pick: NonEmptyStr
    alternative: NonEmptyStr | None = None


class PolicyState(SchemaModel):
    """The whole learner: counts, card ledger, and both logs."""

    preference: Literal["builder_over_disconnect"] = "builder_over_disconnect"
    rulings_seen: Annotated[int, Field(ge=0)] = 0
    duplicates: Annotated[int, Field(ge=0)] = 0
    buckets: dict[Bucket, BucketState]
    commitments: dict[NonEmptyStr, CommitmentState] = Field(default_factory=dict)
    cards: dict[NonEmptyStr, Literal["A", "B", "neither"] | None] = Field(
        default_factory=dict
    )
    score_log: tuple[ScoreEntry, ...] = ()
    pick_log: tuple[PickLogEntry, ...] = ()

    @model_validator(mode="after")
    def _three_buckets(self) -> "PolicyState":
        if set(self.buckets) != set(BUCKETS):
            raise ValueError("buckets must hold exactly the three BUCKETS keys")
        return self


class Prediction(SchemaModel):
    """Four probabilities that Builder is taken, from state only."""

    learner: float
    always_half: float
    majority: float
    pooled_rate: float

    @field_validator("learner", "always_half", "majority", "pooled_rate")
    @classmethod
    def _bounded(cls, value: float) -> float:
        _finite(value, "prediction")
        if not 0.0 <= value <= 1.0:
            raise ValueError("prediction must lie in [0, 1]")
        return value


class RankedCommitment(SchemaModel):
    """One candidate in rank order, with the reason for its place."""

    commitment_id: NonEmptyStr
    position: Annotated[int, Field(ge=1)]
    role: Literal["pick", "alternative", "other"]
    profile_id: ProfileId
    bucket: Bucket
    offered: Annotated[int, Field(ge=0)]
    taken: Annotated[int, Field(ge=0)]
    declined: Annotated[int, Field(ge=0)]
    smoothed_rate: float
    reason: str

    @field_validator("smoothed_rate")
    @classmethod
    def _finite_rate(cls, value: float) -> float:
        return _finite(value, "smoothed_rate")


class PolicyChange(SchemaModel):
    """One leaf difference between two states."""

    path: str
    kind: Literal["added", "removed", "changed"]
    before: object = None
    after: object = None


class PredictorReport(SchemaModel):
    """Mean losses and call counts for one predictor."""

    mean_brier: float | None
    mean_log_loss: float | None
    correct: Annotated[int, Field(ge=0)]
    wrong: Annotated[int, Field(ge=0)]
    no_call: Annotated[int, Field(ge=0)]

    @field_validator("mean_brier", "mean_log_loss")
    @classmethod
    def _finite_or_none(cls, value: float | None) -> float | None:
        if value is not None:
            _finite(value, "mean")
        return value


class ScoreReport(SchemaModel):
    """Per-predictor reports over the score log."""

    n: Annotated[int, Field(ge=0)]
    learner: PredictorReport
    always_half: PredictorReport
    majority: PredictorReport
    pooled_rate: PredictorReport


class RecoverCell(SchemaModel):
    """One known-preference cell: four numbers at one grid point."""

    true_p: float
    n_cards: Annotated[int, Field(ge=1)]
    n_sims: Annotated[int, Field(ge=1)]
    seed: int
    correct_side: float | None
    mean_absolute_error: float
    coverage: float
    mean_interval_width: float

    @field_validator("true_p", "mean_absolute_error", "coverage", "mean_interval_width")
    @classmethod
    def _finite_stat(cls, value: float) -> float:
        return _finite(value, "stat")

    @field_validator("correct_side")
    @classmethod
    def _finite_side(cls, value: float | None) -> float | None:
        if value is not None:
            _finite(value, "correct_side")
        return value


class RecoverTable(SchemaModel):
    """The full simulated grid, labelled so nobody reads it as real."""

    label: Literal["simulated"] = "simulated"
    seed: int
    n_sims: int
    note: str
    cells: tuple[RecoverCell, ...]
