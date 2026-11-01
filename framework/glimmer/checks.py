"""Deterministic fact checks (Ticket 9). Pure."""

from __future__ import annotations

import decimal
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from framework.briefing.context import MetricSnapshot
from framework.briefing.numbers import NumberToken, extract_number_tokens
from framework.glimmer.labels import INTERNAL_ONLY_LABELS
from framework.glimmer.metrics import PERIOD_NAMES, period_bounds
from framework.schemas.events import Event

_ALIAS_RE = re.compile(r"\b[ef]\d+\b", re.IGNORECASE)
_TIER_ORDER = {"public": 0, "private": 1, "sensitive": 2}
_MODEL_SKIPPED_SCREEN = frozenset({"system"})
_PERIOD_WORD_RE = re.compile(r"(?<![\w-])(earlier|prior|last)(?![\w-])", re.IGNORECASE)
_SYSTEM_TOKEN_RE = re.compile(r"\bsystem\b")


def resolve_aliases(
    aliases: Sequence[str], alias_map: Mapping[str, str]
) -> tuple[str, ...] | None:
    resolved: list[str] = []
    for alias in aliases:
        real = alias_map.get(alias)
        if real is None:
            return None
        resolved.append(real)
    return tuple(dict.fromkeys(resolved))


def highest_tier(events: Sequence[Event]) -> str:
    return max((e.tier for e in events), key=lambda t: _TIER_ORDER[t], default="public")


def _collapse(text: str) -> str:
    return " ".join(text.split()).casefold()


def _words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.casefold())


def _backs(value: float, places: int, token_abs: Decimal) -> bool:
    try:
        quantum = Decimal(1).scaleb(-places)
        rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    except decimal.InvalidOperation:
        return False
    return abs(rounded) == token_abs


def _family_match(rest: str, event: Event) -> bool:
    data: Any = event.data
    if rest.startswith("screen_hours."):
        category = rest[len("screen_hours.") :]
        return event.type == "screen.hour" and category in data.minutes_by_category
    if rest == "pushes":
        return event.type == "github.push"
    if rest == "prs":
        return event.type == "github.pr"
    if rest.startswith("tag_hours."):
        tag = rest[len("tag_hours.") :]
        return (
            event.type.startswith("calendar.event.")
            and event.type != "calendar.event.cancelled"
            and tag in data.tags
        )
    if rest.startswith("cancelled."):
        tag = rest[len("cancelled.") :]
        return event.type == "calendar.event.cancelled" and tag in data.tags
    if rest == "calendar.busy_hours" or rest == "busy_hours":
        return event.type.startswith("calendar.event.") and (
            event.type != "calendar.event.cancelled"
        )
    if rest == "github.push.count":
        return event.type == "github.push"
    if rest == "github.pr.count":
        return event.type == "github.pr"
    if rest.startswith("feed.item.count"):
        if rest == "feed.item.count":
            return event.type == "feed.item"
        source = rest[len("feed.item.count.") :]
        return event.type == "feed.item" and data.source == source
    return False


def _period_of(moment: datetime, as_of: datetime) -> str | None:
    for name, start, end in period_bounds(as_of):
        if start <= moment < end:
            return name
    return None


def _tag_overlaps(span: tuple[datetime, datetime], rest: str, event: Event) -> bool:
    """True when a non-cancelled calendar row overlaps the period with hours.

    ``event.time`` is a calendar block's start, so start-in-period misses
    blocks that cross into the period; overlap matches the clipped rollup.
    """
    if not rest.startswith("tag_hours."):
        return False
    if not event.type.startswith("calendar.event."):
        return False
    if event.type == "calendar.event.cancelled":
        return False
    data: Any = event.data
    if rest[len("tag_hours.") :] not in data.tags:
        return False
    start, end = max(data.start, span[0]), min(data.end, span[1])
    return (end - start).total_seconds() > 0


def _cited_period_families(cited: Sequence[Event]) -> set[str]:
    """Period-key families the cited rows belong to, for the zero rule."""
    families: set[str] = set()
    for event in cited:
        data: Any = event.data
        if event.type == "screen.hour":
            for category in data.minutes_by_category:
                families.add(f"screen_hours.{category}")
        elif event.type == "github.push":
            families.add("pushes")
        elif event.type == "github.pr":
            families.add("prs")
        elif event.type == "calendar.event.cancelled":
            for tag in data.tags:
                families.add(f"cancelled.{tag}")
        elif event.type.startswith("calendar.event."):
            for tag in data.tags:
                families.add(f"tag_hours.{tag}")
    return families


