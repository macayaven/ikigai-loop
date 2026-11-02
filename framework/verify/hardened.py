"""Ticket 023: hardened public claim checker.

``check_claims`` runs every check the old ``verify_claims`` runs (by
calling it on the same input with ``units`` and ``periods`` removed),
then adds negation, quantity forms, units and period binding on top.
``verify_claims``, ``Report``, ``LIMITS_NOTE`` and ``verify_and_repair``
are untouched: they keep the earlier, smaller set of checks.

Made-up data only; no network, no model, no store.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from pydantic import ConfigDict, ValidationError, field_validator

from framework.briefing.claim_text import (
    DOWN_WORDS,
    SAME_WORDS,
    UP_WORDS,
    counted_periods,
    has_negator,
)
from framework.briefing.gate import (
    collapse_text,
    contains_token,
    direction_sides,
    ref_backs_token,
    text_check_codes,
    word_list_hit,
)
from framework.briefing.normalize import normalize_text
from framework.briefing.numbers import extract_number_tokens, token_backed_by
from framework.briefing.quantities import find_unverifiable_quantities, time_scope_hit
from framework.verify.core import (
    MAX_CLAIM_ID_CHARS,
    MAX_CLAIM_TEXT_CHARS,
    MAX_CLAIMS,
    MAX_INPUT_BYTES,
    MAX_JSON_DEPTH,
    MAX_LABEL_CHECKS,
    MAX_LABEL_WORDS,
    MAX_REFS_PER_CLAIM,
    MAX_SERIES_IDS,
    MAX_TERMS,
    MAX_TOTAL_CLAIM_TEXT_CHARS,
    MAX_WORD_CHARS,
    Report,
    VerifyInput,
    VerifyInputError,
    Violation,
    verify_claims,
)

HARDENED_LIMITS_NOTE = (
    "This check covers parseable numbers, cited sources, labels, direction, negation, quantity forms, "
    "and units and periods where you declare them. It does not check that a sentence is true. "
    "Without labels it cannot tell which metric a number belongs to, "
    "and a cited fact is only checked to exist. A check listed as not checked did not run."
)

UnitName = Literal["count", "hours", "minutes", "seconds", "days", "percent"]

_UNIT_NAMES = frozenset({"count", "hours", "minutes", "seconds", "days", "percent"})

HOURS_WORDS = frozenset({"hour", "hours", "hr", "hrs"})
MINUTES_WORDS = frozenset({"minute", "minutes", "min", "mins"})
SECONDS_WORDS = frozenset({"second", "seconds", "sec", "secs"})
DAYS_WORDS = frozenset({"day", "days"})
CALENDAR_WORDS = frozenset({"week", "weeks", "month", "months", "year", "years"})
TIME_WORDS = HOURS_WORDS | MINUTES_WORDS | SECONDS_WORDS | DAYS_WORDS | CALENDAR_WORDS
MAGNITUDE_WORDS = frozenset({"thousand", "million", "billion", "trillion"})
GLUED_TIME_LETTERS = frozenset(
    {"h", "hr", "hrs", "min", "mins", "m", "s", "sec", "secs"}
)
GLUED_MAGNITUDE_LETTERS = frozenset({"k", "m", "bn"})

_REASON_NO_LABELS = "no labels declared for a cited metric"
_REASON_NO_LABELS_OR_ORDER = "no labels or order declared for a cited metric"
_REASON_NO_UNIT = "no unit declared for a cited metric"
_REASON_NO_PERIOD = "no period declared for a cited metric"
_REASON_NO_PERIOD_COMPARISON = "no period declared for a cited metric in the comparison"
_REASON_PERIODS_SAME = "declared periods are not distinct"
_REASON_NO_SERIES = "cited metrics share no declared series"

_TIME_ARM_MESSAGE = "claim names a time outside the cited metric"

_NON_ZERO_GUARD_RE = re.compile(r"(?<!\w)non[ -]?$")


class CheckInput(VerifyInput):
    """The public input plus two optional flat maps beside ``labels``."""

    model_config = ConfigDict(extra="forbid")

    units: dict[str, str] | None = None
    periods: dict[str, str] | None = None

    @field_validator("units")
    @classmethod
    def _units_valid(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        if len(value) > MAX_TERMS:
            raise ValueError(f"units exceed MAX_TERMS ({MAX_TERMS})")
        for key, item in value.items():
            if not key.strip():
                raise ValueError("units key must not be blank")
            if item not in _UNIT_NAMES:
                raise ValueError(
                    "units value must be one of count, hours, minutes, seconds, days, percent"
                )
        return value

    @field_validator("periods")
    @classmethod
    def _periods_valid(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return value
        if len(value) > MAX_TERMS:
            raise ValueError(f"periods exceed MAX_TERMS ({MAX_TERMS})")
        for key, item in value.items():
            if not key.strip():
                raise ValueError("periods key must not be blank")
            if not item.strip():
                raise ValueError("periods value must not be blank")
            if len(item) > MAX_WORD_CHARS:
                raise ValueError(
                    f"periods value exceeds MAX_WORD_CHARS ({MAX_WORD_CHARS})"
                )
            if not any(char.isalpha() or char.isdigit() for char in item):
                raise ValueError("periods value must hold a letter or digit")
        return value


@dataclass(frozen=True)
class SkippedCheck:
    """One check that could not run for lack of metadata."""

    check: str
    reason: str


@dataclass(frozen=True)
class ClaimCoverage:
    """Which checks ran and which were skipped for one claim."""

    claim_id: str
    ran: tuple[str, ...]
    skipped: tuple[SkippedCheck, ...]


@dataclass(frozen=True)
class CheckReport:
    """Violations plus per-claim coverage and the hardened limits note."""

    violations: tuple[Violation, ...]
    limits: str
    coverage: tuple[ClaimCoverage, ...]
    complete: bool

    @property
    def passed(self) -> bool:
        """Input passes iff it has no violations."""
        return self.violations == ()

    def feedback(self) -> str:
        """One ``CODE claim_id: message`` line per violation."""
        return "\n".join(f"{v.code} {v.claim_id}: {v.message}" for v in self.violations)

    def human_first_line(self) -> str:
        """PASS/FAIL with a suffix when checks were skipped."""
        if self.passed and self.complete:
            return "PASS"
        if self.passed:
            return "PASS - checks skipped"
        if self.complete:
            return "FAIL"
        return "FAIL - checks skipped"

    def to_json(self) -> str:
        """Machine report: verdict, limits, violations, coverage, flag."""
        return json.dumps(
            {
                "passed": self.passed,
                "limits": self.limits,
                "violations": [
                    {
                        "code": item.code,
                        "claim_id": item.claim_id,
                        "message": item.message,
                    }
                    for item in self.violations
                ],
                "coverage": [
                    {
                        "claim_id": entry.claim_id,
                        "ran": list(entry.ran),
                        "skipped": [
                            {"check": skip.check, "reason": skip.reason}
                            for skip in entry.skipped
                        ],
                    }
                    for entry in self.coverage
                ],
                "complete": self.complete,
            }
        )


_FIELD_NAMES = frozenset(
    {
        "claims",
        "id",
        "text",
        "fact_ids",
        "metric_refs",
        "metric_id",
        "value",
        "facts",
        "metrics",
        "labels",
        "order",
        "deny_terms",
        "advice_words",
        "units",
        "periods",
    }
)

_TYPE_WORDS = {
    "missing": "missing",
    "extra_forbidden": "unknown key",
    "model_type": "must be an object",
    "model_attributes_type": "must be an object",
    "dict_type": "must be an object",
    "list_type": "must be a list",
    "string_type": "must be a string",
    "string_unicode": "must be valid text",
    "int_type": "must be a number",
    "float_type": "must be a number",
}

_VALUE_ERROR_PREFIX = "Value error, "


def _safe_message(exc: ValidationError) -> str:
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    lines: list[str] = []
    seen_lines: set[str] = set()
    for error in errors:
        error_type = str(error.get("type", "value_error"))
        parts = list(error.get("loc", ()))
        if error_type in ("int_type", "float_type") and parts:
            parts = parts[:-1]
        safe_loc = ".".join(
            str(part) if isinstance(part, int) or part in _FIELD_NAMES else "<key>"
            for part in parts
        )
        if error_type == "value_error":
            detail = str(error.get("msg", "")).removeprefix(_VALUE_ERROR_PREFIX)
        else:
            detail = _TYPE_WORDS.get(error_type, error_type)
        line = f"{safe_loc}: {detail}" if safe_loc else detail
        if line not in seen_lines:
            seen_lines.add(line)
            lines.append(line)
    text = "; ".join(lines[:5]) if lines else "invalid input"
    rest = len(lines) - 5
    if rest > 0:
        text += f"; and {rest} more"
    return text


def _validate_check(parsed: Any) -> CheckInput:
    if isinstance(parsed, CheckInput):
        parsed = parsed.model_dump()
    if not isinstance(parsed, dict):
        raise VerifyInputError("input must be a JSON object")
    try:
        return CheckInput.model_validate(parsed)
    except ValidationError as exc:
        raise VerifyInputError(_safe_message(exc)) from None


_JSON_TOKEN_RE = re.compile(r'"(?:[^"\\]++|\\.?+)*+(?:"|\Z)|[\[\]{}]', re.DOTALL)


def _check_depth(text: str) -> None:
    """Reject deep nesting before ``json.loads`` sees it.

    The same scan the old loader runs: only strings and brackets are
    walked, so brackets inside a string never count and a long string
    costs one match.
    """
    depth = 0
    for match in _JSON_TOKEN_RE.finditer(text):
        token = match.group(0)
        if token == "[" or token == "{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise VerifyInputError(
                    f"input nests deeper than MAX_JSON_DEPTH ({MAX_JSON_DEPTH})"
                )
        elif token == "]" or token == "}":
            depth = max(0, depth - 1)


def load_check_input(raw: str | bytes) -> CheckInput:
    """Parse one JSON input for the hardened checker."""
    if not isinstance(raw, (str, bytes)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise VerifyInputError("input must be text or bytes")
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
    except (ValueError, RecursionError) as exc:
        raise VerifyInputError("input is not valid UTF-8") from exc
    if len(data) > MAX_INPUT_BYTES:
        raise VerifyInputError(f"input exceeds MAX_INPUT_BYTES ({MAX_INPUT_BYTES})")
    try:
        text = data.decode("utf-8-sig")
    except (ValueError, RecursionError) as exc:
        raise VerifyInputError("input is not valid UTF-8") from exc
    _check_depth(text)

    def _no_dup(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, item in pairs:
            if key in obj:
                raise ValueError("duplicate key")
            obj[key] = item
        return obj

    def _no_const(name: str) -> Any:
        raise ValueError(f"non-finite constant: {name}")

    try:
        parsed = json.loads(text, parse_constant=_no_const, object_pairs_hook=_no_dup)
    except (ValueError, RecursionError) as exc:
        raise VerifyInputError("input is not valid JSON") from exc
    return _validate_check(parsed)


def _collapsed(text: str) -> str:
    return collapse_text(normalize_text(text))


def _folded(text: str) -> str:
    return normalize_text(text).casefold()


def _as_number(value: Decimal) -> int | float:
    """Whole differences stay ints; fractions become floats, fail-closed."""
    try:
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    except (OverflowError, ValueError):
        return math.inf


def _token_signed(norm: str, start: int) -> bool:
    if start < len(norm) and norm[start] == "-":
        return True
    return (
        start > 0
        and norm[start - 1] == "-"
        and (start < 2 or not norm[start - 2].isdigit())
    )


def _label_words_of(validated: CheckInput) -> dict[str, tuple[str, ...]]:
    return {
        metric_id: tuple(_collapsed(word) for word in words)
        for metric_id, words in (validated.labels or {}).items()
    }


def _series_index_of(validated: CheckInput) -> dict[str, tuple[int, int]]:
    index: dict[str, tuple[int, int]] = {}
    for series_no, series in enumerate(validated.order or []):
        for position, metric_id in enumerate(series):
            index[metric_id] = (series_no, position)
    return index


def _ordered_label_keys(validated: CheckInput) -> dict[str, list[str]]:
    """Caller label entries per metric, in the caller's order."""
    return {
        metric_id: [normalize_text(word).casefold() for word in words]
        for metric_id, words in (validated.labels or {}).items()
    }


