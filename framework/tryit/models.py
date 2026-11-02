"""Ticket 21: typed manifest for the packaged synthetic recording."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from framework.briefing.schemas import Commitment
from framework.schemas.base import SchemaModel
from framework.schemas.events import Event, NonEmptyStr


class ClaimTemplate(SchemaModel):
    """One drafted claim: prose plus a coverage marker, never a fact id."""

    text: str
    fact_family: NonEmptyStr
    fact_member: str
    metric_refs: list[NonEmptyStr]


class DraftTemplate(SchemaModel):
    """One canned reply in the shape the model returns."""

    commitment_id: NonEmptyStr
    overall_state: list[ClaimTemplate] = Field(min_length=1, max_length=3)
    working: list[ClaimTemplate] = Field(
        default_factory=list[ClaimTemplate], max_length=3
    )
    not_working: list[ClaimTemplate] = Field(
        default_factory=list[ClaimTemplate], max_length=3
    )


class Recording(SchemaModel):
    """The whole made-up world: instants, rows, taps, commitments, replies."""

    note: NonEmptyStr
    subject_id: NonEmptyStr
    as_of: AwareDatetime
    slot: AwareDatetime
    prev_card: AwareDatetime
    cycle_id: NonEmptyStr
    events: list[Event] = Field(min_length=1)
    earlier_taps: list[Event] = Field(min_length=1)
    commitments: list[Commitment] = Field(min_length=2, max_length=2)
    builder_planted: DraftTemplate
    builder_fixed: DraftTemplate
    disconnect: DraftTemplate
