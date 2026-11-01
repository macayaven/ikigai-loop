"""Model-facing draft schemas for Glimmer (Ticket 9)."""

from typing import Annotated

from pydantic import Field, StringConstraints

from framework.schemas.base import SchemaModel
from framework.schemas.events import NonEmptyStr

StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class FactDraft(SchemaModel):
    statement: StrippedStr
    evidence: Annotated[list[NonEmptyStr], Field(min_length=1)]


class FactDraftBatch(SchemaModel):
    facts: list[FactDraft]


class FeedTopicDraft(SchemaModel):
    evidence: Annotated[list[NonEmptyStr], Field(min_length=1)]
    topic: StrippedStr


class FeedTopicBatch(SchemaModel):
    topics: list[FeedTopicDraft]