def _stated_zero_code(
    lower: str,
    cited: Collection[tuple[str, int | float]],
    label_lists: Mapping[str, Collection[str]],
) -> str | None:
    for word in ("no", "zero"):
        pattern = r"(?<!\w)no(?!\w)" if word == "no" else r"(?<!\w)zero(?!\w)"
        for match in re.finditer(pattern, lower):
            if word == "zero" and _NON_ZERO_GUARD_RE.search(lower[: match.start()]):
                continue
            rest = lower[match.end() :].lstrip()
            for metric_id, _value in cited:
                for label in label_lists.get(metric_id, ()):
                    if not label:
                        continue
                    if re.match(re.escape(label) + r"(?!\w)", rest) is None:
                        continue
                    values = [value for mid, value in cited if mid == metric_id]
                    if values:
                        if any(value == 0 for value in values):
                            return None
                        return "L1B_NUMBER_WITHOUT_METRIC_REF"
    return "L1B_NEGATED_CLAIM"


def _negation_code(
    text: str,
    fact_ids: Collection[str],
    refs: Collection[tuple[str, int | float]],
    label_lists: Mapping[str, Collection[str]],
) -> str | None:
    lower = _folded(text)
    known_ids = set(fact_ids) | {metric_id for metric_id, _value in refs}
    if not has_negator(lower, known_ids):
        return None
    if refs:
        return _stated_zero_code(lower, list(refs), label_lists)
    words = set(re.findall(r"[a-z0-9]+", lower))
    if words & (UP_WORDS | DOWN_WORDS | SAME_WORDS) or counted_periods(lower):
        return "L1B_NEGATED_CLAIM"
    return None


