"""Ticket 8: deterministic briefing gate (L0 structure, L1 rules, L1b).

No network, no model call, no env read, no clock read: all times come from
the briefing/context. Messages never interpolate a matched secret, email,
private term, or raw value. Identical ``(code, location)`` pairs are
de-duplicated once at the end; the result is sorted by
``(layer, code, location)`` so section input order cannot change it.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from framework.briefing.context import GateContext, TimeInterval
from framework.briefing.numbers import extract_number_tokens
from framework.briefing.schemas import Action, Briefing, Claim

Layer = Literal["L0", "L1", "L1b"]

REQUIRED_SECTIONS = ("overall_state", "working", "not_working", "actions")
KNOWN_SECTION_TYPES = frozenset(
    ["overall_state", "since_last", "working", "not_working", "actions"]
)

_SECRET_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bghp_[A-Za-z0-9_-]{16,}",
        r"\bgho_[A-Za-z0-9_-]{16,}",
        r"\bgithub_pat_[A-Za-z0-9_-]{16,}",
        r"\bglpat-[A-Za-z0-9_-]{16,}",
        r"\bsk-[A-Za-z0-9_-]{16,}",
        r"\bAKIA[A-Za-z0-9_-]{16,}",
        r"\bxox[baprs]-[A-Za-z0-9_-]{16,}",
        r"\bBearer\s+\S{16,}",
        r"-----BEGIN [A-Za-z0-9 ]*PRIVATE KEY-----",
        r"(?:api[_-]?key|secret|token|password)\s*[:=]\s*\S+",
        r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.ts\.net\b",
    )
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+\d[\d ()-]{7,}\d")
_REPO_TERMS = ("ikigai-loop", "ikigai_loop", "ikigai loop")


@dataclass(frozen=True)
class Violation:
    """One stable gate finding; ``message`` never echoes matched content."""

    code: str
    layer: Layer
    location: str
    message: str


@dataclass(frozen=True)
class GateResult:
    """Sorted, de-duplicated violations for one briefing."""

    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        """A briefing passes iff it has no violations."""
        return self.violations == ()


def _section_location(section_type: str) -> str:
    return f"sections[{section_type}]"


def _claim_location(section_type: str, claim_id: str) -> str:
    return f"sections[{section_type}].claims[{claim_id}]"


def _action_location(action_id: str) -> str:
    return f"sections[actions].actions[{action_id}]"


def _iter_texts(
    briefing: Briefing,
) -> tuple[tuple[str, str, str, str], ...]:
    """(kind, owner_id, text, location) for every scanned claim/action text."""
    rows: list[tuple[str, str, str, str]] = []
    for section in briefing.sections:
        for claim in section.claims:
            rows.append(
                (
                    "claim",
                    claim.id,
                    claim.text,
                    _claim_location(section.type, claim.id),
                )
            )
        for action in section.actions:
            rows.append(("action", action.id, action.text, _action_location(action.id)))
    return tuple(rows)


def _iter_claims(
    briefing: Briefing,
) -> tuple[tuple[str, Claim], ...]:
    return tuple(
        (section.type, claim)
        for section in briefing.sections
        for claim in section.claims
    )


def _iter_actions(briefing: Briefing) -> tuple[Action, ...]:
    return tuple(action for section in briefing.sections for action in section.actions)


def _collapse(text: str) -> str:
    return " ".join(text.split()).casefold()


def _contains_token(text: str, literal: str) -> bool:
    start = 0
    while True:
        index = text.find(literal, start)
        if index < 0:
            return False
        before = text[index - 1] if index > 0 else ""
        end = index + len(literal)
        after = text[end] if end < len(text) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            return True
        start = index + 1


def _merge_intervals(
    intervals: tuple[TimeInterval, ...],
) -> tuple[tuple[datetime, datetime], ...]:
    spans = sorted(
        ((item.start, item.end) for item in intervals), key=lambda span: span[0]
    )
    merged: list[list[datetime]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return tuple((start, end) for start, end in merged)


def _l0_counts(briefing: Briefing, context: GateContext) -> list[Violation]:
    violations: list[Violation] = []
    types = [section.type for section in briefing.sections]
    for section_type, count in Counter(types).items():
        if count > 1:
            violations.append(
                Violation(
                    "L0_DUPLICATE_SECTION",
                    "L0",
                    _section_location(section_type),
                    "section type appears more than once",
                )
            )
    for section_type in REQUIRED_SECTIONS:
        if section_type not in types:
            violations.append(
                Violation(
                    "L0_MISSING_SECTION",
                    "L0",
                    _section_location(section_type),
                    "required section is missing",
                )
            )
    if len(types) > 5:
        violations.append(
            Violation("L0_SECTION_COUNT", "L0", "sections", "too many sections")
        )
    for section in briefing.sections:
        if section.type == "overall_state" and not section.claims:
            violations.append(
                Violation(
                    "L0_EMPTY_SECTION",
                    "L0",
                    _section_location(section.type),
                    "section must carry at least one claim",
                )
            )
        if section.type == "since_last" and not section.claims:
            violations.append(
                Violation(
                    "L0_EMPTY_SECTION",
                    "L0",
                    _section_location(section.type),
                    "section must carry at least one claim",
                )
            )
    limit = min(3, context.limits.max_actions)
    for section in briefing.sections:
        if section.type == "actions":
            if len(section.actions) < 1 or len(section.actions) > limit:
                violations.append(
                    Violation(
                        "L0_ACTION_COUNT",
                        "L0",
                        _section_location(section.type),
                        "action count outside 1..limit",
                    )
                )
        elif section.actions:
            violations.append(
                Violation(
                    "L0_ACTION_COUNT",
                    "L0",
                    _section_location(section.type),
                    "action count outside 1..limit",
                )
            )
    seen: dict[str, str] = {}
    for section in briefing.sections:
        for claim in section.claims:
            location = _claim_location(section.type, claim.id)
            if claim.id in seen:
                violations.append(
                    Violation(
                        "L0_DUPLICATE_ID",
                        "L0",
                        location,
                        "id is used more than once",
                    )
                )
            else:
                seen[claim.id] = location
        for action in section.actions:
            location = _action_location(action.id)
            if action.id in seen:
                violations.append(
                    Violation(
                        "L0_DUPLICATE_ID",
                        "L0",
                        location,
                        "id is used more than once",
                    )
                )
            else:
                seen[action.id] = location
    return violations


def _l1_text_checks(briefing: Briefing, context: GateContext) -> list[Violation]:
    violations: list[Violation] = []
    if not context.private_terms_available:
        violations.append(
            Violation(
                "L1_PRIVATE_TERMS_UNAVAILABLE",
                "L1",
                "briefing",
                "private terms unavailable",
            )
        )
        check_terms = False
    else:
        check_terms = True
    collapsed_terms = [_collapse(term) for term in context.private_terms]
    for _kind, _owner, text, location in _iter_texts(briefing):
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            violations.append(
                Violation("L1_SECRET", "L1", location, "secret-like token")
            )
        if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
            violations.append(Violation("L1_PII", "L1", location, "contact detail"))
        if check_terms:
            collapsed = _collapse(text)
            for term in collapsed_terms:
                if not term:
                    continue
                if len(term) <= 3:
                    hit = _contains_token(collapsed, term)
                else:
                    hit = term in collapsed
                if hit:
                    violations.append(
                        Violation("L1_PRIVATE_TERM", "L1", location, "private term")
                    )
                    break
        if any(
            _contains_token(_collapse(text), _collapse(literal))
            for literal in context.forbidden_raw_literals
            if _collapse(literal)
        ):
            violations.append(
                Violation("L1_RAW_VALUE", "L1", location, "raw source value")
            )
    return violations


def _l1_metric_ref_raw_check(
    briefing: Briefing, context: GateContext
) -> list[Violation]:
    violations: list[Violation] = []
    for section_type, claim in _iter_claims(briefing):
        location = _claim_location(section_type, claim.id)
        if any(
            ref.metric_id in context.raw_metric_ids or ref.metric_id.startswith("raw.")
            for ref in claim.metric_refs
        ):
            violations.append(
                Violation("L1_RAW_VALUE", "L1", location, "raw source value")
            )
    return violations


def _l1_slot_and_interval_checks(
    briefing: Briefing, context: GateContext
) -> list[Violation]:
    violations: list[Violation] = []
    if context.check_slot:
        local = briefing.slot.astimezone(ZoneInfo(context.limits.timezone)).time()
        if not (context.limits.allowed_start <= local < context.limits.allowed_end):
            violations.append(
                Violation(
                    "L1_SLOT_OUTSIDE_ALLOWED_HOURS",
                    "L1",
                    "slot",
                    "slot outside allowed hours",
                )
            )
    merged_free = _merge_intervals(context.free_intervals)
    for action in _iter_actions(briefing):
        location = _action_location(action.id)
        if action.proposed_start < briefing.slot:
            violations.append(
                Violation(
                    "L1_ACTION_BEFORE_SLOT",
                    "L1",
                    location,
                    "action starts before the briefing slot",
                )
            )
        start, end = action.proposed_start, action.proposed_end
        if any(
            start < busy.end and busy.start < end for busy in context.busy_intervals
        ):
            violations.append(
                Violation(
                    "L1_ACTION_IN_BUSY_INTERVAL",
                    "L1",
                    location,
                    "action overlaps a busy interval",
                )
            )
        elif not any(
            free_start <= start and end <= free_end
            for free_start, free_end in merged_free
        ):
            violations.append(
                Violation(
                    "L1_ACTION_NOT_FREE",
                    "L1",
                    location,
                    "action is not fully inside free time",
                )
            )
        lowered = action.text.casefold()
        if any(term in lowered for term in _REPO_TERMS):
            violations.append(
                Violation(
                    "L1_ACTION_TARGETS_REPO",
                    "L1",
                    location,
                    "action targets this repo",
                )
            )
    return violations


def _ref_backs_token(value: float, places: int, token_abs: Decimal) -> bool:
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return abs(rounded) == token_abs


def _l1b_checks(briefing: Briefing, context: GateContext) -> list[Violation]:
    violations: list[Violation] = []
    for section_type, claim in _iter_claims(briefing):
        location = _claim_location(section_type, claim.id)
        known_ids = set(claim.fact_ids) | {ref.metric_id for ref in claim.metric_refs}
        if not claim.fact_ids and not claim.metric_refs:
            violations.append(
                Violation(
                    "L1B_CLAIM_WITHOUT_EVIDENCE",
                    "L1b",
                    location,
                    "claim has no fact or metric evidence",
                )
            )
        for fact_id in claim.fact_ids:
            fact = context.facts.get(fact_id)
            if fact is None or fact.subject_id != briefing.subject_id:
                violations.append(
                    Violation(
                        "L1B_UNKNOWN_FACT",
                        "L1b",
                        location,
                        "fact is unknown or belongs to another subject",
                    )
                )
        for token in extract_number_tokens(claim.text, known_ids):
            if not any(
                _ref_backs_token(ref.value, token.places, abs(token.value))
                for ref in claim.metric_refs
            ):
                violations.append(
                    Violation(
                        "L1B_NUMBER_WITHOUT_METRIC_REF",
                        "L1b",
                        location,
                        "number token has no backing metric ref",
                    )
                )
        if section_type == "since_last":
            continue
        for ref in claim.metric_refs:
            if ref.metric_id not in context.metrics.values:
                violations.append(
                    Violation(
                        "L1B_UNKNOWN_METRIC",
                        "L1b",
                        location,
                        "metric is absent from the snapshot",
                    )
                )
            elif Decimal(str(ref.value)) != Decimal(
                str(context.metrics.values[ref.metric_id])
            ):
                violations.append(
                    Violation(
                        "L1B_METRIC_VALUE_MISMATCH",
                        "L1b",
                        location,
                        "metric value differs from the snapshot",
                    )
                )
    parent_id = briefing.parent_briefing_id
    if parent_id is not None:
        if (
            context.parent_briefing is None
            or context.parent_metrics is None
            or context.parent_briefing.id != parent_id
            or context.parent_briefing.profile_id != briefing.profile_id
            or context.parent_briefing.subject_id != briefing.subject_id
            or not (context.parent_briefing.slot < briefing.slot)
        ):
            violations.append(
                Violation(
                    "L1B_PARENT_MISMATCH",
                    "L1b",
                    "parent_briefing_id",
                    "parent briefing does not match the context",
                )
            )
        since_last = next(
            (section for section in briefing.sections if section.type == "since_last"),
            None,
        )
        if since_last is None:
            violations.append(
                Violation(
                    "L1B_MISSING_SINCE_LAST",
                    "L1b",
                    "sections",
                    "parent briefing requires a since_last section",
                )
            )
        else:
            parent_values = (
                context.parent_metrics.values
                if context.parent_metrics is not None
                else None
            )
            for claim in since_last.claims:
                location = _claim_location(since_last.type, claim.id)
                for ref in claim.metric_refs:
                    if (
                        ref.metric_id not in context.metrics.values
                        or parent_values is None
                        or ref.metric_id not in parent_values
                    ) or Decimal(str(ref.value)) != (
                        Decimal(str(context.metrics.values[ref.metric_id]))
                        - Decimal(str(parent_values[ref.metric_id]))
                    ):
                        violations.append(
                            Violation(
                                "L1B_DELTA_MISMATCH",
                                "L1b",
                                location,
                                "metric value differs from current-minus-parent",
                            )
                        )
    else:
        if context.parent_briefing is not None or context.parent_metrics is not None:
            violations.append(
                Violation(
                    "L1B_PARENT_MISMATCH",
                    "L1b",
                    "parent_briefing_id",
                    "parent briefing does not match the context",
                )
            )
        for section in briefing.sections:
            if section.type != "since_last":
                continue
            violations.append(
                Violation(
                    "L1B_SINCE_LAST_WITHOUT_PARENT",
                    "L1b",
                    _section_location(section.type),
                    "since_last section has no parent briefing",
                )
            )
            for claim in section.claims:
                location = _claim_location(section.type, claim.id)
                for ref in claim.metric_refs:
                    violations.append(
                        Violation(
                            "L1B_DELTA_MISMATCH",
                            "L1b",
                            location,
                            "metric value differs from current-minus-parent",
                        )
                    )
    return violations


def evaluate_briefing(
    raw: Briefing | Mapping[str, Any], context: GateContext
) -> GateResult:
    """Gate one briefing against reference data (pure, deterministic)."""
    pre_scan: list[Violation] = []
    unknown_indexes: set[int] = set()
    raw_obj = cast("object", raw)
    if isinstance(raw_obj, Briefing):
        briefing = raw_obj
    elif not isinstance(raw_obj, Mapping):
        return _finish(
            [
                Violation(
                    "L0_SCHEMA_INVALID",
                    "L0",
                    "briefing",
                    "briefing does not match the schema",
                )
            ]
        )
    else:
        raw_mapping = cast("Mapping[str, Any]", raw_obj)
        sections_obj: object = raw_mapping.get("sections")
        if isinstance(sections_obj, list):
            sections = cast("list[Any]", sections_obj)
            for index in range(len(sections)):
                section_obj: object = sections[index]
                if isinstance(section_obj, dict):
                    raw_section = cast("dict[str, Any]", section_obj)
                    section_type: object = raw_section.get("type")
                else:
                    section_type = None
                if (
                    not isinstance(section_type, str)
                    or section_type not in KNOWN_SECTION_TYPES
                ):
                    unknown_indexes.add(index)
                    pre_scan.append(
                        Violation(
                            "L0_UNKNOWN_SECTION",
                            "L0",
                            f"sections[{index}]",
                            "unknown section type",
                        )
                    )
        try:
            briefing = Briefing.model_validate(raw)
        except ValidationError as exc:
            schema_errors: list[Violation] = []
            for error in exc.errors():
                loc = error.get("loc", ())
                if (
                    len(loc) == 3
                    and loc[0] == "sections"
                    and isinstance(loc[1], int)
                    and loc[1] in unknown_indexes
                    and loc[2] == "type"
                ):
                    continue
                location = ".".join(str(part) for part in loc)
                schema_errors.append(
                    Violation(
                        "L0_SCHEMA_INVALID",
                        "L0",
                        location,
                        "briefing does not match the schema",
                    )
                )
            return _finish(pre_scan + schema_errors)
    violations = list(pre_scan)
    violations.extend(_l0_counts(briefing, context))
    violations.extend(_l1_text_checks(briefing, context))
    violations.extend(_l1_metric_ref_raw_check(briefing, context))
    violations.extend(_l1_slot_and_interval_checks(briefing, context))
    violations.extend(_l1b_checks(briefing, context))
    return _finish(violations)


def _finish(violations: list[Violation]) -> GateResult:
    seen: set[tuple[str, str]] = set()
    unique: list[Violation] = []
    for violation in sorted(violations, key=lambda v: (v.layer, v.code, v.location)):
        key = (violation.code, violation.location)
        if key not in seen:
            seen.add(key)
            unique.append(violation)
    return GateResult(violations=tuple(unique))
