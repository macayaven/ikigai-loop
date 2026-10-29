"""Fact, Profile and Criterion schemas."""

import math
from typing import Annotated

from pydantic import AwareDatetime, Field, model_validator

from framework.schemas.base import Dimension, SchemaModel, Tier
from framework.schemas.events import NonEmptyStr


class FactWindow(SchemaModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "FactWindow":
        if self.end < self.start:
            raise ValueError("fact window end must not be before start")
        return self


class Fact(SchemaModel):
    id: NonEmptyStr
    subject_id: NonEmptyStr
    window: FactWindow
    statement: NonEmptyStr
    evidence: Annotated[list[NonEmptyStr], Field(min_length=1)]
    tier: Tier


class IkigaiWeights(SchemaModel):
    love: Annotated[float, Field(ge=0, le=1)]
    good_at: Annotated[float, Field(ge=0, le=1)]
    world_needs: Annotated[float, Field(ge=0, le=1)]
    paid_for: Annotated[float, Field(ge=0, le=1)]

    @model_validator(mode="after")
    def _sums_to_one(self) -> "IkigaiWeights":
        total = self.love + self.good_at + self.world_needs + self.paid_for
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError("ikigai weights must sum to 1.0")
        return self


class Profile(SchemaModel):
    subject_id: NonEmptyStr
    profile_id: NonEmptyStr
    label: str
    version: Annotated[int, Field(ge=1)]
    weights: IkigaiWeights


class Criterion(SchemaModel):
    id: NonEmptyStr
    profile_id: NonEmptyStr
    dimension: Dimension
    text: NonEmptyStr
    hidden: bool
    version: Annotated[int, Field(ge=1)]
