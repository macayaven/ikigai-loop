"""Ticket 8: deterministic briefing gate (L0 structure, L1 rules, L1b).

No network, no model call, no env read, no clock read: all times come from
the briefing/context. Messages never interpolate a matched secret, email,
private term, or raw value. Identical ``(code, location)`` pairs are
de-duplicated once at the end; the result is sorted by
``(layer, code, location)`` so section input order cannot change it.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from framework.briefing.context import GateContext, ProfileLimits, TimeInterval
from framework.briefing.labels import MetricBinding, metric_label_binding
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
_ADVICE_SINGLES = frozenset(
    [
        "should",
        "must",
        "diet",
        "diets",
        "calorie",
        "calories",
        "medication",
        "medications",
        "medicine",
        "medicines",
        "dose",
        "doses",
        "dosage",
        "dosages",
        "symptom",
        "symptoms",
        "diagnosis",
        "diagnoses",
        "treatment",
        "treatments",
        "therapy",
        "therapies",
        "intensity",
        "shouldn't",
        "mustn't",
    ]
)
_ADVICE_PHRASES = ("push harder", "rest more")
_PERIOD_WORDS = ("earlier", "prior", "last")
_UP_WORDS = frozenset(
    [
        "up",
        "rose",
        "rise",
        "rises",
        "rising",
        "risen",
        "increase",
        "increased",
        "increases",
        "increasing",
        "more",
        "higher",
        "grew",
        "grow",
        "grows",
        "growing",
        "grown",
    ]
)
_DOWN_WORDS = frozenset(
    [
        "down",
        "fell",
        "fall",
        "falls",
        "falling",
        "fallen",
        "decrease",
        "decreased",
        "decreases",
        "decreasing",
        "less",
        "fewer",
        "lower",
        "dropped",
        "drop",
        "drops",
        "dropping",
    ]
)
_PERIOD_ORDER = {"earlier": 0, "prior": 1, "last": 2}
_DIRECTION_TOKEN_RE = re.compile(r"\w+(?:-\w+)*")
_PERIOD_MESSAGE = "period words do not match the cited metrics"


def text_check_codes(
    text: str,
    *,
    private_terms: tuple[str, ...] = (),
    forbidden_raw_literals: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """L1 text verdicts for one text; never ``L1_ACTION_TARGETS_REPO``."""
    codes: list[str] = []
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        codes.append("L1_SECRET")
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        codes.append("L1_PII")
    normalized = _collapse(text).replace("\u2019", "'").replace("\u2018", "'")
    if any(_contains_token(normalized, word) for word in _ADVICE_SINGLES) or any(
        _contains_token(normalized, phrase) for phrase in _ADVICE_PHRASES
    ):
        codes.append("L1_ADVICE")
    collapsed_terms = [_collapse(term) for term in private_terms]
    collapsed = _collapse(text)
    for term in collapsed_terms:
        if not term:
            continue
        if len(term) <= 3:
            hit = _contains_token(collapsed, term)
        else:
            hit = term in collapsed
        if hit:
            codes.append("L1_PRIVATE_TERM")
            break
    if any(
        _contains_token(collapsed, _collapse(literal))
        for literal in forbidden_raw_literals
        if _collapse(literal)
    ):
        codes.append("L1_RAW_VALUE")
    return tuple(codes)


def action_targets_repo(text: str) -> bool:
    """Whether action text names this repo."""
    lowered = text.casefold()
    return any(term in lowered for term in _REPO_TERMS)


_ACTION_WINDOW_MESSAGES = {
    "L1_ACTION_BEFORE_SLOT": "action starts before the briefing slot",
    "L1_ACTION_IN_BUSY_INTERVAL": "action overlaps a busy interval",
    "L1_ACTION_NOT_FREE": "action is not fully inside free time",
}


def action_window_codes(
    start: datetime,
    end: datetime,
    *,
    slot: datetime,
    busy_intervals: tuple[TimeInterval, ...],
    free_intervals: tuple[TimeInterval, ...],
) -> tuple[str, ...]:
    """Window verdicts for one proposed range; no env, clock or network."""
    codes: list[str] = []
    if start < slot:
        codes.append("L1_ACTION_BEFORE_SLOT")
    if any(start < busy.end and busy.start < end for busy in busy_intervals):
        codes.append("L1_ACTION_IN_BUSY_INTERVAL")
    elif not any(
        free_start <= start and end <= free_end
        for free_start, free_end in _merge_intervals(free_intervals)
    ):
        codes.append("L1_ACTION_NOT_FREE")
    return tuple(codes)


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


_TEXT_MESSAGES = {
    "L1_SECRET": "secret-like token",
    "L1_PII": "contact detail",
    "L1_ADVICE": "advice-like wording",
    "L1_PRIVATE_TERM": "private term",
    "L1_RAW_VALUE": "raw source value",
}


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
    for _kind, _owner, text, location in _iter_texts(briefing):
        for code in text_check_codes(
            text,
            private_terms=context.private_terms if check_terms else (),
            forbidden_raw_literals=context.forbidden_raw_literals,
        ):
            violations.append(Violation(code, "L1", location, _TEXT_MESSAGES[code]))
    return violations


def _l1_commitment_checks(briefing: Briefing, context: GateContext) -> list[Violation]:
    violations: list[Violation] = []
    if not context.commitments_available:
        violations.append(
            Violation(
                "L1_COMMITMENTS_UNAVAILABLE",
                "L1",
                "briefing",
                "commitments unavailable",
            )
        )
        return violations
    by_id = {commitment.id: commitment for commitment in context.commitments}
    for action in _iter_actions(briefing):
        location = _action_location(action.id)
        commitment = by_id.get(action.commitment_id)
        if commitment is None or commitment.profile_id != briefing.profile_id:
            violations.append(
                Violation(
                    "L1_ACTION_NOT_COMMITTED",
                    "L1",
                    location,
                    "action is not a user commitment",
                )
            )
            continue
        if (
            _collapse(action.text) != _collapse(commitment.title)
            or action.kind != commitment.kind
            or action.dimension != commitment.dimension
        ):
            violations.append(
                Violation(
                    "L1_ACTION_TEXT_MISMATCH",
                    "L1",
                    location,
                    "action differs from its commitment",
                )
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
        for code in slot_window_codes(briefing.slot, context.limits):
            violations.append(
                Violation(
                    code,
                    "L1",
                    "slot",
                    _SLOT_MESSAGES[code],
                )
            )
    for action in _iter_actions(briefing):
        location = _action_location(action.id)
        for code in action_window_codes(
            action.proposed_start,
            action.proposed_end,
            slot=briefing.slot,
            busy_intervals=context.busy_intervals,
            free_intervals=context.free_intervals,
        ):
            violations.append(
                Violation(code, "L1", location, _ACTION_WINDOW_MESSAGES[code])
            )
        if action_targets_repo(action.text):
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


def _is_raw_ref(metric_id: str, context: GateContext) -> bool:
    return metric_id in context.raw_metric_ids or metric_id.startswith("raw.")


def _label_in_text(binding: MetricBinding, collapsed: str) -> bool:
    return any(_contains_token(collapsed, _collapse(label)) for label in binding.labels)


def _binding_violations(
    section_type: str, claim: Claim, context: GateContext, location: str
) -> list[Violation]:
    violations: list[Violation] = []
    remaining = [
        ref for ref in claim.metric_refs if not _is_raw_ref(ref.metric_id, context)
    ]
    if not remaining:
        return violations
    bindings: list[MetricBinding | None] = [
        metric_label_binding(ref.metric_id) for ref in remaining
    ]
    if any(binding is None for binding in bindings):
        violations.append(
            Violation(
                "L1B_METRIC_LABEL_UNKNOWN",
                "L1b",
                location,
                "metric family is unknown",
            )
        )
        return violations
    known = [binding for binding in bindings if binding is not None]
    collapsed = _collapse(claim.text)
    if len(remaining) == 1:
        binding = known[0]
        if not _label_in_text(binding, collapsed):
            violations.append(
                Violation(
                    "L1B_METRIC_LABEL_MISSING",
                    "L1b",
                    location,
                    "claim does not name the cited metric",
                )
            )
        if binding.period is not None and not _contains_token(
            collapsed, binding.period
        ):
            violations.append(
                Violation(
                    "L1B_PERIOD_WORD_MISSING",
                    "L1b",
                    location,
                    _PERIOD_MESSAGE,
                )
            )
        if binding.requires_cancel and "cancel" not in collapsed:
            violations.append(
                Violation(
                    "L1B_METRIC_LABEL_MISSING",
                    "L1b",
                    location,
                    "claim does not name the cited metric",
                )
            )
    else:
        periods = [binding.period for binding in known]
        families = {binding.family for binding in known}
        eligible = (
            2 <= len(remaining) <= 3
            and all(period is not None for period in periods)
            and len(families) == 1
            and len(set(periods)) == len(periods)
        )
        if not eligible:
            violations.append(
                Violation(
                    "L1B_TOO_MANY_METRICS",
                    "L1b",
                    location,
                    "claim cites metrics outside one comparison",
                )
            )
            return violations
        if not _label_in_text(known[0], collapsed):
            violations.append(
                Violation(
                    "L1B_METRIC_LABEL_MISSING",
                    "L1b",
                    location,
                    "claim does not name the cited metric",
                )
            )
        for period in periods:
            assert period is not None
            if not _contains_token(collapsed, period):
                violations.append(
                    Violation(
                        "L1B_PERIOD_WORD_MISSING",
                        "L1b",
                        location,
                        _PERIOD_MESSAGE,
                    )
                )
                break
    if section_type != "since_last":
        cited = {binding.period for binding in known if binding.period is not None}
        named = {word for word in _PERIOD_WORDS if _contains_token(collapsed, word)}
        if named != cited:
            violations.append(
                Violation(
                    "L1B_PERIOD_WORD_MISSING",
                    "L1b",
                    location,
                    _PERIOD_MESSAGE,
                )
            )
    label_tokens: set[str] = set()
    for binding in known:
        for label in binding.labels:
            label_tokens.update(_DIRECTION_TOKEN_RE.findall(_collapse(label)))
    tokens = set(_DIRECTION_TOKEN_RE.findall(collapsed)) - label_tokens
    up_hit = bool(tokens & _UP_WORDS)
    down_hit = bool(tokens & _DOWN_WORDS)
    if up_hit and down_hit:
        violations.append(
            Violation(
                "L1B_DIRECTION_MISMATCH",
                "L1b",
                location,
                "direction words disagree with the cited values",
            )
        )
    elif up_hit or down_hit:
        side = "up" if up_hit else "down"
        if section_type == "since_last":
            signs = {
                (Decimal(str(ref.value)) > 0, Decimal(str(ref.value)) < 0)
                for ref in remaining
            }
            if signs != ({(True, False)} if side == "up" else {(False, True)}):
                violations.append(
                    Violation(
                        "L1B_DIRECTION_MISMATCH",
                        "L1b",
                        location,
                        "direction words disagree with the cited values",
                    )
                )
        elif len(remaining) == 1:
            violations.append(
                Violation(
                    "L1B_DIRECTION_MISMATCH",
                    "L1b",
                    location,
                    "direction words disagree with the cited values",
                )
            )
        else:
            pairs = [
                (binding.period, ref.value)
                for binding, ref in zip(known, remaining)
                if binding.period is not None
            ]
            ordered = sorted(pairs, key=lambda pair: _PERIOD_ORDER[pair[0]])
            diffs = [
                Decimal(str(later)) - Decimal(str(earlier))
                for (_, earlier), (_, later) in itertools.pairwise(ordered)
            ]
            agree = (
                all(diff > 0 for diff in diffs)
                if side == "up"
                else all(diff < 0 for diff in diffs)
            )
            if not agree:
                violations.append(
                    Violation(
                        "L1B_DIRECTION_MISMATCH",
                        "L1b",
                        location,
                        "direction words disagree with the cited values",
                    )
                )
    return violations


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
        violations.extend(_binding_violations(section_type, claim, context, location))
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
    violations.extend(_l1_commitment_checks(briefing, context))
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


def collapse_text(text: str) -> str:
    """Ticket 17a: public wrapper over ``_collapse``; nothing else changed."""
    return _collapse(text)


def contains_token(text: str, literal: str) -> bool:
    """Ticket 17a: public wrapper over ``_contains_token``; nothing else changed."""
    return _contains_token(text, literal)


def ref_backs_token(value: float, places: int, token_abs: Decimal) -> bool:
    """Ticket 17a: public wrapper over ``_ref_backs_token``.

    Fail closed: an ``InvalidOperation`` from rounding means no backing,
    never a traceback.
    """
    import decimal

    try:
        return _ref_backs_token(value, places, token_abs)
    except decimal.InvalidOperation:
        return False


def word_list_hit(text: str, words: tuple[str, ...] | list[str]) -> bool:
    """Ticket 17a: whole-token match over caller words, like the advice arm."""
    normalized = _collapse(text).replace("\u2019", "'").replace("\u2018", "'")
    return any(
        bool(word)
        and _contains_token(
            normalized, _collapse(word).replace("\u2019", "'").replace("\u2018", "'")
        )
        for word in words
    )


def direction_sides(
    text: str, *, exclude_words: tuple[str, ...] | list[str]
) -> frozenset[str]:
    """Ticket 17a: direction sides named in ``text``, minus label tokens."""
    excluded: set[str] = set()
    for word in exclude_words:
        excluded.update(_DIRECTION_TOKEN_RE.findall(_collapse(word)))
    tokens = set(_DIRECTION_TOKEN_RE.findall(_collapse(text))) - excluded
    sides: set[str] = set()
    if tokens & _UP_WORDS:
        sides.add("up")
    if tokens & _DOWN_WORDS:
        sides.add("down")
    return frozenset(sides)


ADVICE_WORDS: tuple[str, ...] = tuple(sorted(_ADVICE_SINGLES)) + tuple(_ADVICE_PHRASES)
"""Ticket 17a: the gate's pinned advice list, for callers replicating it."""

