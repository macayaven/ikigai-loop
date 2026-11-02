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
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from pydantic import ValidationError

import framework.briefing.claim_text as claim_text_lists
from framework.briefing.claim_text import (
    STEADY_WORDS,
    claim_text_codes,
    counted_periods,
    direction_side,
    drop_tied_to,
    fact_claim_codes,
    has_negator,
    hyphen_directions,
    stated_zero_code,
    steady_same_counts,
    without_count_held,
)

UP_WORDS = claim_text_lists.UP_WORDS
DOWN_WORDS = claim_text_lists.DOWN_WORDS
PERIOD_WORDS = claim_text_lists.PERIOD_WORDS
ADVICE_PHRASES = claim_text_lists.ADVICE_PHRASES
from framework.briefing.context import GateContext, ProfileLimits, TimeInterval
from framework.briefing.labels import MetricBinding, metric_label_binding
from framework.briefing.normalize import normalize_text
from framework.briefing.numbers import (
    blank_known_names,
    extract_number_tokens,
    find_known_names,
    token_backed_by,
)
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
_PERIOD_ORDER = {"earlier": 0, "prior": 1, "last": 2}
_DIRECTION_TOKEN_RE = re.compile(r"\w+(?:-\w+)*")
_PERIOD_MESSAGE = "period words do not match the cited metrics"


def _squashed_hit(normalized: str, term: str) -> bool:
    """Token-aligned squashed match for terms of 5 or more characters."""
    squashed: list[str] = []
    index_map: list[int] = []
    for pos, char in enumerate(normalized):
        if not char.isalnum():
            continue
        squashed.append(char)
        index_map.append(pos)
    if not squashed:
        return False
    squashed_term = "".join(c for c in term if c.isalnum())
    if len(squashed_term) < 5:
        return False
    joined = "".join(squashed)
    start = 0
    while True:
        index = joined.find(squashed_term, start)
        if index < 0:
            return False
        first = index_map[index]
        last = index_map[index + len(squashed_term) - 1]
        before = normalized[first - 1] if first > 0 else ""
        after = normalized[last + 1] if last + 1 < len(normalized) else ""
        if not (before.isalnum() or before == "_") and not (
            after.isalnum() or after == "_"
        ):
            return True
        start = index + 1


def _sequence_hit(normalized: str, literal: str) -> bool:
    """Token-sequence match of ``literal`` ignoring punctuation between."""
    want = _DIRECTION_TOKEN_RE.findall(literal)
    if not want:
        return False
    got = _DIRECTION_TOKEN_RE.findall(normalized)
    return any(got[i : i + len(want)] == want for i in range(len(got) - len(want) + 1))


