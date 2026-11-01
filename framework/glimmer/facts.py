"""Two-pass fact extraction core (Ticket 9).

Pure: no wall clock, no env read, no network except through the injected
``llm``. Same events plus same recorded responses give byte-identical
results, including ``prompt_hash``, fact IDs, and dropped codes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, cast

from pydantic import ValidationError

from framework.briefing.context import MetricSnapshot
from framework.briefing.numbers import extract_number_tokens
from framework.glimmer.checks import check_fact, highest_tier, resolve_aliases
from framework.glimmer.metrics import (
    WINDOW,
    build_metric_snapshot,
    build_period_rollup,
    fixed_offset,
    select_winners,
)
from framework.glimmer.prompt import (
    REPAIR_SUFFIX,
    build_feed_prompt,
    build_personal_prompt,
)
from framework.glimmer.schemas import FactDraftBatch, FeedTopicBatch
from framework.schemas.base import Tier
from framework.schemas.core import Fact, FactWindow
from framework.schemas.events import Event, FeedItemData

ALLOWED_TYPES = frozenset(
    {
        "calendar.event.created",
        "calendar.event.updated",
        "calendar.event.cancelled",
        "github.push",
        "github.pr",
        "github.issue",
        "github.release",
        "feed.item",
        "screen.hour",
    }
)

MAX_FEED_PER_SOURCE = 7
MAX_PROMPT_EVENTS = 200
MAX_FACTS = 12


class LLMUnavailableError(Exception):
    """Timeout, transport, or non-2xx failure; message carries status only."""

    def __init__(self, message: str = "", *, latency_ms: int = 0) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


@dataclass(frozen=True)
class LLMResponse:
    text: str  # message.content only; reasoning_content never reaches here
    model_id: str  # sanitised by the client: last path component, or "unreported"
    latency_ms: int
    finish_reason: str | None  # e.g. "stop", "length"; None when unset
    completion_tokens: int | None


class LLMClient(Protocol):
    def complete(self, prompt: str) -> LLMResponse: ...


@dataclass(frozen=True)
class DroppedFact:
    statement_hash: str  # sha256(statement)[:12]; text never logged or printed
    code: str


@dataclass(frozen=True)
class PassResult:
    name: Literal["personal", "feed"]
    attempts: int  # 0, 1, or 2
    raw_valid: bool
    model_id: str  # sanitised; "" when no attempt returned
    latency_ms: int  # sum over attempts
    finish_reason: str | None  # last returned attempt's
    completion_tokens: int | None  # sum over attempts when reported
    kept: int
    noop_reason: str | None  # per-pass NOOP_* code, None when kept >= 1


@dataclass(frozen=True)
class AttemptRecord:
    pass_name: Literal["personal", "feed"]
    attempt: int  # 1-based within the pass
    content: str  # raw message.content of that attempt (local persistence only)


@dataclass(frozen=True)
class FactResult:
    facts: tuple[Fact, ...]
    snapshot: MetricSnapshot
    passes: tuple[PassResult, PassResult]  # always (personal, feed) order
    responses: tuple[AttemptRecord, ...]
    cycle_id: str
    subject_id: str
    as_of: datetime
    window_start: datetime
    prompt_hash: str  # sha256 over both first-attempt prompts
    dropped: tuple[DroppedFact, ...]
    is_noop: bool  # True iff no fact from either pass
    noop_reason: str | None  # "NOOP_NO_FACTS" when is_noop, else None


def _drop(statement: str, code: str) -> DroppedFact:
    return DroppedFact(
        statement_hash=hashlib.sha256(statement.encode()).hexdigest()[:12],
        code=code,
    )


def _mint_id(statement: str, evidence_ids: Sequence[str]) -> str:
    joined = "\x00".join(sorted(evidence_ids))
    digest = hashlib.sha256(f"{statement}\x00{joined}".encode()).hexdigest()[:12]
    return f"fact:{digest}"


def _feed_source(event: Event) -> str:
    return cast(FeedItemData, event.data).source


def _feed_score(event: Event) -> float:
    return cast(FeedItemData, event.data).score


def _cap_feed(feed_winners: Sequence[Event]) -> list[Event]:
    """Top ``MAX_FEED_PER_SOURCE`` per source; raw scores never cross sources."""
    by_source: dict[str, list[Event]] = {}
    for event in feed_winners:
        by_source.setdefault(_feed_source(event), []).append(event)
    capped: list[Event] = []
    for rows in by_source.values():
        rows.sort(key=lambda e: (-_feed_score(e), -e.time.timestamp(), e.id))
        capped.extend(rows[:MAX_FEED_PER_SOURCE])
    capped.sort(key=lambda e: (e.time, e.id))
    return capped


def _skipped(
    name: Literal["personal", "feed"], reason: str
) -> tuple[PassResult, list[AttemptRecord], str]:
    return (
        PassResult(
            name=name,
            attempts=0,
            raw_valid=False,
            model_id="",
            latency_ms=0,
            finish_reason=None,
            completion_tokens=None,
            kept=0,
            noop_reason=reason,
        ),
        [],
        "",
    )


def _parse_personal(text: str) -> FactDraftBatch | None:
    try:
        return FactDraftBatch.model_validate(json.loads(text))
    except (ValueError, ValidationError, RecursionError):
        return None


def _parse_feed(text: str) -> FeedTopicBatch | None:
    try:
        return FeedTopicBatch.model_validate(json.loads(text))
    except (ValueError, ValidationError, RecursionError):
        return None


def _run_llm[BatchT](
    llm: LLMClient,
    prompt: str,
    parse: Callable[[str], BatchT | None],
    is_empty: Callable[[BatchT], bool],
) -> tuple[list[LLMResponse], int, str | None, bool, BatchT | None, int]:
    """Call once, with exactly one repair retry after invalid output.

    Returns ``(responses, calls, failure, batch_empty, batch, error_ms)``.
    ``failure`` is a per-pass NOOP code or None when an attempt parsed;
    ``batch_empty`` is True only when a parsed batch held zero items;
    ``error_ms`` is the failed attempt's own latency, which returned
    attempts never report.
    """
    try:
        first = llm.complete(prompt)
    except LLMUnavailableError as exc:
        return ([], 1, "NOOP_LLM_UNAVAILABLE", False, None, exc.latency_ms)
    responses = [first]
    if first.finish_reason == "length":
        return (responses, 1, "NOOP_LLM_TRUNCATED", False, None, 0)
    batch = parse(first.text)
    if batch is not None:
        return (responses, 1, None, is_empty(batch), batch, 0)
    try:
        second = llm.complete(prompt + REPAIR_SUFFIX)
    except LLMUnavailableError as exc:
        return (responses, 2, "NOOP_LLM_UNAVAILABLE", False, None, exc.latency_ms)
    responses.append(second)
    if second.finish_reason == "length":
        return (responses, 2, "NOOP_LLM_TRUNCATED", False, None, 0)
    batch = parse(second.text)
    if batch is not None:
        return (responses, 2, None, is_empty(batch), batch, 0)
    return (responses, 2, "NOOP_INVALID_LLM_OUTPUT", False, None, 0)


def _summarise(
    name: Literal["personal", "feed"],
    responses: list[LLMResponse],
    calls: int,
    kept: int,
    failure: str | None,
    batch_empty: bool,
    empty_reason: str,
    dropped_reason: str,
    error_ms: int = 0,
) -> tuple[PassResult, list[AttemptRecord]]:
    if failure is not None:
        noop: str | None = failure
    elif batch_empty:
        noop = empty_reason
    elif kept == 0:
        noop = dropped_reason
    else:
        noop = None
    tokens = [r.completion_tokens for r in responses if r.completion_tokens is not None]
    records = [
        AttemptRecord(pass_name=name, attempt=i + 1, content=r.text)
        for i, r in enumerate(responses)
    ]
    return (
        PassResult(
            name=name,
            attempts=calls,
            raw_valid=failure is None,
            model_id=responses[-1].model_id if responses else "",
            latency_ms=sum(r.latency_ms for r in responses) + error_ms,
            finish_reason=responses[-1].finish_reason if responses else None,
            completion_tokens=sum(tokens) if tokens else None,
            kept=kept,
            noop_reason=noop,
        ),
        records,
    )


def extract_facts(
    as_of: datetime, subject_id: str, events: Sequence[Event], llm: LLMClient
) -> FactResult:
    """Filter, measure, prompt twice, check, and mint the cycle's facts."""
    as_of = fixed_offset(as_of)
    window_start = as_of - WINDOW
    filtered = [
        e
        for e in events
        if e.subject_id == subject_id
        and window_start <= e.time < as_of
        and e.collected_at <= as_of
        and e.type in ALLOWED_TYPES
    ]
    winners = select_winners(filtered)
    snapshot = build_metric_snapshot(as_of, winners)
    rollup = build_period_rollup(as_of, winners)
    known_by_id = {e.id: e for e in filtered}
    winning_ids = frozenset(e.id for e in winners)
    winners_list = list(winners)
    feed_titles = [
        cast(FeedItemData, e.data).title for e in filtered if e.type == "feed.item"
    ]

    kept: list[Fact] = []
    dropped: list[DroppedFact] = []
    seen_ids: set[str] = set()

    def _keep(statement: str, evidence_ids: Sequence[str], tier: Tier) -> None:
        fact_id = _mint_id(statement, evidence_ids)
        if fact_id in seen_ids:
            dropped.append(_drop(statement, "FACT_DUPLICATE"))
            return
        if len(kept) >= MAX_FACTS:
            dropped.append(_drop(statement, "FACT_OVER_LIMIT"))
            return
        seen_ids.add(fact_id)
        kept.append(
            Fact(
                id=fact_id,
                subject_id=subject_id,
                window=FactWindow(start=window_start, end=as_of),
                statement=statement,
                evidence=list(evidence_ids),
                tier=tier,
            )
        )

    def _checked(statement: str, evidence_ids: Sequence[str]) -> str | None:
        return check_fact(
            statement,
            evidence_ids,
            known_by_id=known_by_id,
            winning_ids=winning_ids,
            winners=winners_list,
            snapshot=snapshot,
            feed_titles=feed_titles,
            as_of=as_of,
            window_start=window_start,
        )

    # Personal pass: most recent MAX_PROMPT_EVENTS winning non-feed rows.
    personal_rows = [e for e in winners if e.type != "feed.item"]
    prompt_rows = personal_rows[-MAX_PROMPT_EVENTS:]
    if not prompt_rows:
        personal_pass, personal_records, personal_prompt = _skipped(
            "personal", "NOOP_NO_PERSONAL_EVENTS"
        )
    else:
        aliased = [(f"e{i + 1}", e) for i, e in enumerate(prompt_rows)]
        personal_prompt = build_personal_prompt(
            as_of, window_start, snapshot, rollup, aliased
        )
        alias_map = {alias: e.id for alias, e in aliased}
        responses, calls, failure, empty, batch, error_ms = _run_llm(
            llm, personal_prompt, _parse_personal, lambda b: b.facts == []
        )
        if failure is None and batch is not None:
            for draft in batch.facts:
                resolved = resolve_aliases(draft.evidence, alias_map)
                if resolved is None:
                    dropped.append(_drop(draft.statement, "FACT_EVIDENCE_UNKNOWN"))
                    continue
                code = _checked(draft.statement, resolved)
                if code is not None:
                    dropped.append(_drop(draft.statement, code))
                    continue
                _keep(
                    draft.statement,
                    resolved,
                    cast(Tier, highest_tier([known_by_id[i] for i in resolved])),
                )
        personal_kept = len(kept)
        personal_pass, personal_records = _summarise(
            "personal",
            responses,
            calls,
            personal_kept,
            failure,
            empty,
            "NOOP_MODEL_RETURNED_NO_FACTS",
            "NOOP_ALL_FACTS_DROPPED",
            error_ms,
        )

    # Feed pass: capped winners only.
    capped = _cap_feed([e for e in winners if e.type == "feed.item"])
    if not capped:
        feed_pass, feed_records, feed_prompt = _skipped("feed", "NOOP_NO_FEED_ITEMS")
    else:
        f_aliased = [(f"f{i + 1}", e) for i, e in enumerate(capped)]
        feed_prompt = build_feed_prompt(f_aliased)
        feed_map = {alias: e.id for alias, e in f_aliased}
        responses, calls, failure, empty, batch, error_ms = _run_llm(
            llm, feed_prompt, _parse_feed, lambda b: b.topics == []
        )
        feed_start = len(kept)
        if failure is None and batch is not None:
            for topic in batch.topics:
                clean = " ".join(topic.topic.split())
                if len(clean.split()) > 6 or extract_number_tokens(
                    clean, known_ids=set()
                ):
                    dropped.append(_drop(topic.topic, "FACT_FEED_TOPIC_SHAPE"))
                    continue
                resolved = resolve_aliases(topic.evidence, feed_map)
                if resolved is None:
                    dropped.append(_drop(topic.topic, "FACT_EVIDENCE_UNKNOWN"))
                    continue
                distinct = sorted(set(resolved))
                statement = f"{len(distinct)} feed items about {clean}"
                code = _checked(statement, distinct)
                if code is not None:
                    dropped.append(_drop(statement, code))
                    continue
                _keep(statement, distinct, "public")
        feed_pass, feed_records = _summarise(
            "feed",
            responses,
            calls,
            len(kept) - feed_start,
            failure,
            empty,
            "NOOP_MODEL_RETURNED_NO_FACTS",
            "NOOP_ALL_FACTS_DROPPED",
            error_ms,
        )

    prompt_hash = hashlib.sha256(
        (personal_prompt + "\x00" + feed_prompt).encode()
    ).hexdigest()
    is_noop = not kept
    return FactResult(
        facts=tuple(kept),
        snapshot=snapshot,
        passes=(personal_pass, feed_pass),
        responses=(*personal_records, *feed_records),
        cycle_id=(
            f"cycle-{subject_id}-"
            f"{as_of.astimezone(UTC).strftime('%Y%m%dT%H%M%SZ')}-"
            f"{prompt_hash[:8]}"
        ),
        subject_id=subject_id,
        as_of=as_of,
        window_start=window_start,
        prompt_hash=prompt_hash,
        dropped=tuple(dropped),
        is_noop=is_noop,
        noop_reason="NOOP_NO_FACTS" if is_noop else None,
    )
