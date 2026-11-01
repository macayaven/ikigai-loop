"""Ticket 17a: public claim checker over plain JSON.

``verify_claims`` reconciles an agent's stated numbers and cited sources
against caller-supplied reference data. It shares its matching path with
the briefing gate (``text_check_codes``, ``extract_number_tokens`` and the
appended wrappers in ``framework.briefing.gate``) and adds nothing else.
No network, no model, no store, no profile: the caller brings the facts
and metrics from their own system of record.
"""

from __future__ import annotations

import itertools
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from framework.briefing.gate import (
    collapse_text,
    contains_token,
    direction_sides,
    ref_backs_token,
    text_check_codes,
    word_list_hit,
)
from framework.briefing.numbers import extract_number_tokens

LIMITS_NOTE = (
    "This check covers parseable numbers, cited sources, labels and direction. "
    "It does not check that a sentence is true. "
    "Without labels it cannot tell which metric a number belongs to, "
    "and a cited fact is only checked to exist."
)

MAX_CLAIM_TEXT_CHARS = 2_000
MAX_TOTAL_CLAIM_TEXT_CHARS = 100_000
MAX_INPUT_BYTES = 10_000_000
MAX_CLAIMS = 5_000
MAX_REFS_PER_CLAIM = 100
MAX_TERMS = 1_000
MAX_LABEL_WORDS = 10
MAX_SERIES_IDS = 366
MAX_JSON_DEPTH = 64
MAX_WORD_CHARS = 100
MAX_CLAIM_ID_CHARS = 200

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
    }
)