def _quantity_code(
    text: str,
    fact_ids: Collection[str],
    refs: Collection[tuple[str, int | float]],
    label_words: Collection[str],
    period_phrases: Collection[str],
    units: Mapping[str, str],
    label_tokens: Collection[str],
) -> str | None:
    # No names are read from cited facts: a number-like or quantity-like
    # word inside a name that a cited fact carries is not skipped, which
    # can only make the check stricter.
    known_names: Collection[str] = ()
    known_ids = set(fact_ids) | {metric_id for metric_id, _value in refs}
    tokens = extract_number_tokens(text, known_ids, known_names)
    norm = normalize_text(text)
    backed_fifty = any(
        float(token.value) == 50
        and any(
            token_backed_by(
                ref_value,
                token.places,
                abs(token.value),
                signed=_token_signed(norm, token.start),
                section_type="working",
            )
            for _mid, ref_value in refs
        )
        for token in tokens
    )
    cited_labels = set(label_words) | {_collapsed(phrase) for phrase in period_phrases}
    cited_tokens = set(label_tokens)
    for phrase in period_phrases:
        cited_tokens.update(re.findall(r"[a-z0-9]+", _folded(phrase)))
    hits = find_unverifiable_quantities(
        text,
        has_metric_refs=bool(refs),
        has_backed_fifty=backed_fifty,
        in_since_last=False,
        cites_hours_metric=any(units.get(mid) == "hours" for mid, _v in refs),
        known_names=known_names,
        cited_labels=cited_labels,
        known_ids=known_ids,
        cited_label_tokens=cited_tokens,
    )
    if hits:
        return "L1B_UNVERIFIABLE_QUANTITY"
    return None