ADVICE_PHRASES = _ADVICE_PHRASES
UP_WORDS = _UP_WORDS
DOWN_WORDS = _DOWN_WORDS
PERIOD_WORDS = _PERIOD_WORDS

_SLOT_MESSAGES = {
    "L1_SLOT_OUTSIDE_ALLOWED_HOURS": "slot outside allowed hours",
}


def slot_window_codes(slot: datetime, limits: ProfileLimits) -> tuple[str, ...]:
    """Slot verdicts against the allowed window; one truth for gate and core."""
    local = slot.astimezone(ZoneInfo(limits.timezone)).time()
    if not (limits.allowed_start <= local < limits.allowed_end):
        return ("L1_SLOT_OUTSIDE_ALLOWED_HOURS",)
    return ()


_OUTBOUND_ALLOWLIST = frozenset(
    {"L1_SECRET", "L1_PII", "L1_PRIVATE_TERM", "L1_RAW_VALUE"}
)


def scan_outbound_text(
    text: str,
    *,
    private_terms: tuple[str, ...] = (),
    private_terms_available: bool,
    forbidden_raw_literals: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Pre-send verdicts for one outbound string; allowlisted codes only."""
    if not private_terms_available:
        return ("L1_PRIVATE_TERMS_UNAVAILABLE",)
    return tuple(
        code
        for code in text_check_codes(
            text,
            private_terms=private_terms,
            forbidden_raw_literals=forbidden_raw_literals,
        )
        if code in _OUTBOUND_ALLOWLIST
    )
