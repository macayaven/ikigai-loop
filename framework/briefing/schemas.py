"""Ticket 8: briefing document schemas (the gated artifact).

A briefing is one typed document per objective profile. ``Claim.id`` is an
addition to the brief's field list: L0 requires unique IDs and violations
need stable locations, so every claim carries one.
"""

from __future__ import annotations

import math
import re
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
    "rest",
    "music",
    "social",
    "plan",
    "checkin",
]

EvidenceKind = Literal["tap", "calendar_tag", "github_push", "no_screen"]

COMMITMENT_TAG_PATTERN = r"iki-[a-z]+"
_COMMITMENT_TAG_RE = re.compile(COMMITMENT_TAG_PATTERN)


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


class Commitment(SchemaModel):
    """One user-written commitment an action may be scheduled from."""

    id: NonEmptyStr
    profile_id: NonEmptyStr
    title: NonEmptyStr
    kind: ActionKind
    dimension: Dimension
    evidence: EvidenceKind
    tag: NonEmptyStr | None = None

    @field_validator("title")
    @classmethod
    def _non_blank_title(cls, title: str) -> str:
        if not title.strip():
            raise ValueError("commitment title must not be blank")
        return title

    @model_validator(mode="after")
    def _tag_exactly_for_calendar_tag(self) -> Commitment:
        if self.evidence == "calendar_tag":
            if self.tag is None:
                raise ValueError("calendar_tag commitments require a tag")
            if _COMMITMENT_TAG_RE.fullmatch(self.tag) is None:
                raise ValueError("commitment tag must fullmatch iki-[a-z]+")
        elif self.tag is not None:
            raise ValueError("only calendar_tag commitments carry a tag")
        return self


class Action(SchemaModel):
    """One proposed item in the ``actions`` section."""

    id: NonEmptyStr
    commitment_id: NonEmptyStr
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
