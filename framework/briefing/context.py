"""Ticket 8: gate reference data (``GateContext``) and private-terms loading.

Building a context is the only place env/files are read;
``evaluate_briefing`` itself is pure.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, field_validator, model_validator

from framework.briefing.schemas import Briefing, Commitment
from framework.schemas.base import SchemaModel
from framework.schemas.core import Fact
from framework.schemas.events import NonEmptyStr


class TimeInterval(SchemaModel):
    """Half-open ``[start, end)`` interval."""

    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> TimeInterval:
        if self.end <= self.start:
            raise ValueError("interval end must be after start")
        return self


class MetricSnapshot(SchemaModel):
    """Point-in-time metric values; empty is valid (claims-free briefings)."""

    values: dict[NonEmptyStr, float] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _finite_values(cls, values: dict[str, float]) -> dict[str, float]:
        import math

        for metric_id, value in values.items():
            if not math.isfinite(value):
                raise ValueError(f"metric value must be finite: {metric_id}")
        return values


class ProfileLimits(SchemaModel):
    """Typed limits a caller encodes; the gate never parses markdown."""

    timezone: NonEmptyStr
    allowed_start: time
    allowed_end: time
    max_actions: int = Field(default=3, ge=1, le=3)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, timezone: str) -> str:
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {timezone}") from exc
        return timezone

    @model_validator(mode="after")
    def _same_day_window(self) -> ProfileLimits:
        if self.allowed_start >= self.allowed_end:
            raise ValueError("allowed_start must be before allowed_end")
        return self


class GateContext(SchemaModel):
    """Reference data the gate reconciles one briefing against."""

    facts: dict[NonEmptyStr, Fact] = Field(default_factory=dict)
    metrics: MetricSnapshot = Field(default_factory=MetricSnapshot)
    parent_briefing: Briefing | None = None
    parent_metrics: MetricSnapshot | None = None
    free_intervals: tuple[TimeInterval, ...] = ()
    busy_intervals: tuple[TimeInterval, ...] = ()
    limits: ProfileLimits
    check_slot: bool = True
    private_terms: tuple[str, ...] = ()
    private_terms_available: bool = False
    raw_metric_ids: frozenset[NonEmptyStr] = frozenset()
    forbidden_raw_literals: tuple[NonEmptyStr, ...] = ()
    commitments: tuple[Commitment, ...] = ()
    commitments_available: bool = False

    @field_validator("facts")
    @classmethod
    def _keys_match_ids(cls, facts: dict[str, Fact]) -> dict[str, Fact]:
        for key, fact in facts.items():
            if key != fact.id:
                raise ValueError("facts key must equal its Fact.id")
        return facts

    @model_validator(mode="after")
    def _parent_pair(self) -> GateContext:
        if (self.parent_briefing is None) != (self.parent_metrics is None):
            raise ValueError(
                "parent_briefing and parent_metrics must both be present or both absent"
            )
        return self

    @model_validator(mode="after")
    def _unique_commitment_ids(self) -> GateContext:
        seen: set[str] = set()
        for commitment in self.commitments:
            if commitment.id in seen:
                raise ValueError("commitment ids must be unique")
            seen.add(commitment.id)
        return self


@dataclass(frozen=True)
class PrivateTerms:
    """Loaded private terms plus their availability (fail closed)."""

    terms: tuple[str, ...]
    available: bool


def load_private_terms(
    environ: Mapping[str, str] | None = None,
    *,
    allow_missing_for_tests: bool = False,
) -> PrivateTerms:
    """Load private terms from ``deny-terms.txt`` in ``HIDDEN_CRITERIA_DIR``.

    The directory may hold other criteria files, so only ``deny-terms.txt``
    is read. The file holds one term per line; blank lines and lines
    starting with ``#`` are ignored. Matching is case-insensitive; terms of
    3 characters or fewer match whole words only, longer terms match as
    substrings (see the gate). Reads the variable at call time only.
    Unset/empty passes terms only when the caller passes
    ``allow_missing_for_tests=True``; every production caller uses the
    default. A missing file, a file with no terms, a non-UTF-8 file, or any
    line starting with ``- `` or ``* `` fails closed with no exception and
    no path in any message. Terms are never logged. The one-term-per-line
    ``deny-terms.txt`` layout is an assumption (see the session note).
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    raw_dir = env.get("HIDDEN_CRITERIA_DIR", "")
    if not raw_dir:
        return PrivateTerms((), available=allow_missing_for_tests)
    try:
        data = (Path(raw_dir) / "deny-terms.txt").read_bytes()
    except OSError:
        return PrivateTerms((), available=False)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return PrivateTerms((), available=False)
    terms: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ")):
            return PrivateTerms((), available=False)
        if stripped not in terms:
            terms.append(stripped)
    if not terms:
        return PrivateTerms((), available=False)
    return PrivateTerms(tuple(terms), available=True)