_AFTER_NUMBER_RE = re.compile(r"\s*([a-zA-Z]+|%)")
_GLUED_LETTERS_RE = re.compile(r"[a-zA-Z]+")


def _word_after(norm: str, end: int) -> tuple[str, str]:
    """First word after a number token, plus the glued letters on it."""
    glued = ""
    rest = norm[end:]
    glued_match = _GLUED_LETTERS_RE.match(rest)
    if glued_match is not None:
        glued = glued_match.group(0).casefold()
    match = _AFTER_NUMBER_RE.match(rest)
    word = match.group(1).casefold() if match is not None else ""
    if word == "per" and match is not None:
        second = re.match(r"\s*cent(?!\w)", rest[match.end() :], re.IGNORECASE)
        if second is not None:
            word = "per cent"
    return word, glued


_GLUED_HOURS = frozenset({"h", "hr", "hrs"})
_GLUED_MINUTES = frozenset({"m", "min", "mins"})
_GLUED_SECONDS = frozenset({"s", "sec", "secs"})

_PERCENT_WORDS = ("percent", "pct", "per cent")


def _unit_conflicts(
    unit: str,
    norm: str,
    work: str,
    tokens: Collection[Any],
) -> bool:
    """Whether any number disagrees with one declared unit.

    Tokens, the normalised copy and its fold are built once per claim by
    the caller. Each glued form maps to its family: h, hr and hrs are
    hours; m, min and mins are minutes; s, sec and secs are seconds.
    """
    if unit == "hours":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if glued in _GLUED_HOURS:
                continue
            if word in MAGNITUDE_WORDS or glued in GLUED_MAGNITUDE_LETTERS:
                return True
            if token.raw.endswith("%") or word in _PERCENT_WORDS:
                return True
            if word in DAYS_WORDS or word in CALENDAR_WORDS:
                return True
            if glued and glued not in HOURS_WORDS:
                return True
        return any(
            re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", work) is not None
            for word in (MINUTES_WORDS | SECONDS_WORDS)
        )
    if unit == "count":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if word in TIME_WORDS or word in MAGNITUDE_WORDS:
                return True
            if token.raw.endswith("%") or word in _PERCENT_WORDS:
                return True
            if glued and (
                glued in GLUED_TIME_LETTERS or glued in GLUED_MAGNITUDE_LETTERS
            ):
                return True
        return False
    if unit == "minutes":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if glued in _GLUED_MINUTES:
                continue
            if word in (HOURS_WORDS | DAYS_WORDS | CALENDAR_WORDS):
                return True
            if word in MAGNITUDE_WORDS or glued in GLUED_MAGNITUDE_LETTERS:
                return True
            if token.raw.endswith("%") or word in _PERCENT_WORDS:
                return True
            if glued and glued not in MINUTES_WORDS:
                return True
        return any(
            re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", work) is not None
            for word in SECONDS_WORDS
        )
    if unit == "seconds":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if glued in _GLUED_SECONDS:
                continue
            if word in (HOURS_WORDS | MINUTES_WORDS | DAYS_WORDS | CALENDAR_WORDS):
                return True
            if word in MAGNITUDE_WORDS or glued in GLUED_MAGNITUDE_LETTERS:
                return True
            if token.raw.endswith("%") or word in _PERCENT_WORDS:
                return True
            if glued and glued not in SECONDS_WORDS:
                return True
        return False
    if unit == "days":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if word in CALENDAR_WORDS:
                return True
            if word in MAGNITUDE_WORDS or glued in GLUED_MAGNITUDE_LETTERS:
                return True
            if token.raw.endswith("%") or word in _PERCENT_WORDS:
                return True
            if glued and glued not in DAYS_WORDS:
                return True
        return any(
            re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", work) is not None
            for word in (HOURS_WORDS | MINUTES_WORDS | SECONDS_WORDS)
        )
    if unit == "percent":
        for token in tokens:
            word, glued = _word_after(norm, token.end)
            if word in TIME_WORDS or word in MAGNITUDE_WORDS:
                return True
            if glued and (
                glued in GLUED_TIME_LETTERS or glued in GLUED_MAGNITUDE_LETTERS
            ):
                return True
        return False
    return False


def _unit_code(
    tokens: Collection[Any],
    norm: str,
    work: str,
    refs: Collection[tuple[str, int | float]],
    units: Mapping[str, str],
) -> str | None:
    """One L1B_UNIT_MISMATCH per claim against any conflicting cited unit."""
    seen_units: set[str] = set()
    for metric_id, _value in refs:
        unit = units.get(metric_id)
        if unit is not None and unit not in seen_units:
            seen_units.add(unit)
            if _unit_conflicts(unit, norm, work, tokens):
                return "L1B_UNIT_MISMATCH"
    return None


