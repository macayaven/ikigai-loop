"""Ticket 11: the narrow draft, the fallback, and the per-call schema.

The model returns ids only; code fills every value. The response schema is
hand-built inline so an empty id list leaves its property out instead of
sending an empty enum.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import AwareDatetime, field_validator

from framework.briefing.schemas import Commitment
from framework.schemas.base import SchemaModel
from framework.schemas.events import NonEmptyStr

# No valid draft comes near this size; it bounds the time the gate's text scan can take on a runaway reply.
MAX_DRAFT_CHARS = 64_000


class ClaimDraft(SchemaModel):
    """One drafted claim: prose plus id-only evidence."""

    text: NonEmptyStr
    fact_ids: list[NonEmptyStr]
    metric_refs: list[NonEmptyStr]

    @field_validator("text")
    @classmethod
    def _text_holds_a_letter(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value):
            raise ValueError("claim text must hold a letter")
        return value


class ProposalDraft(SchemaModel):
    """The narrow draft: one commitment plus claim lists."""

    commitment_id: NonEmptyStr
    overall_state: list[ClaimDraft]
    working: list[ClaimDraft]
    not_working: list[ClaimDraft]
    since_last: list[ClaimDraft]


class FallbackProposal(SchemaModel):
    """A labelled fallback: a commitment and a window, no prose."""

    kind: Literal["fallback"]
    profile_id: NonEmptyStr
    subject_id: NonEmptyStr
    slot: AwareDatetime
    commitment: Commitment
    proposed_start: AwareDatetime
    proposed_end: AwareDatetime
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class UnparseableDraft:
    """Sentinel for model output that is not a valid draft."""


def _id_array(ids: Sequence[str]) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string", "enum": list(ids)}}


def _claim_schema(
    fact_ids: Sequence[str] | None, metric_ids: Sequence[str] | None
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "text": {"type": "string", "minLength": 1},
    }
    required = ["text"]
    if fact_ids:
        properties["fact_ids"] = _id_array(fact_ids)
        required.append("fact_ids")
    if metric_ids:
        properties["metric_refs"] = _id_array(metric_ids)
        required.append("metric_refs")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _section_schema(claim: dict[str, Any], *, min_items: int = 0) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": claim,
        "maxItems": 3,
    }
    if min_items:
        schema["minItems"] = min_items
    return schema


def build_response_schema(
    *,
    commitment_ids: Sequence[str],
    fact_ids: Sequence[str],
    snapshot_metric_ids: Sequence[str],
    delta_metric_ids: Sequence[str],
    has_facts: bool,
    has_metrics: bool,
    has_parent: bool,
) -> dict[str, Any]:
    """Hand-built per-call schema: no defs, no titles, no empty enums."""
    facts = list(fact_ids) if has_facts else []
    metrics = list(snapshot_metric_ids) if has_metrics else []
    deltas = list(delta_metric_ids) if has_parent else []
    claim = _claim_schema(facts or None, metrics or None)
    properties: dict[str, Any] = {
        "commitment_id": {"type": "string", "enum": list(commitment_ids)},
        "overall_state": _section_schema(claim, min_items=1),
        "working": _section_schema(claim),
        "not_working": _section_schema(claim),
    }
    required = ["commitment_id", "overall_state", "working", "not_working"]
    if has_parent:
        since_claim = _claim_schema(facts or None, deltas or None)
        if deltas:
            since_claim["properties"]["metric_refs"]["minItems"] = 1
        properties["since_last"] = _section_schema(since_claim, min_items=1)
        required.append("since_last")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def parse_draft(
    text: str, *, has_facts: bool, has_metrics: bool, has_parent: bool
) -> ProposalDraft | UnparseableDraft:
    """Parse model output, inserting [] for properties the schema left out."""
    if len(text) > MAX_DRAFT_CHARS:
        return UnparseableDraft()
    try:
        loaded: Any = json.loads(text)
    except (ValueError, RecursionError):
        return UnparseableDraft()
    if not isinstance(loaded, dict):
        return UnparseableDraft()
    raw = cast("dict[str, Any]", loaded)
    if not has_parent:
        raw["since_last"] = []
    for section in ("overall_state", "working", "not_working", "since_last"):
        section_claims: Any = raw.get(section)
        if not isinstance(section_claims, list):
            continue
        for item in cast("list[Any]", section_claims):
            if not isinstance(item, dict):
                continue
            claim = cast("dict[str, Any]", item)
            if not has_facts:
                claim.setdefault("fact_ids", [])
            if not has_metrics and section != "since_last":
                claim.setdefault("metric_refs", [])
    try:
        return ProposalDraft.model_validate(raw)
    except Exception:  # noqa: BLE001 -- any validation failure is unparseable
        return UnparseableDraft()
