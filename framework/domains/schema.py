"""Ticket 26: domain pack schema (typed manifests for one domain).

A domain pack is a thin config layer: one goal, the commitments allowed,
the signals read and the metrics checked, for one domain. This module
validates the pack file; it reads no data and touches no model.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from framework.verify.hardened import UnitName

_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFIX_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMIT_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_LABEL_RE = re.compile(r"^[a-z]+$")
_STARTS_ON = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class PackError(ValueError):
    """A pack file is missing, unreadable, or fails schema checks."""


def _safe_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors(include_input=False, include_url=False):
        loc = ".".join(str(bit) for bit in error.get("loc", ()))
        kind = str(error.get("type", "value_error"))
        parts.append(f"{loc}: {kind}" if loc else kind)
        if len(parts) >= 3:
            break
    detail = "; ".join(parts) if parts else "invalid pack"
    return f"pack is invalid: {detail}"


class SourceFile(BaseModel):
    """One CSV source named by the pack, with its pinned hash."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str
    date_column: str

    @field_validator("path")
    @classmethod
    def _path_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source path must not be blank")
        return value

    @field_validator("sha256")
    @classmethod
    def _sha_pins_bytes(cls, value: str) -> str:
        if _HEX_RE.fullmatch(value) is None:
            raise ValueError("source sha256 must be 64 lowercase hex chars")
        return value

    @field_validator("date_column")
    @classmethod
    def _date_column_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source date column must not be blank")
        return value


class WindowSpec(BaseModel):
    """The sliding window shape: length, weekday anchor, period words."""

    model_config = ConfigDict(extra="forbid")

    days: int
    starts_on: Literal[
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    ]
    period_phrase: str

    @field_validator("days")
    @classmethod
    def _days_in_range(cls, value: int) -> int:
        if not 1 <= value <= 31:
            raise ValueError("window days must be between 1 and 31")
        return value

    @field_validator("period_phrase")
    @classmethod
    def _phrase_names_start(cls, value: str) -> str:
        if "{start}" not in value:
            raise ValueError("window period phrase must hold {start}")
        return value