def _period_name_code(
    collapsed: str,
    refs: Collection[tuple[str, int | float]],
    declared: Mapping[str, str],
    series_index: Mapping[str, tuple[int, int]],
    by_series: Mapping[int, Collection[str]],
) -> str | None:
    """One L1B_PERIOD_WORD_MISSING per claim for a missing or stray period.

    The normalised period map and the series membership are built once
    per run by the caller.
    """
    for metric_id, _value in refs:
        phrase = declared.get(metric_id)
        if phrase is not None and not contains_token(collapsed, phrase):
            return "L1B_PERIOD_WORD_MISSING"
    cited_series = {
        series_index[metric_id][0]
        for metric_id, _value in refs
        if metric_id in series_index
    }
    if not cited_series or not declared:
        return None
    cited_ids = {mid for mid, _v in refs}
    for series_no in cited_series:
        for metric_id in by_series.get(series_no, ()):
            if metric_id in cited_ids:
                continue
            phrase = declared.get(metric_id)
            if phrase is not None and contains_token(collapsed, phrase):
                return "L1B_PERIOD_WORD_MISSING"
    return None


def _recompute_time_arm(
    text: str,
    label_words: Collection[str],
    period_phrases: Collection[str],
) -> tuple[str, ...]:
    collapsed = _collapsed(text)
    exempt = set(label_words) | {_collapsed(phrase) for phrase in period_phrases}
    return time_scope_hit(collapsed, exempt)


_BACKWARD_SEP_RE = (
    r"(?:was|were|at|of|with|had|saw|showed|reached|hit|totaled|totalled"
    r"|stood\s+at|came\s+to|[:=])"
)
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<!\w)(?:and|but|while|whereas|then|to|from|than|versus|vs"
    r"|after|before|between|across|over)(?!\w)"
)
_STATED_OF_RE = re.compile(
    r"(?<!\w)(?:drop|fall|rise|gain|loss|gap|difference|change|decline"
    r"|increase|decrease|delta|swing|shift|jump)\s+of\b"
)
_STATED_BY_RE = re.compile(r"(?<!\w)(?:by|net)\b")
_STATED_BARE_RE = re.compile(r"(?<!\w)(?:change|difference)\s+of\b")
_FRACTION_HINT_RE = re.compile(
    r"\d\s*[⁄/]\s*\d|(?<!\w)(?:half|halves|quarter|quarters|point)(?!\w)"
)


def _phrase_spans(
    work: str, phrases: Collection[str]
) -> dict[str, list[tuple[int, int]]]:
    spans: dict[str, list[tuple[int, int]]] = {}
    for phrase in phrases:
        parts = [re.escape(part) for part in phrase.split()]
        if not parts:
            continue
        pattern = r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)"
        spans[phrase] = [(m.start(), m.end()) for m in re.finditer(pattern, work)]
    return spans


def _value_period_eligible(
    refs: Collection[tuple[str, int | float]],
    periods: Mapping[str, str],
    series_index: Mapping[str, tuple[int, int]],
) -> tuple[bool, str | None]:
    items = list(refs)
    if not 2 <= len(items) <= 3:
        return False, None
    ids = [mid for mid, _v in items]
    if any(periods.get(mid) is None for mid in ids):
        return False, _REASON_NO_PERIOD_COMPARISON
    series: set[int] = set()
    for mid in ids:
        position = series_index.get(mid)
        if position is None:
            return False, _REASON_NO_SERIES
        series.add(position[0])
    if len(series) != 1:
        return False, _REASON_NO_SERIES
    folded = [_collapsed(str(periods[mid])) for mid in ids]
    if len(set(folded)) != len(folded):
        return False, _REASON_PERIODS_SAME
    return True, None


