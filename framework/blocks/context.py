"""Display-ready render context: derived data only, never raw events (ticket 6)."""

from pydantic import AwareDatetime, Field, field_validator, model_validator

from framework.schemas.base import SchemaModel
from framework.schemas.events import NonEmptyStr


def check_http_url(url: str) -> str:
    """Shared URL rule: only http:// and https:// values are representable."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("url must start with http:// or https://")
    return url


class FreeSlot(SchemaModel):
    """One display-ready free slot; datetimes are already resolved upstream."""

    start: AwareDatetime
    end: AwareDatetime
    label: str = ""

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "FreeSlot":
        if self.end < self.start:
            raise ValueError("free slot end must not be before start")
        return self


class FactText(SchemaModel):
    """Short display text of one fact, already derived upstream."""

    id: NonEmptyStr
    text: NonEmptyStr


class ContextLink(SchemaModel):
    """Display-ready link; kept for future blocks, unconsumed in v0."""

    label: NonEmptyStr
    url: NonEmptyStr

    @field_validator("url")
    @classmethod
    def _url_scheme(cls, url: str) -> str:
        return check_http_url(url)


class RenderContext(SchemaModel):
    """Display-ready data only: no raw events, files, env vars, or network."""

    free_slots: list[FreeSlot] = Field(default_factory=list[FreeSlot])
    facts: list[FactText] = Field(default_factory=list[FactText])
    links: list[ContextLink] = Field(default_factory=list[ContextLink])