def _zero_token_backed(snapshot: MetricSnapshot, cited: Sequence[Event]) -> bool:
    """A zero token needs only a cited family row in any period, since the
    empty period holds no row to cite: some period key for one cited family
    is absent or zero."""
    for family in _cited_period_families(cited):
        for name in PERIOD_NAMES:
            value = snapshot.values.get(f"period.{name}.{family}")
            if value is None or value == 0.0:
                return True
    return False


def event_touches_window(
    event: Event, window_start: datetime, window_end: datetime
) -> bool:
    """D4 selection rule: a combined winner enters the cycle iff it touches the window."""
    if event.type == "calendar.event.cancelled":
        return window_start <= event.time < window_end
    if event.type.startswith("calendar.event."):
        data: Any = event.data
        start, end = data.start, data.end
        if start == end:
            return window_start <= start < window_end
        return max(start, window_start) < min(end, window_end)
    return window_start <= event.time < window_end


def _period_mentions(masked: str) -> list[tuple[str, int, int]]:
    """Period words on the repo-masked statement, with offsets."""
    return [
        (match.group(0).casefold(), match.start(), match.end())
        for match in _PERIOD_WORD_RE.finditer(masked)
    ]


def _pair_periods(
    tokens: Sequence[NumberToken], mentions: Sequence[tuple[str, int, int]]
) -> list[str | None]:
    """Bind each number token to the period its statement names for it.

    By order when token and mention counts match; otherwise (a) the first
    mention after the token and before the next token, (b) the last mention
    before the token and after the previous token, (c) the statement's only
    named period. Unbound (None) when no rule fires.
    """
    if len(tokens) == len(mentions):
        return [name for name, _, _ in mentions]
    named = {name for name, _, _ in mentions}
    only = next(iter(named)) if len(named) == 1 else None
    paired: list[str | None] = []
    for index, token in enumerate(tokens):
        token_start = token.start
        token_end = token.start + len(token.raw)
        if index > 0:
            prev_end = tokens[index - 1].start + len(tokens[index - 1].raw)
        else:
            prev_end = 0
        next_start = tokens[index + 1].start if index + 1 < len(tokens) else None
        after = [
            mention
            for mention in mentions
            if mention[1] >= token_end
            and (next_start is None or mention[1] < next_start)
        ]
        if after:
            paired.append(after[0][0])
            continue
        before = [
            mention
            for mention in mentions
            if mention[2] <= token_start and mention[1] >= prev_end
        ]
        if before:
            paired.append(before[-1][0])
            continue
        paired.append(only)
    return paired


def _snapshot_backs(
    token_abs: Decimal,
    places: int,
    snapshot: MetricSnapshot,
    cited: Sequence[Event],
    as_of: datetime,
    paired: str | None,
    named: set[str],
) -> bool:
    period_only = paired is not None or bool(named)
    if not period_only:
        if token_abs == 0 and _zero_token_backed(snapshot, cited):
            return True
    elif token_abs == 0:
        if paired is not None:
            return any(
                snapshot.values.get(f"period.{paired}.{family}") in (None, 0.0)
                for family in _cited_period_families(cited)
            )
        return any(
            snapshot.values.get(f"period.{name}.{family}") in (None, 0.0)
            for name in named
            for family in _cited_period_families(cited)
        )
    spans = {name: (start, end) for name, start, end in period_bounds(as_of)}
    for key, value in snapshot.values.items():
        if not _backs(value, places, token_abs):
            continue
        if key.startswith("period."):
            parts = key.split(".", 2)
            if len(parts) < 3:
                continue
            period_name, rest = parts[1], parts[2]
            if paired is not None and period_name != paired:
                continue
            if paired is None and named and period_name not in named:
                continue
            span = spans.get(period_name)
            if span is None:
                continue
            if value == 0.0:
                if any(_family_match(rest, e) for e in cited):
                    return True
            elif rest.startswith("tag_hours."):
                if any(_tag_overlaps(span, rest, e) for e in cited):
                    return True
            elif any(
                _family_match(rest, e) and _period_of(e.time, as_of) == period_name
                for e in cited
            ):
                return True
        elif not period_only and any(_family_match(key, e) for e in cited):
            return True
    return False