def _value_period_code(
    text: str,
    refs: Collection[tuple[str, int | float]],
    periods: Mapping[str, str],
    series_index: Mapping[str, tuple[int, int]],
    label_tokens: Collection[str],
) -> str | None:
    """One L1B_VALUE_PERIOD_MISMATCH per claim for a value beside the wrong period."""
    items = list(refs)
    period_of = {mid: _collapsed(str(periods[mid])) for mid, _v in items}
    cited_periods = set(period_of.values())
    norm = normalize_text(text)
    work = norm.casefold()
    known: Collection[str] = ()
    tokens = [tok for tok in extract_number_tokens(text, known, ())]
    values = [
        (tok.start, tok.start + len(tok.raw), tok.value, tok.places) for tok in tokens
    ]
    values.sort()
    by_start = {start: idx for idx, (start, _e, _v, _p) in enumerate(values)}

    def backed(period: str, pos: int) -> bool:
        _s, _e, val, places = values[pos]
        wanted = [ref for mid, ref in items if period_of.get(mid) == period]
        return any(
            token_backed_by(
                ref,
                places,
                abs(val),
                signed=_token_signed(norm, _s),
                section_type="working",
            )
            for ref in wanted
        )

    def positional_skip(value_end: int) -> bool:
        match = re.match(r"[ ]*(?:[A-Za-z]+[ ]+)?(?:and\b|,)[ ]*", work[value_end:])
        return match is not None and value_end + match.end() in by_start

    middle = set(label_tokens) | set(TIME_WORDS)
    phrase_list = sorted(cited_periods)
    spans = _phrase_spans(work, phrase_list)
    coordinated: set[tuple[str, int]] = set()
    for phrase in phrase_list:
        for start, end in spans.get(phrase, []):
            before = work[:start]
            after = work[end:]
            before_match = re.search(r"(?<!\w)(and|,)\s*$", before)
            if before_match is not None:
                cut = before[: before_match.start()].rstrip()
                if any(
                    cut.endswith(other)
                    and re.search(r"(?<!\w)" + re.escape(other) + r"$", cut) is not None
                    for other in phrase_list
                ):
                    coordinated.add((phrase, start))
                    continue
            after_match = re.match(r"\s*(and|,)\b", after)
            if after_match is not None:
                rest = after[after_match.end() :].lstrip()
                if any(
                    re.match(re.escape(other) + r"(?!\w)", rest) is not None
                    for other in phrase_list
                ):
                    coordinated.add((phrase, start))
    spans = {
        phrase: [(s, e) for s, e in items if (phrase, s) not in coordinated]
        for phrase, items in spans.items()
    }
    used: set[int] = set()
    for vi, (start, end, _val, _places) in enumerate(values):
        words: list[str] = []
        cursor = work[end:]
        for _ in range(3):
            match = re.match(r"\s*([a-z]+|[:=])", cursor)
            if match is None:
                break
            words.append(match.group(1))
            cursor = cursor[match.end() :]
            if words[-1] in cited_periods or words[-1] in (
                "in",
                "during",
                "for",
                "the",
            ):
                continue
            break
        idx = 0
        if idx < len(words) and words[idx] in middle:
            idx += 1
        prep = idx < len(words) and words[idx] in ("in", "during", "for")
        if prep:
            idx += 1
        if idx < len(words) and words[idx] == "the":
            idx += 1
        if idx >= len(words) or words[idx] not in cited_periods:
            continue
        if not prep and not (
            idx + 1 < len(words) and words[idx + 1] in ("period", "window")
        ):
            continue
        anchors = [s for s, _e in spans.get(words[idx], []) if s >= end]
        if not anchors:
            continue
        anchor = min(anchors)
        if re.search(r"[,;:]", work[end:anchor]):
            continue
        used.add(vi)
        if not backed(words[idx], vi):
            return "L1B_VALUE_PERIOD_MISMATCH"
    for vi, (start, _end, _val, _places) in enumerate(values):
        if vi in used:
            continue
        found: str | None = None
        found_end = -1
        for phrase in phrase_list:
            for _pstart, pend in spans.get(phrase, []):
                if pend > start:
                    continue
                gap = work[pend:start]
                if not re.fullmatch(
                    r"\s*(?:period\s+|window\s+)?(?:" + _BACKWARD_SEP_RE + r")?\s*", gap
                ):
                    continue
                if not gap.strip():
                    continue
                if found is None or pend > found_end:
                    found = phrase
                    found_end = pend
        if found is None or found not in cited_periods:
            continue
        if positional_skip(start):
            continue
        used.add(vi)
        if not backed(found, vi):
            return "L1B_VALUE_PERIOD_MISMATCH"
    for vi, (start, _end, _val, _places) in enumerate(values):
        if vi in used:
            continue
        comma = work.rfind(",", 0, start)
        if comma < 0 or not re.fullmatch(r"\s*", work[comma + 1 : start]):
            continue
        best: str | None = None
        best_end = -1
        for phrase in phrase_list:
            for _pstart, pend in spans.get(phrase, []):
                if pend <= comma and pend > best_end:
                    between = work[pend:comma]
                    if re.search(r"(?<!\w)(?:and|but)(?!\w)", between):
                        continue
                    if len(re.findall(r"[a-z]+", between)) > 4:
                        continue
                    best, best_end = phrase, pend
        if best is None or best not in cited_periods:
            continue
        if positional_skip(start):
            continue
        used.add(vi)
        if not backed(best, vi):
            return "L1B_VALUE_PERIOD_MISMATCH"
    seps = [(m.start(), m.end()) for m in re.finditer(r",|;|:", work)]
    for m in _CLAUSE_SPLIT_RE.finditer(work):
        seps.append((m.start(), m.end()))
    seps.sort()
    clauses: list[tuple[int, int]] = []
    pos = 0
    for sstart, send in seps:
        clauses.append((pos, sstart))
        pos = send
    clauses.append((pos, len(work)))
    named = 0
    for index, (cstart, cend) in enumerate(clauses):
        owned_periods = [
            phrase
            for phrase in phrase_list
            for pstart, pend in spans.get(phrase, [])
            if pstart >= cstart and pend <= cend
        ]
        owned_values = [
            vi
            for vi, (vstart, _e, _v, _p) in enumerate(values)
            if cstart <= vstart < cend
        ]
        named += len(owned_periods)
        if len(owned_periods) != 1 or len(owned_values) != 1:
            continue
        if _FRACTION_HINT_RE.search(work[cstart:cend]):
            continue
        if owned_periods[0] not in cited_periods:
            continue
        if named >= 2 and index + 1 < len(clauses):
            nxt_start, nxt_end = clauses[index + 1]
            nxt_periods = any(
                pstart >= nxt_start and pend <= nxt_end
                for phrase in phrase_list
                for pstart, pend in spans.get(phrase, [])
            )
            nxt_values = any(
                nxt_start <= vstart < nxt_end for vstart, _e, _v, _p in values
            )
            if nxt_values and not nxt_periods:
                continue
        if not backed(owned_periods[0], owned_values[0]):
            return "L1B_VALUE_PERIOD_MISMATCH"
    decimals = [Decimal(str(ref)) for _mid, ref in items]
    diffs = {
        abs(first - second)
        for ai, first in enumerate(decimals)
        for bi, second in enumerate(decimals)
        if ai != bi
    }
    for pattern in (_STATED_BY_RE, _STATED_OF_RE, _STATED_BARE_RE):
        for match in pattern.finditer(work):
            at = match.end()
            while at < len(work) and work[at] == " ":
                at += 1
            if at not in by_start:
                continue
            pos = by_start[at]
            _s, _e, val, places = values[pos]
            if not any(
                token_backed_by(
                    _as_number(diff),
                    places,
                    abs(val),
                    signed=_token_signed(norm, _s),
                    section_type="working",
                )
                for diff in diffs
            ):
                return "L1B_VALUE_PERIOD_MISMATCH"
    return None


