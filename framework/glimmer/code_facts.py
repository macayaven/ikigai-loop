"""Code facts: the largest change per metric family (Ticket 9b).

Pure and deterministic: no model, no clock, no env, no I/O. Same
``winners``/``rollup`` in, byte-identical code facts out.
"""

from __future__ import annotations

import decimal
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, cast

from framework.briefing.labels import metric_label_binding
from framework.briefing.numbers import extract_number_tokens
from framework.glimmer.checks import highest_tier
from framework.glimmer.metrics import PERIOD_NAMES, is_opened_pr, period_bounds
from framework.schemas.base import Tier
from framework.schemas.events import Event

HOURS_FLOOR = 0.5  # hours; see the ticket plan D4
COUNT_FLOOR = 1.0
SCREEN_SKIPPED_CATEGORIES = frozenset({"other", "system"})
SCREEN_DISPLAY_NAMES = {"ai": "AI"}

Family = Literal["screen_hours", "pushes", "prs", "tag_hours", "cancelled"]

_PAIRS: tuple[tuple[str, str], ...] = (
    (PERIOD_NAMES[0], PERIOD_NAMES[1]),
    (PERIOD_NAMES[1], PERIOD_NAMES[2]),
)

_PERIOD_WORD_RE = re.compile(r"\b(earlier|prior|last)\b")


@dataclass(frozen=True)
class CodeFact:
    family: Family
    member: str  # screen category or tag verbatim; "" for pushes/prs
    from_period: str  # "earlier" | "prior"
    to_period: str  # "prior" | "last"; always the next period after from_period
    from_value: float
    to_value: float
    statement: str
    evidence: tuple[str, ...]  # real winning event ids, 1..8, most recent first
    tier: Tier
    metric_ids: tuple[str, str]  # (period.<from>.<rest>, period.<to>.<rest>)


