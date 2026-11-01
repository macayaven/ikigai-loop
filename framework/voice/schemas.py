"""Ticket 14: the voice compile schema, its validation, and change lines.

The model proposes one typed operation; code disposes. Validation returns
closed codes in a fixed sorted order, and any code back means nothing changes.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from framework.briefing.gate import scan_outbound_text
from framework.schemas.base import SchemaModel

Operation = Literal["skip", "defer", "drop", "done", "keep", "fact_correction", "none"]
Until = Literal["slot", "today", "tomorrow", "this_week", "open"]

CORRECTION_UNKNOWN_COMMITMENT = "CORRECTION_UNKNOWN_COMMITMENT"
CORRECTION_COMMITMENT_REQUIRED = "CORRECTION_COMMITMENT_REQUIRED"
CORRECTION_PAIR_INVALID = "CORRECTION_PAIR_INVALID"
CORRECTION_QUESTION_INVALID = "CORRECTION_QUESTION_INVALID"

_OPERATIONS: tuple[str, ...] = (
    "skip",
    "defer",
    "drop",
    "done",
    "keep",
    "fact_correction",
    "none",
)

_UNTILS: tuple[str, ...] = ("slot", "today", "tomorrow", "this_week", "open")

_ALLOWED_UNTIL: dict[str, tuple[str | None, ...]] = {
    "skip": ("slot", "today", "tomorrow", "this_week", "open"),
    "defer": ("today", "tomorrow", "this_week"),
    "drop": ("open",),
    "done": ("today",),
    "keep": (None,),
    "fact_correction": (None,),
    "none": (None,),
}

_ID_REQUIRED: tuple[str, ...] = ("skip", "defer", "drop", "done", "keep")
_ID_FORBIDDEN: tuple[str, ...] = ("fact_correction", "none")

_UNTIL_WORDS: dict[str, str] = {
    "slot": "this slot",
    "today": "today",
    "tomorrow": "tomorrow",
    "this_week": "this week",
    "open": "no end date",
}

_QUESTION_MAX_CHARS = 200


class CompiledCorrection(SchemaModel):
    """One compiled voice correction: the operation plus its narrow args."""

    operation: Operation
    commitment_id: str | None
    until: Until | None
    question: str | None


@dataclass(frozen=True)
class UnparseableCorrection:
    """Sentinel for model output that is not a valid correction."""


def build_correction_schema(commitment_ids: Sequence[str]) -> dict[str, Any]:
    """Hand-built per-call schema: the id enum names exactly the known ids."""
    ids = list(commitment_ids)
    return {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": list(_OPERATIONS)},
            "commitment_id": {"type": ["string", "null"], "enum": [*ids, None]},
            "until": {"type": ["string", "null"], "enum": [*_UNTILS, None]},
            "question": {"type": ["string", "null"]},
        },
        "required": ["operation", "commitment_id", "until", "question"],
        "additionalProperties": False,
    }


def parse_compiled(text: str) -> CompiledCorrection | UnparseableCorrection:
    """Parse model output, normalising an empty or whitespace question to null."""
    try:
        loaded: Any = json.loads(text)
    except (ValueError, RecursionError):
        return UnparseableCorrection()
    if not isinstance(loaded, dict):
        return UnparseableCorrection()
    try:
        parsed = CompiledCorrection.model_validate(cast("dict[str, Any]", loaded))
    except Exception:  # noqa: BLE001 -- any validation failure is unparseable
        return UnparseableCorrection()
    if parsed.question is not None and not parsed.question.strip():
        parsed = parsed.model_copy(update={"question": None})
    return parsed


def validate_compiled(
    correction: CompiledCorrection,
    known_commitment_ids: Collection[str],
    *,
    private_terms: tuple[str, ...],
    private_terms_available: bool,
    forbidden_raw_literals: tuple[str, ...],
) -> tuple[str, ...]:
    """Deterministic checks on a parsed correction; sorted closed codes."""
    codes: list[str] = []
    if (
        correction.commitment_id is not None
        and correction.commitment_id not in known_commitment_ids
    ):
        codes.append(CORRECTION_UNKNOWN_COMMITMENT)
    if (correction.operation in _ID_REQUIRED and correction.commitment_id is None) or (
        correction.operation in _ID_FORBIDDEN and correction.commitment_id is not None
    ):
        codes.append(CORRECTION_COMMITMENT_REQUIRED)
    if correction.until not in _ALLOWED_UNTIL.get(correction.operation, ()):
        codes.append(CORRECTION_PAIR_INVALID)
    if correction.operation == "none":
        question = correction.question
        if (
            question is None
            or not question.strip()
            or len(question) > _QUESTION_MAX_CHARS
            or "\n" in question
            or "\r" in question
            or scan_outbound_text(
                question,
                private_terms=private_terms,
                private_terms_available=private_terms_available,
                forbidden_raw_literals=forbidden_raw_literals,
            )
        ):
            codes.append(CORRECTION_QUESTION_INVALID)
    elif correction.question is not None:
        codes.append(CORRECTION_QUESTION_INVALID)
    return tuple(sorted(codes))


def change_line(correction: CompiledCorrection, title: str | None) -> str:
    """The reply's change line: the transcript's effect, never the transcript.

    For ``fact_correction`` there is no commitment title, so ``title`` carries
    the pre-built claim-count phrase (``"1 claim"`` or ``"<n> claims"``)
    computed by the caller from the matched card. For ``none`` there is no
    change line, so the model's question is returned directly.
    """
    name = title if title is not None else ""
    if correction.operation == "skip":
        if correction.until is None:
            return f"Skipped: {name}."
        return f"Skipped: {name} ({_UNTIL_WORDS[correction.until]})."
    if correction.operation == "defer":
        if correction.until is None:
            return f"Put off: {name}."
        return f"Put off: {name} ({_UNTIL_WORDS[correction.until]})."
    if correction.operation == "drop":
        return f"Dropped: {name}."
    if correction.operation == "done":
        return f"Done: {name}."
    if correction.operation == "keep":
        return f"Kept: {name}."
    if correction.operation == "fact_correction":
        claims = title if title else "1 claim"
        return f"You disputed what this card cited ({claims})."
    return correction.question or ""