_SHARED_CAPS = (
    MAX_CLAIM_TEXT_CHARS,
    MAX_TOTAL_CLAIM_TEXT_CHARS,
    MAX_CLAIMS,
    MAX_REFS_PER_CLAIM,
    MAX_LABEL_WORDS,
    MAX_SERIES_IDS,
    MAX_CLAIM_ID_CHARS,
    MAX_LABEL_CHECKS,
)
_BASE_ARMS = (text_check_codes, word_list_hit, direction_sides, ref_backs_token)

_MESSAGES = {
    "L1B_NEGATED_CLAIM": "state the value or direction positively",
    "L1B_UNVERIFIABLE_QUANTITY": "state the digits from the cited metric instead of a quantity word",
    "L1B_UNIT_MISMATCH": "use the unit of the cited metric",
    "L1B_PERIOD_WORD_MISSING": "claim does not name the period of the cited metric",
    "L1B_VALUE_PERIOD_MISMATCH": "write each cited value next to its own period phrase",
}

_NEW_ORDER = (
    "L1B_NUMBER_WITHOUT_METRIC_REF",
    "L1B_NEGATED_CLAIM",
    "L1B_UNVERIFIABLE_QUANTITY",
    "L1B_UNIT_MISMATCH",
    "L1B_PERIOD_WORD_MISSING",
    "L1B_VALUE_PERIOD_MISMATCH",
)


def _coverage_for(
    claim_id: str,
    refs: Collection[tuple[str, int | float]],
    labels: Mapping[str, Collection[str]] | None,
    units: Mapping[str, str] | None,
    periods: Mapping[str, str] | None,
    series_index: Mapping[str, tuple[int, int]],
    value_period_skip: str | None,
    value_period_ran: bool,
) -> ClaimCoverage:
    ran: list[str] = []
    skipped: list[SkippedCheck] = []
    if not refs:
        return ClaimCoverage(
            claim_id=claim_id, ran=("negation", "quantity forms"), skipped=()
        )
    labels = labels or {}
    units = units or {}
    periods = periods or {}
    if all(mid in labels for mid, _v in refs):
        ran.append("metric naming")
    else:
        skipped.append(SkippedCheck("metric naming", _REASON_NO_LABELS))
        if any(mid in labels for mid, _v in refs):
            ran.append("metric naming")
    if all(mid in labels or mid in series_index for mid, _v in refs):
        ran.append("direction")
    else:
        skipped.append(SkippedCheck("direction", _REASON_NO_LABELS_OR_ORDER))
        if any(mid in labels or mid in series_index for mid, _v in refs):
            ran.append("direction")
    ran.extend(("negation", "quantity forms"))
    if all(mid in units for mid, _v in refs):
        ran.append("unit")
    else:
        skipped.append(SkippedCheck("unit", _REASON_NO_UNIT))
        if any(mid in units for mid, _v in refs):
            ran.append("unit")
    if all(mid in periods for mid, _v in refs):
        ran.append("period name")
    else:
        skipped.append(SkippedCheck("period name", _REASON_NO_PERIOD))
        if any(mid in periods for mid, _v in refs):
            ran.append("period name")
    if len(list(refs)) >= 2:
        if value_period_ran:
            ran.append("value-period binding")
        elif value_period_skip is not None:
            skipped.append(SkippedCheck("value-period binding", value_period_skip))
    return ClaimCoverage(claim_id=claim_id, ran=tuple(ran), skipped=tuple(skipped))