def format_metric_value(value: float) -> str:
    """Round half-up to 2 places, then strip trailing zeros."""
    quantised = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(quantised, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _rest(family: Family, member: str) -> str:
    if family == "pushes":
        return "pushes"
    if family == "prs":
        return "prs"
    if family == "screen_hours":
        return f"screen_hours.{member}"
    if family == "tag_hours":
        return f"tag_hours.{member}"
    return f"cancelled.{member}"


def _direction(from_value: float, to_value: float) -> str:
    return "rose" if to_value > from_value else "fell"


def _statement(
    family: Family,
    member: str,
    direction: str,
    text_from: str,
    period_from: str,
    text_to: str,
    period_to: str,
) -> str:
    if family == "screen_hours":
        display = SCREEN_DISPLAY_NAMES.get(member, member)
        return (
            f"{display} screen hours {direction} from {text_from}"
            f" in {period_from} to {text_to} in {period_to}."
        )
    if family == "pushes":
        return (
            f"Pushes {direction} from {text_from}"
            f" in {period_from} to {text_to} in {period_to}."
        )
    if family == "prs":
        return (
            f"Pull requests {direction} from {text_from}"
            f" in {period_from} to {text_to} in {period_to}."
        )
    if family == "tag_hours":
        return (
            f"{member} calendar hours {direction} from {text_from}"
            f" in {period_from} to {text_to} in {period_to}."
        )
    return (
        f"Cancelled {member} blocks {direction} from {text_from}"
        f" in {period_from} to {text_to} in {period_to}."
    )


def _members(family: Family, rollup: dict[str, dict[str, Any]]) -> list[str]:
    if family == "screen_hours":
        found: set[str] = set()
        for name in PERIOD_NAMES:
            found.update(rollup[name]["screen_hours"].keys())
        found -= SCREEN_SKIPPED_CATEGORIES
        return sorted(found)
    if family == "pushes" or family == "prs":
        return [""]
    key = (
        "calendar_hours_by_tag" if family == "tag_hours" else "cancelled_blocks_by_tag"
    )
    found = set()
    for name in PERIOD_NAMES:
        found.update(rollup[name][key].keys())
    return sorted(found)


def _value(
    family: Family, member: str, period: str, rollup: dict[str, dict[str, Any]]
) -> float:
    if family == "screen_hours":
        return float(rollup[period]["screen_hours"].get(member, 0.0))
    if family == "pushes":
        return float(rollup[period]["pushes"])
    if family == "prs":
        return float(rollup[period]["prs"])
    if family == "tag_hours":
        return float(rollup[period]["calendar_hours_by_tag"].get(member, 0.0))
    return float(rollup[period]["cancelled_blocks_by_tag"].get(member, 0))


def _floor(family: Family) -> float:
    if family == "screen_hours" or family == "tag_hours":
        return HOURS_FLOOR
    return COUNT_FLOOR


def _in_period(moment: datetime, start: datetime, end: datetime) -> bool:
    return start <= moment < end


def _overlap_hours(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    low, high = max(start, lo), min(end, hi)
    return max(0.0, (high - low).total_seconds() / 3600.0)


def _pool(
    family: Family,
    member: str,
    period: str,
    winners: Sequence[Event],
    spans: dict[str, tuple[datetime, datetime]],
) -> list[Event]:
    start, end = spans[period]
    rows: list[Event] = []
    for event in winners:
        data: Any = event.data
        if family == "screen_hours":
            if (
                event.type == "screen.hour"
                and _in_period(event.time, start, end)
                and float(data.minutes_by_category.get(member, 0)) > 0
            ):
                rows.append(event)
        elif family == "pushes":
            if event.type == "github.push" and _in_period(event.time, start, end):
                rows.append(event)
        elif family == "prs":
            if (
                event.type == "github.pr"
                and is_opened_pr(event)
                and _in_period(event.time, start, end)
            ):
                rows.append(event)
        elif family == "tag_hours":
            if (
                event.type.startswith("calendar.event.")
                and event.type != "calendar.event.cancelled"
                and member in data.tags
                and _overlap_hours(data.start, data.end, start, end) > 0
            ):
                rows.append(event)
        elif (
            event.type == "calendar.event.cancelled"
            and member in data.tags
            and _in_period(event.time, start, end)
        ):
            rows.append(event)
    return rows


def _select_evidence(
    pool_from: Sequence[Event], pool_to: Sequence[Event]
) -> tuple[str, ...]:
    """Reserve each period's most recent row, fill to 8, order newest first."""
    chosen: dict[str, Event] = {}
    for pool in (pool_from, pool_to):
        if pool:
            best = max(pool, key=lambda e: (e.time, e.id))
            chosen[best.id] = best
    combined = sorted(
        {e.id: e for e in (*pool_from, *pool_to)}.values(),
        key=lambda e: (e.time, e.id),
        reverse=True,
    )
    for event in combined:
        if len(chosen) >= 8:
            break
        chosen.setdefault(event.id, event)
    ordered = sorted(chosen.values(), key=lambda e: (e.time, e.id), reverse=True)
    return tuple(e.id for e in ordered)


def code_facts(
    as_of: datetime,
    winners: Sequence[Event],
    rollup: dict[str, dict[str, Any]],
) -> tuple[CodeFact, ...]:
    """Largest absolute change per family between consecutive periods."""
    bounds = period_bounds(as_of)
    spans = {name: (start, end) for name, start, end in bounds}
    by_id = {e.id: e for e in winners}
    facts: list[CodeFact] = []
    for family in ("screen_hours", "pushes", "prs", "tag_hours", "cancelled"):
        floor = _floor(family)
        ranked: list[tuple[float, int, str, str, str, float, float]] = []
        for member in _members(family, rollup):
            for rank, (period_from, period_to) in enumerate(_PAIRS):
                from_value = _value(family, member, period_from, rollup)
                to_value = _value(family, member, period_to, rollup)
                change = round(abs(to_value - from_value), 6)
                if change >= floor:
                    ranked.append(
                        (
                            change,
                            rank,
                            member,
                            period_from,
                            period_to,
                            from_value,
                            to_value,
                        )
                    )
        if not ranked:
            continue
        ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
        _, _, member, period_from, period_to, from_value, to_value = ranked[0]
        pool_from = _pool(family, member, period_from, winners, spans)
        pool_to = _pool(family, member, period_to, winners, spans)
        evidence = _select_evidence(pool_from, pool_to)
        rows = [by_id[eid] for eid in evidence]
        rest = _rest(family, member)
        statement = _statement(
            family,
            member,
            _direction(from_value, to_value),
            format_metric_value(from_value),
            period_from,
            format_metric_value(to_value),
            period_to,
        )
        facts.append(
            CodeFact(
                family=family,
                member=member,
                from_period=period_from,
                to_period=period_to,
                from_value=from_value,
                to_value=to_value,
                statement=statement,
                evidence=evidence,
                tier=cast(Tier, highest_tier(rows)),
                metric_ids=(
                    f"period.{period_from}.{rest}",
                    f"period.{period_to}.{rest}",
                ),
            )
        )
    return tuple(facts)


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


def _value_backed(value: float, places: int, token_abs: Decimal) -> bool:
    try:
        quantum = Decimal(1).scaleb(-places)
        rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except decimal.InvalidOperation:
        return False
    return abs(rounded) == token_abs


def _matches(statement: str, evidence_ids: Sequence[str], fact: CodeFact) -> bool:
    collapsed = _collapse(statement)
    bindings = [metric_label_binding(mid) for mid in fact.metric_ids]
    if any(binding is None for binding in bindings):
        return False
    first = bindings[0]
    if first is None:
        return False
    labels = first.labels
    if not any(_contains_token(collapsed, _collapse(label)) for label in labels):
        return False
    if fact.family == "cancelled":
        if "cancel" not in collapsed:
            return False
    elif "cancel" in collapsed:
        return False
    named = set(_PERIOD_WORD_RE.findall(collapsed))
    wanted = {fact.from_period, fact.to_period}
    if not named <= wanted:
        return False
    tokens = extract_number_tokens(statement, known_ids=set(evidence_ids))
    change = abs(fact.to_value - fact.from_value)
    if named == wanted and len(tokens) == 1:
        only = tokens[0]
        if _value_backed(change, only.places, abs(only.value)):
            return True
    count = len(tokens)
    for i in range(count):
        for j in range(count):
            if i == j:
                continue
            first, second = tokens[i], tokens[j]
            if not (
                _value_backed(fact.from_value, first.places, abs(first.value))
                and _value_backed(fact.to_value, second.places, abs(second.value))
            ):
                continue
            if all(
                k == i
                or k == j
                or _value_backed(change, tokens[k].places, abs(tokens[k].value))
                for k in range(count)
            ):
                return True
    return False


def is_duplicate_of_code(
    statement: str,
    evidence_ids: Sequence[str],
    code_facts: Sequence[CodeFact],
) -> CodeFact | None:
    """First code fact the statement repeats, or None."""
    for fact in code_facts:
        if _matches(statement, evidence_ids, fact):
            return fact
    return None