def _cited_repo_names(cited: Sequence[Event]) -> list[str]:
    """Repo strings (and qualifying segments) of the cited ``github.*`` rows."""
    names: list[str] = []
    seen: set[str] = set()
    for event in cited:
        if not event.type.startswith("github."):
            continue
        data: Any = event.data
        repo: str = data.repo
        candidates = [repo, *repo.split("/")]
        for candidate in candidates:
            if not candidate:
                continue
            if candidate != repo and not (
                any(ch.isalpha() for ch in candidate)
                and any(ch in "-_." for ch in candidate)
            ):
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(candidate)
    names.sort(key=len, reverse=True)
    return names


def _mask_cited_repos(statement: str, cited: Sequence[Event]) -> str:
    """Blank cited repo names for the number check only."""
    masked = statement
    for name in _cited_repo_names(cited):
        pattern = re.compile(
            r"(?<![\w/.-])" + re.escape(name) + r"(?![\w/-]|\.\w)",
            re.IGNORECASE,
        )
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    return masked


def _leak_values(winners: Sequence[Event]) -> list[str]:
    values: list[str] = []
    for event in winners:
        if event.tier not in ("private", "sensitive"):
            continue
        data: Any = event.data
        if event.type.startswith("github."):
            values.append(data.repo)
        elif event.type == "feed.item":
            values.extend([data.title, data.url])
    return [v for v in values if len(_collapse(v)) >= 3]


def private_free_text_values(events: Sequence[Event]) -> tuple[str, ...]:
    """Free-text values the outbound scan must never carry (Ticket 11)."""
    return tuple(_leak_values(events))


def check_fact(
    statement: str,
    evidence_ids: Sequence[str],
    *,
    known_by_id: Mapping[str, Event],
    winning_ids: frozenset[str],
    winners: Sequence[Event],
    snapshot: MetricSnapshot,
    feed_titles: Sequence[str],
    as_of: datetime,
    window_start: datetime,
    open_families: frozenset[str] = frozenset(),
) -> str | None:
    """Return the first failing code, or None when the fact passes."""
    cited: list[Event] = []
    for event_id in evidence_ids:
        event = known_by_id.get(event_id)
        if event is None:
            return "FACT_EVIDENCE_UNKNOWN"
        cited.append(event)
    if any(event.id not in winning_ids for event in cited):
        return "FACT_EVIDENCE_UNKNOWN"
    window_end = period_bounds(as_of)[-1][2]
    for event in cited:
        if not event_touches_window(event, window_start, window_end):
            return "FACT_EVIDENCE_OUT_OF_WINDOW"
    if _ALIAS_RE.search(statement):
        return "FACT_ALIAS_IN_STATEMENT"
    collapsed_statement = statement.casefold()
    for internal in INTERNAL_ONLY_LABELS:
        if internal.casefold() in collapsed_statement:
            return "FACT_INTERNAL_LABEL"
    if _SYSTEM_TOKEN_RE.search(collapsed_statement) and any(
        event.type == "screen.hour" for event in cited
    ):
        return "FACT_SCREEN_SYSTEM_CATEGORY"
    known_ids: set[str] = set(evidence_ids)
    for event in cited:
        if event.type.startswith("github."):
            data: Any = event.data
            repo: str = data.repo
            known_ids.add(repo)
            known_ids.update(repo.split("/"))
    all_feed = bool(cited) and all(event.type == "feed.item" for event in cited)
    masked_statement = _mask_cited_repos(statement, cited)
    tokens = extract_number_tokens(masked_statement, known_ids=known_ids)
    mentions = _period_mentions(masked_statement)
    paired = _pair_periods(tokens, mentions)
    named = {name for name, _, _ in mentions}
    if open_families and (_cited_period_families(cited) & open_families):
        for token, period in zip(tokens, paired):
            if token.value == 0 and period == "last":
                return "FACT_OPEN_HOUR_ZERO"
    for token, period in zip(tokens, paired):
        token_abs = abs(token.value)
        if all_feed and Decimal(len(cited)) == token_abs:
            continue
        if _snapshot_backs(
            token_abs, token.places, snapshot, cited, as_of, period, named
        ):
            continue
        return "FACT_NUMBER_UNBACKED"
    collapsed = _collapse(statement)
    for value in _leak_values(winners):
        if _collapse(value) in collapsed:
            return "FACT_PRIVATE_TEXT_LEAK"
    statement_words = _words(statement)
    statement_grams = {
        tuple(statement_words[i : i + 5]) for i in range(len(statement_words) - 4)
    }
    if statement_grams:
        for title in feed_titles:
            title_words = _words(title)
            title_grams = {
                tuple(title_words[i : i + 5]) for i in range(len(title_words) - 4)
            }
            if statement_grams & title_grams:
                return "FACT_FEED_HEADLINE_OVERLAP"
    return None