def check_claims(data: CheckInput | dict[str, Any] | str | bytes) -> CheckReport:
    """Check agent output with the hardened arms; bad input raises."""
    if not isinstance(data, (CheckInput, VerifyInput, dict, str, bytes)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise VerifyInputError("input must be a JSON object")
    if isinstance(data, (str, bytes)):
        validated = load_check_input(data)
    elif isinstance(data, CheckInput):
        validated = data
    elif isinstance(data, VerifyInput):
        validated = _validate_check(data.model_dump())
    else:
        validated = _validate_check(data)
    base_input = validated.model_dump(exclude={"units", "periods"})
    base: Report = verify_claims(base_input)
    label_words = _label_words_of(validated)
    series_index = _series_index_of(validated)
    units = dict(validated.units or {})
    periods = dict(validated.periods or {})
    declared_periods = {mid: _collapsed(phrase) for mid, phrase in periods.items()}
    by_series: dict[int, list[str]] = {}
    for metric_id, (series_no, _pos) in series_index.items():
        by_series.setdefault(series_no, []).append(metric_id)
    ordered_labels = _ordered_label_keys(validated)
    base_by_claim: dict[str, list[Violation]] = {}
    for item in base.violations:
        base_by_claim.setdefault(item.claim_id, []).append(item)
    violations: list[Violation] = []
    seen: set[tuple[str, str]] = set()

    def _add(code: str, claim_id: str, message: str) -> None:
        if (code, claim_id) not in seen:
            seen.add((code, claim_id))
            violations.append(Violation(code=code, claim_id=claim_id, message=message))

    coverages: list[ClaimCoverage] = []
    for claim in validated.claims:
        refs = [(ref.metric_id, ref.value) for ref in claim.metric_refs]
        cited_ids = [mid for mid, _v in refs]
        if validated.periods:
            for item in base_by_claim.get(claim.id, ()):
                if (
                    item.code == "L1B_METRIC_LABEL_MISSING"
                    and item.message == _TIME_ARM_MESSAGE
                    and any(mid in periods for mid in cited_ids)
                ):
                    leftover = _recompute_time_arm(
                        claim.text,
                        [
                            word
                            for mid in cited_ids
                            for word in label_words.get(mid, ())
                        ],
                        [periods[mid] for mid in cited_ids if mid in periods],
                    )
                    if not leftover:
                        seen.add((item.code, item.claim_id))
        for item in base_by_claim.get(claim.id, ()):
            if (item.code, item.claim_id) not in seen:
                _add(item.code, item.claim_id, item.message)
        label_tokens = {
            token
            for mid in cited_ids
            for word in label_words.get(mid, ())
            for token in re.findall(r"[a-z0-9]+", word)
        }
        for mid in cited_ids:
            if mid in periods:
                label_tokens.update(re.findall(r"[a-z0-9]+", _folded(periods[mid])))
        norm = normalize_text(claim.text)
        work = norm.casefold()
        claim_tokens = extract_number_tokens(claim.text, (), ())
        new_codes: list[str] = []
        neg = _negation_code(claim.text, list(claim.fact_ids), refs, ordered_labels)
        if neg is not None:
            new_codes.append(neg)
        qty = _quantity_code(
            claim.text,
            list(claim.fact_ids),
            refs,
            [word for mid in cited_ids for word in label_words.get(mid, ())],
            [periods[mid] for mid in cited_ids if mid in periods],
            units,
            label_tokens,
        )
        if qty is not None:
            new_codes.append(qty)
        if refs:
            unit_hit = _unit_code(claim_tokens, norm, work, refs, units)
            if unit_hit is not None:
                new_codes.append(unit_hit)
            if any(mid in periods for mid in cited_ids):
                collapsed = _collapsed(claim.text)
                period_hit = _period_name_code(
                    collapsed, refs, declared_periods, series_index, by_series
                )
                if period_hit is not None:
                    new_codes.append(period_hit)
        value_skip: str | None = None
        value_ran = False
        if 2 <= len(refs) <= 3:
            eligible, reason = _value_period_eligible(refs, periods, series_index)
            if eligible:
                value_ran = True
                hit = _value_period_code(
                    claim.text, refs, periods, series_index, label_tokens
                )
                if hit is not None:
                    new_codes.append(hit)
            elif reason is not None:
                value_skip = reason
        ordered = sorted(new_codes, key=lambda code: _NEW_ORDER.index(code))
        for code in ordered:
            if code == "L1B_NUMBER_WITHOUT_METRIC_REF":
                _add(code, claim.id, "number token has no backing metric ref")
            else:
                _add(code, claim.id, _MESSAGES[code])
        coverages.append(
            _coverage_for(
                claim.id,
                refs,
                validated.labels,
                units,
                periods,
                series_index,
                value_skip,
                value_ran,
            )
        )
    complete = all(not entry.skipped for entry in coverages)
    return CheckReport(
        violations=tuple(violations),
        limits=HARDENED_LIMITS_NOTE,
        coverage=tuple(coverages),
        complete=complete,
    )


def _safe_claim_id(claim_id: str) -> str:
    if claim_id.isprintable():
        return claim_id
    return claim_id.encode("unicode-escape").decode("ascii")


def format_check_report(report: CheckReport) -> str:
    """Human report: verdict line, limits note, findings, then gaps."""
    lines = [report.human_first_line(), report.limits]
    lines.extend(
        f"{v.code} {_safe_claim_id(v.claim_id)}: {v.message}" for v in report.violations
    )
    for entry in report.coverage:
        for skip in entry.skipped:
            lines.append(
                f"NOT CHECKED {_safe_claim_id(entry.claim_id)}: {skip.check} - {skip.reason}"
            )
    return "\n".join(lines)


def page_render_hardened(raw: str) -> str:
    """Run the hardened checker for the browser page; never raises, never echoes."""
    try:
        report = check_claims(raw)
    except VerifyInputError as exc:
        return json.dumps({"exit_code": 2, "text": str(exc)})
    except Exception:  # noqa: BLE001 - the page shows a fixed message instead
        return json.dumps({"exit_code": 2, "text": "could not check that input"})
    return json.dumps(
        {
            "exit_code": 0 if report.passed else 1,
            "text": format_check_report(report),
        }
    )