class VerifyInputError(ValueError):
    """Bad checker input; safe to print and to send back to a model."""


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("string must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_non_blank)]
StrictNumber = Annotated[StrictInt | StrictFloat, Field(union_mode="left_to_right")]


def _finite_number(value: StrictNumber) -> StrictNumber:
    if isinstance(value, bool):
        raise TypeError("metric value must be a number")
    if isinstance(value, int) and value.bit_length() > 14_000:
        raise ValueError("metric value is too large")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metric value must be finite")
    return value


class MetricRefInput(BaseModel):
    """One cited metric value on a claim."""

    model_config = ConfigDict(extra="forbid")

    metric_id: NonBlankStr
    value: StrictNumber

    @field_validator("value")
    @classmethod
    def _finite_value(cls, value: float) -> int | float:
        return _finite_number(value)


class ClaimInput(BaseModel):
    """One statement plus its evidence."""

    model_config = ConfigDict(extra="forbid")

    id: NonBlankStr
    text: NonBlankStr
    fact_ids: Annotated[list[NonBlankStr], Field(default_factory=list, fail_fast=True)]
    metric_refs: Annotated[
        list[MetricRefInput], Field(default_factory=list, fail_fast=True)
    ]

    @field_validator("id")
    @classmethod
    def _id_capped(cls, value: str) -> str:
        if len(value) > MAX_CLAIM_ID_CHARS:
            raise ValueError(
                f"claim id exceeds MAX_CLAIM_ID_CHARS ({MAX_CLAIM_ID_CHARS})"
            )
        return value

    @field_validator("text")
    @classmethod
    def _text_capped(cls, value: str) -> str:
        if len(value) > MAX_CLAIM_TEXT_CHARS:
            raise ValueError(
                f"claim text exceeds MAX_CLAIM_TEXT_CHARS ({MAX_CLAIM_TEXT_CHARS})"
            )
        return value

    @field_validator("metric_refs")
    @classmethod
    def _refs_capped(cls, value: list[MetricRefInput]) -> list[MetricRefInput]:
        if len(value) > MAX_REFS_PER_CLAIM:
            raise ValueError(
                f"claim refs exceed MAX_REFS_PER_CLAIM ({MAX_REFS_PER_CLAIM})"
            )
        return value


class VerifyInput(BaseModel):
    """The whole public input: agent output plus reference data."""

    model_config = ConfigDict(extra="forbid")

    claims: Annotated[list[ClaimInput], Field(fail_fast=True)]
    facts: dict[str, str]
    metrics: dict[str, StrictNumber]
    labels: dict[str, Annotated[list[str], Field(fail_fast=True)]] | None = None
    order: Annotated[
        list[Annotated[list[NonBlankStr], Field(fail_fast=True)]] | None,
        Field(default=None, fail_fast=True),
    ] = None
    deny_terms: Annotated[
        list[NonBlankStr] | None, Field(default=None, fail_fast=True)
    ] = None
    advice_words: Annotated[
        list[NonBlankStr] | None, Field(default=None, fail_fast=True)
    ] = None

    @field_validator("facts")
    @classmethod
    def _facts_non_blank(cls, value: dict[str, str]) -> dict[str, str]:
        for key, item in value.items():
            if not key.strip():
                raise ValueError("fact id must not be blank")
            if not item.strip():
                raise ValueError("fact value must not be blank")
        return value

    @field_validator("metrics")
    @classmethod
    def _metrics_valid(cls, value: dict[str, int | float]) -> dict[str, int | float]:
        for key, item in value.items():
            if not key.strip():
                raise ValueError("metric id must not be blank")
            _finite_number(item)
        return value

    @field_validator("labels")
    @classmethod
    def _labels_valid(
        cls, value: dict[str, list[str]] | None
    ) -> dict[str, list[str]] | None:
        if value is None:
            return value
        for key, words in value.items():
            if not key.strip():
                raise ValueError("label id must not be blank")
            if not words:
                raise ValueError("label word list must not be empty")
            if len(words) > MAX_LABEL_WORDS:
                raise ValueError(
                    f"label word list exceeds MAX_LABEL_WORDS ({MAX_LABEL_WORDS})"
                )
            for word in words:
                if not word.strip():
                    raise ValueError("label word must not be blank")
                if len(word) > MAX_WORD_CHARS:
                    raise ValueError(
                        f"label word exceeds MAX_WORD_CHARS ({MAX_WORD_CHARS})"
                    )
        return value

    @field_validator("deny_terms", "advice_words")
    @classmethod
    def _terms_capped(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) > MAX_TERMS:
            raise ValueError(f"term list exceeds MAX_TERMS ({MAX_TERMS})")
        if value is not None:
            for term in value:
                if len(term) > MAX_WORD_CHARS:
                    raise ValueError(f"term exceeds MAX_WORD_CHARS ({MAX_WORD_CHARS})")
        return value

    @model_validator(mode="after")
    def _claims_capped(self) -> VerifyInput:
        if not self.claims:
            raise ValueError("claims must not be empty")
        if len(self.claims) > MAX_CLAIMS:
            raise ValueError(f"claims exceed MAX_CLAIMS ({MAX_CLAIMS})")
        seen: set[str] = set()
        for claim in self.claims:
            if claim.id in seen:
                raise ValueError("claim id appears more than once")
            seen.add(claim.id)
        total = sum(len(claim.text) for claim in self.claims)
        if total > MAX_TOTAL_CLAIM_TEXT_CHARS:
            raise ValueError(
                "total claim text exceeds "
                f"MAX_TOTAL_CLAIM_TEXT_CHARS ({MAX_TOTAL_CLAIM_TEXT_CHARS})"
            )
        if self.order is not None:
            seen_order: set[str] = set()
            for series in self.order:
                if len(series) < 2:
                    raise ValueError("order series must hold at least 2 metric ids")
                if len(series) > MAX_SERIES_IDS:
                    raise ValueError(
                        f"order series exceeds MAX_SERIES_IDS ({MAX_SERIES_IDS})"
                    )
                for metric_id in series:
                    if metric_id in seen_order:
                        raise ValueError("order metric id appears more than once")
                    seen_order.add(metric_id)
        return self


@dataclass(frozen=True)
class Violation:
    """One finding; ``message`` never echoes matched content."""

    code: str
    claim_id: str
    message: str


@dataclass(frozen=True)
class Report:
    """Violations plus the pinned limits note."""

    violations: tuple[Violation, ...]
    limits: str

    @property
    def passed(self) -> bool:
        """Input passes iff it has no violations."""
        return self.violations == ()

    def feedback(self) -> str:
        """One ``CODE claim_id: message`` line per violation."""
        return "\n".join(f"{v.code} {v.claim_id}: {v.message}" for v in self.violations)


_TEXT_MESSAGES = {
    "L1_SECRET": "secret-like token",
    "L1_PII": "contact detail",
    "L1_PRIVATE_TERM": "private term",
    "L1_ADVICE": "advice-like wording",
}


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


def _validate(parsed: Any) -> VerifyInput:
    if isinstance(parsed, VerifyInput):
        parsed = parsed.model_dump()
    if not isinstance(parsed, dict):
        raise VerifyInputError("input must be a JSON object")
    try:
        return VerifyInput.model_validate(parsed)
    except ValidationError as exc:
        raise VerifyInputError(_safe_message(exc)) from None


_JSON_TOKEN_RE = re.compile(r'"(?:[^"\\]++|\\.?+)*+(?:"|\Z)|[\[\]{}]', re.DOTALL)


def _check_depth(text: str) -> None:
    """Reject deep nesting before ``json.loads`` sees it.

    Only strings and brackets are walked, so brackets inside a string
    never count and a long string costs one match. Past the cap the
    browser build dies in the JS stack before Python's recursion check
    fires, so fail here with a named limit instead. ``\\Z`` lets an
    unclosed string run to the end of the text, so every match consumes
    and the search never restarts at each escaped quote.
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


def load_input(raw: str | bytes) -> VerifyInput:
    """Parse one JSON input; every failure is a ``VerifyInputError``."""
    # Runtime callers bypass the annotation, so this guard stays.
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
    return _validate(parsed)


@dataclass(frozen=True)
class _ClaimContext:
    """Lookups built once per run, so a claim walks only its own series."""

    facts: Mapping[str, str]
    metrics: Mapping[str, int | float]
    label_words: dict[str, tuple[str, ...]]
    series_index: dict[str, tuple[int, int]]
    series_words: dict[int, tuple[str, ...]]
    deny_terms: tuple[str, ...]
    advice_words: tuple[str, ...] | None


def _check_claim(
    claim: ClaimInput,
    ctx: _ClaimContext,
    add: Any,
) -> None:
    facts = ctx.facts
    metrics = ctx.metrics
    label_words = ctx.label_words
    series_index = ctx.series_index
    series_words = ctx.series_words
    deny_terms = ctx.deny_terms
    advice_words = ctx.advice_words
    if not claim.fact_ids and not claim.metric_refs:
        add(
            "L1B_CLAIM_WITHOUT_EVIDENCE",
            claim.id,
            "claim has no fact or metric evidence",
        )
    for fact_id in claim.fact_ids:
        if fact_id not in facts:
            add("L1B_UNKNOWN_FACT", claim.id, "cited fact is unknown")
    for ref in claim.metric_refs:
        if ref.metric_id not in metrics:
            add(
                "L1B_UNKNOWN_METRIC",
                claim.id,
                "metric is absent from the snapshot",
            )
        elif Decimal(str(ref.value)) != Decimal(str(metrics[ref.metric_id])):
            add(
                "L1B_METRIC_VALUE_MISMATCH",
                claim.id,
                "metric value differs from the snapshot",
            )
    known_ids = set(claim.fact_ids) | {ref.metric_id for ref in claim.metric_refs}
    for token in extract_number_tokens(claim.text, known_ids):
        if not any(
            ref_backs_token(ref.value, token.places, abs(token.value))
            for ref in claim.metric_refs
        ):
            add(
                "L1B_NUMBER_WITHOUT_METRIC_REF",
                claim.id,
                "number token has no backing metric ref",
            )
    bound = [
        ref
        for ref in claim.metric_refs
        if ref.metric_id in label_words or ref.metric_id in series_index
    ]
    if bound:
        ids = [ref.metric_id for ref in bound]
        inside = (
            len(set(ids)) == len(ids)
            and all(metric_id in series_index for metric_id in ids)
            and len({series_index[metric_id][0] for metric_id in ids}) == 1
        )
        if len(bound) >= 2 and not inside:
            add(
                "L1B_TOO_MANY_METRICS",
                claim.id,
                "claim cites several metrics outside one declared series; "
                "split the claim or list them in order",
            )
        else:
            collapsed = collapse_text(claim.text)
            bound_words = {
                word for metric_id in ids for word in label_words.get(metric_id, ())
            }
            missing = any(not contains_token(collapsed, word) for word in bound_words)
            if missing:
                add(
                    "L1B_METRIC_LABEL_MISSING",
                    claim.id,
                    "claim does not name the cited metric",
                )
            else:
                home: int = series_index[ids[0]][0] if ids[0] in series_index else -1
                named_sibling = False
                # A cited member's words are all in bound_words, so a word
                # outside bound_words can only belong to an uncited member.
                for word in series_words.get(home, ()):
                    if (
                        word not in bound_words
                        and word in collapsed
                        and contains_token(collapsed, word)
                    ):
                        named_sibling = True
                        break
                if named_sibling:
                    add(
                        "L1B_METRIC_LABEL_MISSING",
                        claim.id,
                        "claim names another metric in its series without citing it",
                    )
            exclude_words = [
                word for ref in bound for word in label_words.get(ref.metric_id, ())
            ]
            sides = direction_sides(claim.text, exclude_words=exclude_words)
            if len(sides) > 1:
                add(
                    "L1B_DIRECTION_MISMATCH",
                    claim.id,
                    "direction words disagree with the cited values",
                )
            elif sides:
                side = next(iter(sides))
                if len(bound) == 1:
                    add(
                        "L1B_DIRECTION_MISMATCH",
                        claim.id,
                        "direction words disagree with the cited values",
                    )
                else:
                    ordered = sorted(
                        bound, key=lambda ref: series_index[ref.metric_id][1]
                    )
                    diffs = [
                        Decimal(str(later.value)) - Decimal(str(earlier.value))
                        for earlier, later in itertools.pairwise(ordered)
                    ]
                    agree = (
                        all(diff > 0 for diff in diffs)
                        if side == "up"
                        else all(diff < 0 for diff in diffs)
                    )
                    if not agree:
                        add(
                            "L1B_DIRECTION_MISMATCH",
                            claim.id,
                            "direction words disagree with the cited values",
                        )
    for code in text_check_codes(claim.text, private_terms=deny_terms):
        if code == "L1_ADVICE":
            continue
        add(code, claim.id, _TEXT_MESSAGES.get(code, "text check failed"))
    if advice_words and word_list_hit(claim.text, advice_words):
        add("L1_ADVICE", claim.id, _TEXT_MESSAGES["L1_ADVICE"])


def verify_claims(data: VerifyInput | dict[str, Any] | str | bytes) -> Report:
    """Check agent output against reference data; bad input raises."""
    # Runtime callers bypass the annotation, so this guard stays.
    if not isinstance(data, (VerifyInput, dict, str, bytes)):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise VerifyInputError("input must be a JSON object")
    if isinstance(data, (str, bytes)):
        validated = load_input(data)
    else:
        validated = _validate(data)
    violations: list[Violation] = []
    seen: set[tuple[str, str]] = set()

    def _add(code: str, claim_id: str, message: str) -> None:
        if (code, claim_id) not in seen:
            seen.add((code, claim_id))
            violations.append(Violation(code=code, claim_id=claim_id, message=message))

    label_words = {
        metric_id: tuple(collapse_text(word) for word in words)
        for metric_id, words in (validated.labels or {}).items()
    }
    series_index: dict[str, tuple[int, int]] = {}
    for series_no, series in enumerate(validated.order or []):
        for position, metric_id in enumerate(series):
            series_index[metric_id] = (series_no, position)
    grouped: dict[int, list[str]] = {}
    for series_no, series in enumerate(validated.order or []):
        for metric_id in series:
            for word in label_words.get(metric_id, ()):
                grouped.setdefault(series_no, []).append(word)
    ctx = _ClaimContext(
        facts=validated.facts,
        metrics=validated.metrics,
        label_words=label_words,
        series_index=series_index,
        series_words={
            key: tuple(dict.fromkeys(words)) for key, words in grouped.items()
        },
        deny_terms=tuple(
            dict.fromkeys(collapse_text(term) for term in validated.deny_terms or ())
        ),
        advice_words=tuple(
            dict.fromkeys(collapse_text(word) for word in validated.advice_words or ())
        )
        if validated.advice_words
        else None,
    )
    for claim in validated.claims:
        _check_claim(claim, ctx, _add)
    return Report(violations=tuple(violations), limits=LIMITS_NOTE)


def _safe_claim_id(claim_id: str) -> str:
    if claim_id.isprintable():
        return claim_id
    return claim_id.encode("unicode-escape").decode("ascii")


def format_report(report: Report) -> str:
    """Human report: PASS/FAIL, the limits note, then one line per finding."""
    lines = ["PASS" if report.passed else "FAIL", report.limits]
    lines.extend(
        f"{v.code} {_safe_claim_id(v.claim_id)}: {v.message}" for v in report.violations
    )
    return "\n".join(lines)


def page_render(raw: str) -> str:
    """Run the checker for the browser page; never raises, never echoes."""
    try:
        report = verify_claims(raw)
    except VerifyInputError as exc:
        return json.dumps({"exit_code": 2, "text": str(exc)})
    except Exception:  # noqa: BLE001 - the page shows a fixed message instead
        return json.dumps({"exit_code": 2, "text": "could not check that input"})
    return json.dumps(
        {
            "exit_code": 0 if report.passed else 1,
            "text": format_report(report),
        }
    )
