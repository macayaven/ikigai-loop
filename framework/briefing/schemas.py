"""Ticket 8: briefing document schemas (the gated artifact).

A briefing is one typed document per objective profile. ``Claim.id`` is an
addition to the brief's field list: L0 requires unique IDs and violations
need stable locations, so every claim carries one.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from framework.schemas.base import Dimension, SchemaModel
from framework.schemas.events import NonEmptyStr

SectionType = Literal[
    "overall_state", "since_last", "working", "not_working", "actions"
]

ActionKind = Literal[
    "build",
    "write",
    "read",
    "apply",
    "outreach",
    "walk",
    "exercise",
    "rest",
    "music",
    "social",
    "plan",
    "checkin",
]


class MetricRef(SchemaModel):
    """A numeric value cited by a claim, reconciled against a snapshot."""

    metric_id: NonEmptyStr
    value: float

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("metric value must be finite")
        return value


class Claim(SchemaModel):
    """One prose statement plus its evidence (facts and/or metric refs)."""

    id: NonEmptyStr
    text: NonEmptyStr
    fact_ids: Annotated[list[NonEmptyStr], Field(default_factory=list)]
    metric_refs: Annotated[list[MetricRef], Field(default_factory=list)]


class Action(SchemaModel):
    """One proposed item in the ``actions`` section."""

    id: NonEmptyStr
    kind: ActionKind
    text: NonEmptyStr
    dimension: Dimension
    proposed_start: AwareDatetime
    proposed_end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Action:
        if self.proposed_end <= self.proposed_start:
            raise ValueError("proposed_end must be after proposed_start")
        return self


class Section(SchemaModel):
    """One typed section; its ``type`` is its identity (no ``id`` field)."""

    type: SectionType
    claims: Annotated[list[Claim], Field(default_factory=list)]
    actions: Annotated[list[Action], Field(default_factory=list)]


class Briefing(SchemaModel):
    """One gated briefing for one profile at one slot."""

    id: NonEmptyStr
    profile_id: NonEmptyStr
    subject_id: NonEmptyStr
    slot: AwareDatetime
    parent_briefing_id: NonEmptyStr | None = None
    sections: Annotated[list[Section], Field(default_factory=list)]