class DailyMetric(BaseModel):
    """One per-date metric read from a source column."""

    model_config = ConfigDict(extra="forbid")

    prefix: str
    source: str
    column: str
    op: Literal["sum", "count_above"]
    above: int | None = None
    labels: list[str]
    unit: UnitName

    @field_validator("prefix")
    @classmethod
    def _prefix_shaped(cls, value: str) -> str:
        if _PREFIX_RE.fullmatch(value) is None:
            raise ValueError("daily prefix must match ^[a-z][a-z0-9_]*$")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_single_words(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= 10:
            raise ValueError("metric labels must hold 1 to 10 entries")
        for entry in value:
            if _LABEL_RE.fullmatch(entry) is None:
                raise ValueError("metric label entries must be one lowercase word")
        return value

    @model_validator(mode="after")
    def _above_matches_op(self) -> Self:
        if self.op == "count_above" and self.above is None:
            raise ValueError("count_above needs an above value")
        if self.op != "count_above" and self.above is not None:
            raise ValueError("above is only allowed with count_above")
        return self


class WindowMetric(BaseModel):
    """One per-window metric folded from a daily series."""

    model_config = ConfigDict(extra="forbid")

    id: str
    op: Literal["sum", "count_above", "max"]
    of: str
    above: int | None = None
    labels: list[str]
    unit: UnitName

    @field_validator("id")
    @classmethod
    def _id_shaped(cls, value: str) -> str:
        if _PREFIX_RE.fullmatch(value) is None:
            raise ValueError("window metric id must match ^[a-z][a-z0-9_]*$")
        return value

    @field_validator("labels")
    @classmethod
    def _labels_single_words(cls, value: list[str]) -> list[str]:
        if not 1 <= len(value) <= 10:
            raise ValueError("metric labels must hold 1 to 10 entries")
        for entry in value:
            if _LABEL_RE.fullmatch(entry) is None:
                raise ValueError("metric label entries must be one lowercase word")
        return value

    @model_validator(mode="after")
    def _above_matches_op(self) -> Self:
        if self.op == "count_above" and self.above is None:
            raise ValueError("count_above needs an above value")
        if self.op != "count_above" and self.above is not None:
            raise ValueError("above is only allowed with count_above")
        return self


class Identity(BaseModel):
    """One cross-check between sources, run on every build."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["columns_sum", "daily_matches", "rows_per_date"]
    source: str
    parts: list[str] | None = None
    total: str | None = None
    metric: str | None = None
    column: str | None = None
    count: int | None = None

    @model_validator(mode="after")
    def _fields_match_kind(self) -> Self:
        if self.kind == "columns_sum" and (
            not self.source or not self.parts or not self.total
        ):
            raise ValueError("columns_sum needs source, parts and total")
        if self.kind == "daily_matches" and (
            not self.metric or not self.source or not self.column
        ):
            raise ValueError("daily_matches needs metric, source and column")
        if self.kind == "rows_per_date" and (not self.source or self.count is None):
            raise ValueError("rows_per_date needs source and count")
        return self


class Rule(BaseModel):
    """When one commitment applies, as a comparison on a window metric."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    op: Literal[">=", ">", "==", "<=", "<"]
    value: int


class CommitmentRule(BaseModel):
    """One allowed commitment with the rule that selects it."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    when: Rule

    @field_validator("id")
    @classmethod
    def _id_shaped(cls, value: str) -> str:
        if _COMMIT_RE.fullmatch(value) is None:
            raise ValueError("commitment id must match ^[a-z][a-z0-9-]*$")
        return value

    @field_validator("text")
    @classmethod
    def _text_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("commitment text must not be blank")
        return value


class Goal(BaseModel):
    """The one goal this pack serves."""

    model_config = ConfigDict(extra="forbid")

    id: str
    text: str


class DomainPack(BaseModel):
    """The validated domain pack manifest."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str
    title: str
    note: str
    goal: Goal
    sources: dict[str, SourceFile]
    window: WindowSpec
    daily_metrics: list[DailyMetric]
    window_metrics: list[WindowMetric]
    identities: list[Identity]
    commitments: list[CommitmentRule]
    facts: dict[str, str]

    @field_validator("daily_metrics")
    @classmethod
    def _daily_non_empty(cls, value: list[DailyMetric]) -> list[DailyMetric]:
        if not value:
            raise ValueError("daily metrics must hold at least 1 entry")
        return value

    @field_validator("commitments")
    @classmethod
    def _commitments_at_least_two(
        cls, value: list[CommitmentRule]
    ) -> list[CommitmentRule]:
        if len(value) < 2:
            raise ValueError("commitments must hold at least 2 entries")
        return value

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        prefixes = [metric.prefix for metric in self.daily_metrics]
        if len(set(prefixes)) != len(prefixes):
            raise ValueError("daily metric prefixes must be unique")
        window_ids = [metric.id for metric in self.window_metrics]
        if len(set(window_ids)) != len(window_ids):
            raise ValueError("window metric ids must be unique")
        if set(prefixes) & set(window_ids):
            raise ValueError("metric ids and prefixes must be unique")
        for metric in self.daily_metrics:
            if metric.source not in self.sources:
                raise ValueError("daily metric source is not declared")
        for metric in self.window_metrics:
            if metric.of not in prefixes:
                raise ValueError("window metric of must name a declared prefix")
        for identity in self.identities:
            if identity.source not in self.sources:
                raise ValueError("identity source is not declared")
            if identity.kind == "daily_matches" and identity.metric not in prefixes:
                raise ValueError("daily_matches metric must name a declared prefix")
        commitment_ids = [commitment.id for commitment in self.commitments]
        if len(set(commitment_ids)) != len(commitment_ids):
            raise ValueError("commitment ids must be unique")
        for commitment in self.commitments:
            if commitment.when.metric not in window_ids:
                raise ValueError("commitment rule must name a declared window metric")
        return self


def load_pack(path: str | Path) -> DomainPack:
    """Read and validate a pack file; every failure raises PackError."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise PackError("pack file cannot be read") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise PackError("pack file is not valid JSON") from None
    try:
        return DomainPack.model_validate(data)
    except ValidationError as exc:
        raise PackError(_safe_error(exc)) from None