def text_check_codes(
    text: str,
    *,
    private_terms: tuple[str, ...] = (),
    forbidden_raw_literals: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """L1 text verdicts for one text; never ``L1_ACTION_TARGETS_REPO``.

    Matching runs on the ``normalize_text`` copy (casefolded locally), so
    full-width, accented and confusable spellings read as their base
    letters. Unsafe characters are stripped for matching here and never
    reported; the claim path rejects them outright instead.
    """
    codes: list[str] = []
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        codes.append("L1_SECRET")
    if _EMAIL_RE.search(text) or _PHONE_RE.search(text):
        codes.append("L1_PII")
    normalized = normalize_text(text).casefold()
    if any(_contains_token(normalized, word) for word in _ADVICE_SINGLES) or any(
        _contains_token(normalized, phrase) for phrase in ADVICE_PHRASES
    ):
        codes.append("L1_ADVICE")
    for raw_term in private_terms:
        term = normalize_text(raw_term).casefold()
        if not term:
            continue
        if len(term) <= 3:
            hit = _contains_token(normalized, term)
        elif term in normalized:
            hit = True
        else:
            hit = _squashed_hit(normalized, term)
        if hit:
            codes.append("L1_PRIVATE_TERM")
            break
    for raw_literal in forbidden_raw_literals:
        literal = normalize_text(raw_literal).casefold()
        if literal and _sequence_hit(normalized, literal):
            codes.append("L1_RAW_VALUE")
            break
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

_CLAIM_MESSAGES = {
    "L1_UNSAFE_TEXT": (
        "write the text plainly, with no invisible characters "
        "and no words spelled out letter by letter"
    ),
    "L1_CLAIM_LANGUAGE": "write the claim in English so it can be checked",
    "L1_ADVICE": (
        "state what the data shows, with no question, instruction or suggestion"
    ),
    "L1_PRIVATE_TERM": "private term",
    "L1_RAW_VALUE": "raw source value",
    "L1B_UNVERIFIABLE_QUANTITY": (
        "state the digits from the cited metric instead of a quantity word"
    ),
    "L1B_NEGATED_CLAIM": "state the value or direction positively",
    "L1B_SINCE_LAST_WORDING": "write the change as since the last card",
    "L1B_COMPARISON_WORD_UNKNOWN": (
        "write the comparison with a pinned direction word, the cited "
        "label, its periods and its values only"
    ),
    "L1B_UNIT_MISMATCH": "use the unit of the cited metric",
    "L1B_METRIC_LABEL_MISMATCH": "name only the metric the claim cites",
    "L1B_VALUE_PERIOD_MISMATCH": ("write each cited value next to its own period word"),
    "L1_TEXT_TOO_LONG": "text is too long to check",
    "L1B_NUMBER_WITHOUT_METRIC_REF": "number token has no backing metric ref",
    "L1B_DIRECTION_MISMATCH": ("direction words disagree with the cited values"),
    "L1B_PERIOD_WORD_MISSING": _PERIOD_MESSAGE,
    "L1B_METRIC_LABEL_MISSING": "claim does not name the cited metric",
}

_CLAIM_LAYERS: dict[str, Layer] = {
    "L1_UNSAFE_TEXT": "L1",
    "L1_CLAIM_LANGUAGE": "L1",
    "L1_ADVICE": "L1",
    "L1_PRIVATE_TERM": "L1",
    "L1_RAW_VALUE": "L1",
    "L1_TEXT_TOO_LONG": "L1",
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
        if len(text) > _MAX_TEXT_LENGTH:
            violations.append(
                Violation(
                    "L1_TEXT_TOO_LONG",
                    "L1",
                    location,
                    _CLAIM_MESSAGES["L1_TEXT_TOO_LONG"],
                )
            )
            continue
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


_MAX_TEXT_LENGTH = 2000
_TWO_POW_53 = Decimal(2**53)


def _ref_value_mismatch(ref_value: float, snapshot_value: float) -> bool:
    """Whether a ref value differs from the snapshot value.

    Compares exact decimals of the shortest printed forms, and treats any
    ref value at or above 2 to the 53rd in magnitude as a mismatch: two
    integers up there can share one float.
    """
    ref_dec = Decimal(repr(ref_value))
    if abs(ref_dec) >= _TWO_POW_53:
        return True
    return ref_dec != Decimal(repr(snapshot_value))


def _ref_backs_token(
    value: float,
    places: int,
    token_abs: Decimal,
    *,
    signed: bool = False,
    section_type: str = "working",
) -> bool:
    """Whether ``value`` backs a token; a failed rounding backs nothing."""
    return token_backed_by(
        value, places, token_abs, signed=signed, section_type=section_type
    )


def _is_raw_ref(metric_id: str, context: GateContext) -> bool:
    return metric_id in context.raw_metric_ids or metric_id.startswith("raw.")


def _binding_label_hit(binding: MetricBinding, lower: str) -> bool:
    return any(
        _contains_token(lower, normalize_text(label).casefold())
        for label in binding.labels
    )


def _than_sentences(lower: str) -> list[str]:
    """Split ``lower`` at sentence ends; a decimal point is not one."""
    bounds: list[int] = [0]
    for match in re.finditer(r"[.!?]", lower):
        if (
            match.group(0) == "."
            and match.start() > 0
            and lower[match.start() - 1].isdigit()
            and match.end() < len(lower)
            and lower[match.end()].isdigit()
        ):
            continue
        bounds.append(match.end())
    bounds.append(len(lower))
    return [lower[bounds[i] : bounds[i + 1]] for i in range(len(bounds) - 1)]


def _than_decision(
    lower: str,
    side: str,
    remaining: list[Any],
    known: list[MetricBinding],
) -> bool | None:
    """Up/down verdict from ``A ... than ... B`` naming order, if present.

    With exactly two refs in two different periods and text naming period
    A, then ``than``, then period B inside one sentence, the up side agrees
    only when A's value is above B's and the down side only when A's value
    is below B's. Any other shape returns ``None`` for time-order logic.
    """
    from framework.briefing.claim_text import remove_period_phrases

    if side not in ("up", "down") or len(remaining) != 2:
        return None
    periods = [binding.period for binding in known]
    if any(period is None for period in periods) or periods[0] == periods[1]:
        return None
    by_period = {
        binding.period: Decimal(str(ref.value))
        for binding, ref in zip(known, remaining)
        if binding.period is not None
    }
    for sentence in _than_sentences(remove_period_phrases(lower)):
        mentioned: list[tuple[int, str]] = []
        for period in PERIOD_WORDS:
            for match in re.finditer(r"(?<!\w)" + period + r"(?!\w)", sentence):
                mentioned.append((match.start(), period))
        mentioned.sort()
        than = next(
            (match.start() for match in re.finditer(r"(?<!\w)than(?!\w)", sentence)),
            None,
        )
        if than is None:
            continue
        before = [period for pos, period in mentioned if pos < than]
        after = [period for pos, period in mentioned if pos > than]
        if not before or not after or before[-1] == after[0]:
            continue
        if before[-1] not in by_period or after[0] not in by_period:
            continue
        first, second = by_period[before[-1]], by_period[after[0]]
        return first > second if side == "up" else first < second
    return None


def _direction_mismatch(
    section_type: str,
    side: str,
    remaining: list[Any],
    known: list[MetricBinding],
    lower: str = "",
) -> bool:
    if side == "mixed":
        return True
    if section_type == "since_last":
        if side == "same":
            return any(ref.value != 0 for ref in remaining)
        signs = {
            (Decimal(str(ref.value)) > 0, Decimal(str(ref.value)) < 0)
            for ref in remaining
        }
        return signs != ({(True, False)} if side == "up" else {(False, True)})
    decision = _than_decision(lower, side, remaining, known)
    if decision is not None:
        return not decision
    if len(remaining) == 1:
        return True
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
    if side == "same":
        return not all(diff == 0 for diff in diffs)
    if side == "up":
        return not all(diff > 0 for diff in diffs)
    return not all(diff < 0 for diff in diffs)


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
    lower = normalize_text(claim.text).casefold()
    held = without_count_held(claim.text).casefold()
    # In a since_last claim the delta is the change since the last card,
    # so there `last card` names the last period; everywhere else it stays
    # a non-period sense.
    if section_type == "since_last":
        period_text = re.sub(r"(?<!\w)last card(?!\w)", "last", lower)
        period_text = re.sub(
            r"(?<!\w)since the previous card(?!\w)", "since the last", period_text
        )
    else:
        period_text = lower
    named = counted_periods(period_text)
    if len(remaining) == 1:
        binding = known[0]
        if not _binding_label_hit(binding, lower):
            violations.append(
                Violation(
                    "L1B_METRIC_LABEL_MISSING",
                    "L1b",
                    location,
                    "claim does not name the cited metric",
                )
            )
        if binding.period is not None and binding.period not in named:
            violations.append(
                Violation(
                    "L1B_PERIOD_WORD_MISSING",
                    "L1b",
                    location,
                    _PERIOD_MESSAGE,
                )
            )
        if binding.requires_cancel and "cancel" not in lower:
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
        if not _binding_label_hit(known[0], lower):
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
            if period not in named:
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
        if named != cited:
            violations.append(
                Violation(
                    "L1B_PERIOD_WORD_MISSING",
                    "L1b",
                    location,
                    _PERIOD_MESSAGE,
                )
            )
    negator_ids = [ref.metric_id for ref in remaining]
    stated_zero = (
        has_negator(lower, negator_ids)
        and stated_zero_code(
            lower,
            [(ref.metric_id, ref.value) for ref in remaining],
            {label.casefold() for binding in known for label in binding.labels},
        )
        is None
    )
    if not has_negator(lower, negator_ids) or stated_zero:
        label_tokens: set[str] = set()
        for binding in known:
            for label in binding.labels:
                label_tokens.update(
                    _DIRECTION_TOKEN_RE.findall(normalize_text(label).casefold())
                )
        held = drop_tied_to(held)
        tokens = set(_DIRECTION_TOKEN_RE.findall(held)) - label_tokens
        tokens |= hyphen_directions(held)
        if tokens & STEADY_WORDS and not steady_same_counts(
            held, [label for binding in known for label in binding.labels]
        ):
            tokens -= STEADY_WORDS
        side = direction_side(tokens, metric_claim=True)
        if side is not None and _direction_mismatch(
            section_type, side, remaining, known, lower
        ):
            violations.append(
                Violation(
                    "L1B_DIRECTION_MISMATCH",
                    "L1b",
                    location,
                    "direction words disagree with the cited values",
                )
            )
    return violations


def _signed_tokens(
    text: str, known_names: Collection[str], tokens: Any
) -> dict[int, bool]:
    """Whether each number token carries a minus sign (D8 sign rule).

    A ``-`` directly before the token counts as a sign unless it sits
    between two digits (a range dash, as in G12's ``3-5``).
    """
    blanked = blank_known_names(normalize_text(text), known_names)
    signed: dict[int, bool] = {}
    for token in tokens:
        at_sign = blanked[token.start : token.start + 1] == "-"
        before_sign = (
            token.start > 0
            and blanked[token.start - 1 : token.start] == "-"
            and (token.start < 2 or not blanked[token.start - 2].isdigit())
        )
        signed[token.start] = at_sign or before_sign
    return signed


def _l1b_checks(briefing: Briefing, context: GateContext) -> list[Violation]:
    violations: list[Violation] = []
    snapshot_ids = tuple(context.metrics.values.keys())
    for section_type, claim in _iter_claims(briefing):
        location = _claim_location(section_type, claim.id)
        if len(claim.text) > _MAX_TEXT_LENGTH:
            continue
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
        statements: list[str] = []
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
            else:
                statements.append(fact.statement)
        known_names = find_known_names(statements)
        tokens = extract_number_tokens(claim.text, known_ids, known_names)
        signed = _signed_tokens(claim.text, known_names, tokens)
        backed: dict[int, bool] = {}
        for token in tokens:
            token_backed = any(
                _ref_backs_token(
                    ref.value,
                    token.places,
                    abs(token.value),
                    signed=signed[token.start],
                    section_type=section_type,
                )
                for ref in claim.metric_refs
            )
            backed[token.start] = token_backed
            if not token_backed:
                violations.append(
                    Violation(
                        "L1B_NUMBER_WITHOUT_METRIC_REF",
                        "L1b",
                        location,
                        "number token has no backing metric ref",
                    )
                )
        has_backed_fifty = any(
            float(token.value) == 50 and backed[token.start] for token in tokens
        )
        cited_refs = [(ref.metric_id, ref.value) for ref in claim.metric_refs]
        for code in claim_text_codes(
            claim.text,
            section_type=section_type,
            has_metric_refs=bool(claim.metric_refs),
            cited_refs=cited_refs,
            cited_fact_statements=tuple(statements),
            has_backed_fifty=has_backed_fifty,
            snapshot_metric_ids=snapshot_ids,
            known_names=known_names,
            private_terms=(
                context.private_terms if context.private_terms_available else ()
            ),
            private_terms_available=context.private_terms_available,
            forbidden_raw_literals=tuple(context.forbidden_raw_literals),
            number_tokens=tokens,
            cited_ids=tuple(known_ids),
            titles=tuple(commitment.title for commitment in context.commitments),
        ):
            violations.append(
                Violation(
                    code,
                    _CLAIM_LAYERS.get(code, "L1b"),
                    location,
                    _CLAIM_MESSAGES[code],
                )
            )
        if claim.fact_ids and not claim.metric_refs:
            for code in fact_claim_codes(
                claim.text,
                tuple(statements),
                snapshot_metric_ids=snapshot_ids,
                known_ids=tuple(claim.fact_ids),
            ):
                violations.append(
                    Violation(
                        code,
                        "L1b",
                        location,
                        _CLAIM_MESSAGES[code],
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
            elif _ref_value_mismatch(ref.value, context.metrics.values[ref.metric_id]):
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


def ref_backs_token(value: float, places: int, signed_token: Decimal) -> bool:
    """Ticket 17a: public wrapper over ``_ref_backs_token``.

    ``signed_token`` carries the token's own sign: ``-7`` is not backed
    by ``7``, while ``7`` is backed by ``-7``. Bad decimals fail closed
    inside the backing function itself, never as a traceback.
    """
    signed = bool(signed_token.is_signed() and signed_token != 0)
    return _ref_backs_token(value, places, abs(signed_token), signed=signed)


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
    """Ticket 17a: direction sides named in ``text``, minus label tokens.

    Reads the same tokens as the gate's own direction arm over the
    normalised text: the ``held`` containment guard applies first, then
    hyphen compounds add their side. Same-direction words name no side
    here.
    """
    excluded: set[str] = set()
    for word in exclude_words:
        excluded.update(_DIRECTION_TOKEN_RE.findall(normalize_text(word).casefold()))
    held = drop_tied_to(without_count_held(text))
    tokens = set(_DIRECTION_TOKEN_RE.findall(held.casefold())) - excluded
    tokens |= hyphen_directions(held)
    if tokens & STEADY_WORDS and not steady_same_counts(held.casefold(), exclude_words):
        tokens -= STEADY_WORDS
    side = direction_side(tokens, metric_claim=True)
    if side == "mixed":
        return frozenset({"up", "down"})
    if side in ("up", "down"):
        return frozenset({side})
    return frozenset()


ADVICE_WORDS: tuple[str, ...] = tuple(sorted(_ADVICE_SINGLES)) + tuple(ADVICE_PHRASES)
"""Ticket 17a: the gate's pinned advice list, for callers replicating it."""

CLAIM_ADVICE_PHRASES = claim_text_lists.CLAIM_ADVICE_PHRASES
"""Ticket 10b: the claim path's whole advice phrase list, with ``ADVICE_WORDS``."""

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
