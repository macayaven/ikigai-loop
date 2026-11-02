"""Ticket 13 slice 4: trace reads the stored rows only (made-up data)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals.glimmer_cases import RecordingLLM, personal_batch
from framework.briefing.context import TimeInterval
from framework.briefing.schemas import Briefing, Commitment
from framework.cycle import run_cycle
from framework.cycle.card_build import build_card, minimal_chart_data
from framework.cycle.slot_ledger import SlotLedger
from framework.glimmer.facts import ALLOWED_TYPES, MAX_PROMPT_EVENTS
from framework.glimmer.metrics import (
    WINDOW,
    build_metric_snapshot,
    period_bounds,
    select_winners,
)
from framework.proposal.core import AttemptOutcome, ProposalResult
from framework.schemas.events import Event
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.store.store import EventStore

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-a"
AS_OF = datetime(2026, 11, 2, 15, 5, tzinfo=MADRID)
SLOT = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)

HOUR_START = SLOT.replace(hour=16, minute=0)
HOUR_END = SLOT.replace(hour=17, minute=0)


def _event(
    eid: str,
    etype: str,
    moment: datetime,
    data: dict,
    *,
    source: str = "synthetic",
    source_id: str | None = None,
    tier: str = "public",
) -> Event:
    collected = moment + timedelta(minutes=5)
    payload = dict(data)
    payload["type"] = etype
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": SUBJECT,
            "source": source,
            "type": etype,
            "time": moment.isoformat(),
            "source_id": source_id or f"{etype}-{eid}",
            "data": payload,
            "tier": tier,
            "collected_at": collected.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def _seeds() -> tuple[Event, ...]:
    return (
        _event(
            "evt-push-1",
            "github.push",
            AS_OF - timedelta(hours=26),
            {"repo": "synthetic/quiet", "counts": {"commits": 2}},
            source="github",
        ),
        _event(
            "evt-push-2",
            "github.push",
            AS_OF - timedelta(hours=3),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
            source="github",
        ),
        _event(
            "evt-pr-1",
            "github.pr",
            AS_OF - timedelta(hours=5),
            {"repo": "synthetic/quiet", "counts": {"opened": 1}},
            source="github",
        ),
        _event(
            "evt-pr-2",
            "github.pr",
            AS_OF - timedelta(hours=30),
            {"repo": "synthetic/quiet", "counts": {"opened": 1}},
            source="github",
        ),
        _event(
            "evt-screen-last",
            "screen.hour",
            AS_OF - timedelta(hours=4),
            {"device": "mac", "minutes_by_category": {"code": 90.0}},
            source="activitywatch",
            tier="private",
        ),
        _event(
            "evt-screen-prior",
            "screen.hour",
            AS_OF - timedelta(hours=30),
            {"device": "mac", "minutes_by_category": {"ai": 60.0}},
            source="activitywatch",
            tier="private",
        ),
        _event(
            "evt-feed-1",
            "feed.item",
            AS_OF - timedelta(hours=6),
            {
                "title": "Synthetic vector index update",
                "url": "https://example.invalid/synthetic-item",
                "source": "hf",
                "score": 9.5,
            },
            source="feed",
        ),
        _event(
            "evt-cal-1",
            "calendar.event.created",
            AS_OF - timedelta(hours=8),
            {
                "start": (AS_OF - timedelta(hours=8)).isoformat(),
                "end": (AS_OF - timedelta(hours=6)).isoformat(),
                "busy": True,
                "category": "personal",
                "tags": ["iki-focus"],
                "is_new": False,
            },
            source="calendar",
            tier="private",
        ),
        _event(
            "evt-cal-cancelled",
            "calendar.event.cancelled",
            AS_OF - timedelta(hours=50),
            {
                "start": (AS_OF - timedelta(hours=50)).isoformat(),
                "end": (AS_OF - timedelta(hours=49)).isoformat(),
                "busy": False,
                "category": "personal",
                "tags": ["iki-focus"],
                "is_new": False,
            },
            source="calendar",
            tier="private",
        ),
    )


def _winners(events: tuple[Event, ...]) -> tuple[Event, ...]:
    rows = [event for event in events if event.collected_at <= AS_OF]
    return select_winners(rows)


def _clip(start: datetime, end: datetime, low: datetime, high: datetime) -> float:
    lowed = max(start, low)
    highed = min(end, high)
    return max(0.0, (highed - lowed).total_seconds() / 3600.0)


def _data(event: Event) -> Any:
    return event.data


def _formula(mid: str, rows: tuple[Event, ...]) -> float:
    if mid.startswith("screen_hours."):
        category = mid.removeprefix("screen_hours.")
        total = 0.0
        for event in rows:
            assert event.type == "screen.hour"
            total += float(_data(event).minutes_by_category.get(category, 0.0)) / 60.0
        return total
    if ".screen_hours." in mid:
        return _formula("screen_hours." + mid.split(".screen_hours.")[1], rows)
    if mid in ("github.push.count", "github.pr.count"):
        return float(len(rows))
    if mid.endswith((".pushes", ".prs")):
        return float(len(rows))
    if mid == "calendar.busy_hours":
        return sum(
            _clip(
                _data(event).start,
                _data(event).end,
                AS_OF - WINDOW,
                AS_OF,
            )
            for event in rows
        )
    if mid.startswith("tag_hours."):
        tag = mid.removeprefix("tag_hours.")
        assert all(tag in _data(event).tags for event in rows)
        return sum(
            _clip(_data(event).start, _data(event).end, AS_OF - WINDOW, AS_OF)
            for event in rows
        )
    if ".tag_hours." in mid:
        head, tag = mid.split(".tag_hours.")
        period = head.removeprefix("period.")
        bounds = {name: (low, high) for name, low, high in period_bounds(AS_OF)}
        low, high = bounds[period]
        assert all(tag in _data(event).tags for event in rows)
        return sum(
            _clip(_data(event).start, _data(event).end, low, high) for event in rows
        )
    if mid.startswith("feed.item.count"):
        return float(len(rows))
    if mid.endswith(tuple(f".cancelled.{tag}" for tag in ("iki-focus",))):
        return float(len(rows))
    raise AssertionError(f"no formula for {mid}")


METRIC_IDS = (
    "screen_hours.code",
    "period.last.screen_hours.code",
    "github.push.count",
    "github.pr.count",
    "period.last.pushes",
    "period.prior.prs",
    "calendar.busy_hours",
    "feed.item.count",
    "feed.item.count.hf",
    "tag_hours.iki-focus",
    "period.last.tag_hours.iki-focus",
    "period.prior.cancelled.iki-focus",
)


@pytest.mark.parametrize("mid", METRIC_IDS)
def test_metric_sources_recompute_to_snapshot(mid: str) -> None:
    from framework.cycle.trace import metric_sources

    winners = _winners(_seeds())
    rows = metric_sources(mid, AS_OF, winners)
    assert rows is not None
    snapshot = build_metric_snapshot(AS_OF, winners)
    assert _formula(mid, rows) == pytest.approx(snapshot.values.get(mid, 0.0))


def _at(
    eid: str,
    etype: str,
    moment: datetime,
    data: dict,
    collected: datetime,
    *,
    source: str = "synthetic",
    source_id: str | None = None,
    tier: str = "public",
) -> Event:
    payload = dict(data)
    payload["type"] = etype
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": SUBJECT,
            "source": source,
            "type": etype,
            "time": moment.isoformat(),
            "source_id": source_id or f"{etype}-{eid}",
            "data": payload,
            "tier": tier,
            "collected_at": collected.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def _cal(
    eid: str,
    etype: str,
    start: datetime,
    end: datetime,
    busy: bool,
    tags: list[str],
    collected: datetime,
) -> Event:
    return _at(
        eid,
        etype,
        start,
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "busy": busy,
            "category": "personal",
            "tags": tags,
            "is_new": False,
        },
        collected,
        source="calendar",
        tier="private",
    )


def _floored_spans() -> tuple[
    tuple[datetime, datetime], dict[str, tuple[datetime, datetime]]
]:
    from framework.glimmer.metrics import window_bounds

    window = window_bounds(AS_OF)
    periods = {name: (low, high) for name, low, high in period_bounds(AS_OF)}
    return window, periods


def _edge_value(mid: str, rows: tuple[Event, ...]) -> float:
    """Recompute with the floored spans the snapshot clips to."""
    window, periods = _floored_spans()
    if mid == "calendar.busy_hours" or mid.startswith("tag_hours."):
        return sum(
            _clip(_data(event).start, _data(event).end, window[0], window[1])
            for event in rows
        )
    if ".tag_hours." in mid and ".cancelled." not in mid:
        head, tag = mid.split(".tag_hours.")
        low, high = periods[head.removeprefix("period.")]
        assert all(tag in _data(event).tags for event in rows)
        return sum(
            _clip(_data(event).start, _data(event).end, low, high) for event in rows
        )
    if ".cancelled." in mid:
        return float(len(rows))
    return _formula(mid, rows)


EDGE_METRIC_IDS = (
    "screen_hours.code",
    "period.last.screen_hours.code",
    "period.prior.screen_hours.code",
    "github.push.count",
    "github.pr.count",
    "period.last.pushes",
    "period.prior.prs",
    "calendar.busy_hours",
    "feed.item.count",
    "feed.item.count.hf",
    "feed.item.count.other",
    "tag_hours.iki-focus",
    "period.last.tag_hours.iki-focus",
    "period.prior.tag_hours.iki-focus",
    "tag_hours.edge-start",
    "tag_hours.edge-mid",
    "tag_hours.edge-end",
    "tag_hours.quiet-tag",
    "period.last.tag_hours.edge-end",
    "period.prior.tag_hours.edge-mid",
    "period.last.tag_hours.edge-mid",
    "period.last.cancelled.other-tag",
    "period.prior.cancelled.iki-focus",
)


def _edge_seeds() -> tuple[Event, ...]:
    window, periods = _floored_spans()
    window_start, window_end = window
    last_start, _ = periods["last"]
    floor = window_end
    return (
        *_seeds(),
        # Outside the window on both sides: neither counts anywhere.
        _at(
            "x-push-before",
            "github.push",
            window_start - timedelta(hours=1),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
            window_start - timedelta(minutes=55),
            source="github",
        ),
        # In the open hour: winners keep it, no family touches it.
        _at(
            "x-push-open",
            "github.push",
            floor + timedelta(minutes=2),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
            floor + timedelta(minutes=3),
            source="github",
        ),
        _at(
            "x-screen-open",
            "screen.hour",
            floor,
            {"device": "mac", "minutes_by_category": {"code": 30.0}},
            floor + timedelta(minutes=3),
            source="activitywatch",
            tier="private",
        ),
        # A pull request that is not an opening counts nothing.
        _at(
            "x-pr-closed",
            "github.pr",
            last_start + timedelta(hours=2),
            {"repo": "synthetic/quiet", "counts": {"opened": 0}},
            last_start + timedelta(hours=2, minutes=5),
            source="github",
        ),
        # The same screen category and the same tag in another period.
        _at(
            "x-screen-prior-code",
            "screen.hour",
            last_start - timedelta(hours=3),
            {"device": "mac", "minutes_by_category": {"code": 30.0}},
            last_start - timedelta(hours=2, minutes=55),
            source="activitywatch",
            tier="private",
        ),
        _cal(
            "x-tag-prior",
            "calendar.event.created",
            last_start - timedelta(hours=5),
            last_start - timedelta(hours=3),
            True,
            ["iki-focus"],
            last_start - timedelta(hours=2, minutes=55),
        ),
        # A cancelled block with another tag, in the last period.
        _cal(
            "x-cancel-other",
            "calendar.event.cancelled",
            last_start + timedelta(hours=17),
            last_start + timedelta(hours=18),
            False,
            ["other-tag"],
            last_start + timedelta(hours=18, minutes=5),
        ),
        # A cancelled block with another tag in the prior period, the same
        # period the probed `period.prior.cancelled.iki-focus` reads, so a
        # dropped tag filter would wrongly count it.
        _cal(
            "x-cancel-other-prior",
            "calendar.event.cancelled",
            last_start - timedelta(hours=20),
            last_start - timedelta(hours=19),
            False,
            ["other-tag"],
            last_start - timedelta(hours=18, minutes=55),
        ),
        # A busy block wholly before the window: every calendar family
        # must leave it out, while the value recompute clips it to zero.
        _cal(
            "x-cal-outside",
            "calendar.event.created",
            window_start - timedelta(hours=5),
            window_start - timedelta(hours=3),
            True,
            ["iki-focus"],
            window_start - timedelta(hours=2, minutes=55),
        ),
        # A calendar row that isn't busy still carries its tag, not hours.
        _cal(
            "x-quiet",
            "calendar.event.updated",
            last_start + timedelta(hours=19),
            last_start + timedelta(hours=20),
            False,
            ["quiet-tag"],
            last_start + timedelta(hours=20, minutes=5),
        ),
        # A feed row from another source.
        _at(
            "x-feed-other",
            "feed.item",
            last_start + timedelta(hours=18),
            {
                "title": "Synthetic other source item",
                "url": "https://example.invalid/synthetic-other",
                "source": "other",
                "score": 5.0,
            },
            last_start + timedelta(hours=18, minutes=5),
            source="feed",
        ),
        # Blocks crossing the window's start, a period edge, and its end.
        _cal(
            "x-edge-start",
            "calendar.event.created",
            window_start - timedelta(hours=2),
            window_start + timedelta(hours=2),
            True,
            ["edge-start"],
            window_start + timedelta(hours=2, minutes=5),
        ),
        _cal(
            "x-edge-mid",
            "calendar.event.updated",
            last_start - timedelta(hours=2),
            last_start + timedelta(hours=2),
            True,
            ["edge-mid"],
            last_start + timedelta(hours=2, minutes=5),
        ),
        _cal(
            "x-edge-end",
            "calendar.event.created",
            floor - timedelta(hours=1),
            floor + timedelta(hours=1),
            True,
            ["edge-end"],
            floor - timedelta(minutes=30),
        ),
        # A screen row stamped before the window: outside on that side.
        _at(
            "x-screen-early",
            "screen.hour",
            window_start - timedelta(hours=5),
            {"device": "mac", "minutes_by_category": {"code": 60.0}},
            window_start - timedelta(hours=4, minutes=55),
            source="activitywatch",
            tier="private",
        ),
    )


@pytest.mark.parametrize("mid", EDGE_METRIC_IDS)
def test_metric_sources_recompute_with_open_hour_and_edge_blocks(
    mid: str,
) -> None:
    """Open-hour rows and edge-crossing blocks still equal the snapshot.

    One extra push and one extra screen row sit in the open hour, calendar
    blocks cross the window's start, a period edge and the window's end,
    and every probed filter (unopened PR, same category/tag in another
    period, other-tag cancelled block, non-busy row, other feed source,
    rows outside on both sides) has a row it must leave out. The
    recompute clips each block to the floored span the snapshot uses.
    """
    from framework.cycle.trace import metric_sources

    events = _edge_seeds()
    winners = _winners(events)
    rows = metric_sources(mid, AS_OF, winners)
    assert rows is not None
    snapshot = build_metric_snapshot(AS_OF, winners)
    assert _edge_value(mid, rows) == pytest.approx(snapshot.values.get(mid, 0.0))


def test_metric_sources_unknown_family_is_none() -> None:
    from framework.cycle.trace import metric_sources

    assert metric_sources("no.such.family", AS_OF, _winners(_seeds())) is None


@pytest.mark.parametrize(
    ("mid", "expected"),
    (
        (
            "calendar.busy_hours",
            {"evt-cal-1", "x-tag-prior", "x-edge-start", "x-edge-mid", "x-edge-end"},
        ),
        ("tag_hours.iki-focus", {"evt-cal-1", "x-tag-prior"}),
        ("tag_hours.edge-start", {"x-edge-start"}),
        ("tag_hours.edge-mid", {"x-edge-mid"}),
        ("tag_hours.edge-end", {"x-edge-end"}),
        ("period.last.tag_hours.iki-focus", {"evt-cal-1"}),
        ("period.prior.tag_hours.iki-focus", {"x-tag-prior"}),
        ("period.last.tag_hours.edge-mid", {"x-edge-mid"}),
        ("period.prior.tag_hours.edge-mid", {"x-edge-mid"}),
        ("period.last.tag_hours.edge-end", {"x-edge-end"}),
        ("period.prior.cancelled.iki-focus", set()),
        ("period.last.cancelled.other-tag", {"x-cancel-other"}),
    ),
)
def test_metric_sources_calendar_families_return_exact_rows(
    mid: str, expected: set[str]
) -> None:
    """Calendar families return exactly the rows their span and tag allow.

    The value recompute clips an out-of-span block to zero, so a family
    that forgets its span or its tag still adds up. The id set catches
    it: `x-cal-outside` sits wholly before the window, `x-cancel-other`
    and `x-cancel-other-prior` carry another tag, and the edge blocks
    cross the window's start, a period edge and the window's end.
    """
    from framework.cycle.trace import metric_sources

    winners = _winners(_edge_seeds())
    rows = metric_sources(mid, AS_OF, winners)
    assert rows is not None
    assert {event.id for event in rows} == expected


def _alias_of_push(events: tuple[Event, ...]) -> str:
    winners = select_winners(
        [
            event
            for event in events
            if event.type in ALLOWED_TYPES and event.collected_at <= AS_OF
        ]
    )
    prompt_rows = [event for event in winners if event.type != "feed.item"][
        -MAX_PROMPT_EVENTS:
    ]
    for index, event in enumerate(prompt_rows):
        if event.id == "evt-push-2":
            return f"e{index + 1}"
    raise AssertionError("push winner missing from prompt rows")


def _briefing(
    code_fact_id: str,
    model_fact_id: str,
    metric_id: str,
    metric_value: float,
    *,
    ghost: str | None = None,
) -> Briefing:
    start = HOUR_START.isoformat()
    end = HOUR_END.isoformat()
    return Briefing.model_validate(
        {
            "id": "brf-trace-1",
            "profile_id": "builder",
            "subject_id": SUBJECT,
            "slot": SLOT.isoformat(),
            "sections": [
                {
                    "type": "overall_state",
                    "claims": [
                        {
                            "id": "c-overall-1",
                            "text": "The recorded session stands as noted",
                            "fact_ids": [ghost or code_fact_id],
                            "metric_refs": [],
                        }
                    ],
                },
                {
                    "type": "working",
                    "claims": [
                        {
                            "id": "c-working-1",
                            "text": "The recorded push stands as noted",
                            "fact_ids": [model_fact_id],
                            "metric_refs": [],
                        },
                        {
                            "id": "c-working-2",
                            "text": "Pushes were 2 in the last period",
                            "fact_ids": [],
                            "metric_refs": [
                                {"metric_id": metric_id, "value": metric_value}
                            ],
                        },
                    ],
                },
                {
                    "type": "actions",
                    "claims": [],
                    "actions": [
                        {
                            "id": "act-1",
                            "commitment_id": "b-1",
                            "kind": "build",
                            "text": "Model action wording",
                            "dimension": "love",
                            "proposed_start": start,
                            "proposed_end": end,
                        }
                    ],
                },
            ],
        }
    )


def _attempt() -> AttemptOutcome:
    return AttemptOutcome(
        number=1,
        model_requested="synthetic-model",
        model_reported="synthetic-model",
        effort="high",
        prompt_hash="synthetic-hash",
        raw_text="{}",
        parsed_ok=True,
        blocked=False,
        codes=(),
        latency_ms=7,
        prompt_tokens=11,
        completion_tokens=13,
        reasoning_tokens=None,
        finish_reason="stop",
        transport="muse",
        transport_version="synthetic 1.0",
    )


def _build_db(db: Path, ghost: bool = False) -> dict[str, str]:
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(_seeds())) == len(_seeds())
        fact_store = FactStore(db_path=store.db_path)
        try:
            stub = RecordingLLM(
                (
                    personal_batch(
                        {
                            "statement": "The recorded push activity stands as noted",
                            "evidence": [_alias_of_push(_seeds())],
                        }
                    ),
                )
            )
            result, run = run_cycle(
                AS_OF, SUBJECT, store, fact_store, stub, feed_pass=False
            )
            assert any(
                fact_store.fetch_facts(result.cycle_id, run),
            )
            facts = {
                row["fact_id"]: row
                for row in fact_store.fetch_facts(result.cycle_id, run)
            }
            model_fact = next(row for row in facts.values() if row["origin"] == "model")
            code_fact = next(row for row in facts.values() if row["origin"] == "code")
            snapshot = fact_store.fetch_cycle(result.cycle_id, run)["snapshot"]
            proposal_store = ProposalStore(db_path=store.db_path)
            try:
                metric_id = "period.last.pushes"
                briefing = _briefing(
                    code_fact["fact_id"],
                    model_fact["fact_id"],
                    metric_id,
                    float(snapshot[metric_id]),
                    ghost=(None if not ghost else "fact:ghost-1"),
                )
                produced = ProposalResult(
                    kind="proposal",
                    profile_id="builder",
                    subject_id=SUBJECT,
                    cycle_id=result.cycle_id,
                    run=run,
                    slot=SLOT,
                    hour=TimeInterval(start=HOUR_START, end=HOUR_END),
                    briefing=briefing,
                    fallback=None,
                    reason_codes=(),
                    attempts=(_attempt(),),
                    cycle_age_s=0.0,
                    prompt_hash="synthetic-hash",
                )
                proposal_store.record(produced, snapshot=dict(snapshot))
                commitment = Commitment.model_validate(
                    {
                        "id": "b-1",
                        "profile_id": "builder",
                        "title": "Quiet pages draft",
                        "kind": "build",
                        "dimension": "love",
                        "evidence": "github_push",
                    }
                )
                built = build_card(
                    slot=SLOT,
                    subject_id=SUBJECT,
                    as_of=AS_OF,
                    bucket="evening",
                    results=(produced,),
                    commitments_by_id={"b-1": commitment},
                    picks={"builder": ("b-1", None)},
                    since_line="Since 13:30: nothing new recorded.",
                )
                assert built.card is not None
                ledger = SlotLedger(db)
                ledger.append_step(SLOT, "start", "ok", 0.0, None, None)
                chart = minimal_chart_data()
                ledger.save_card_step(
                    SLOT,
                    built.card.card_id,
                    {"codes": "-"},
                    built.sides,
                    built.card.model_dump_json(),
                    chart.model_dump_json(),
                    0.1,
                )
                ledger.append_step(
                    SLOT, "send_intent", "intent", 0.2, built.card.card_id, None
                )
                ledger.append_step(
                    SLOT,
                    "send",
                    "delivered",
                    0.3,
                    built.card.card_id,
                    {"message_id": "77"},
                )
                tap = _event(
                    "evt-tap-1",
                    "app.tap",
                    SLOT + timedelta(minutes=5),
                    {"block_id": built.card.card_id, "target": "A"},
                    source="telegram",
                    tier="private",
                )
                store.append_event(tap)
                return {
                    "card_id": built.card.card_id,
                    "model_fact": str(model_fact["fact_id"]),
                    "code_fact": str(code_fact["fact_id"]),
                }
            finally:
                proposal_store.close()
        finally:
            fact_store.close()
    finally:
        store.close()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_trace_prints_card_facts_events_metrics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    before = _hash(db)
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert _hash(db) == before
    out = capsys.readouterr().out
    assert f"card={ids['card_id']}" in out
    assert "delivery=delivered" in out
    assert "message=77" in out
    assert "ruling=A" in out
    assert "origin=code" in out
    assert "origin=model" in out
    assert ids["model_fact"] in out
    assert ids["code_fact"] in out
    assert "metric period.last.pushes" in out
    assert "source_events=" in out
    assert "evt-push-2" in out
    assert "since" in out.lower()


def _build_db_with_pre_window_block(db: Path) -> str:
    """A stored card whose cited calendar metric starts before the window.

    The block `x-pre-window` starts two hours before the window's start
    and ends two hours inside it. The trace must load it whole and count
    it in `source_events` on the metric line it prints.
    """
    window, _ = _floored_spans()
    window_start, _ = window
    seeds = (
        *_seeds(),
        _cal(
            "x-pre-window",
            "calendar.event.created",
            window_start - timedelta(hours=2),
            window_start + timedelta(hours=2),
            True,
            ["iki-focus"],
            window_start + timedelta(hours=2, minutes=5),
        ),
    )
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(seeds)) == len(seeds)
        fact_store = FactStore(db_path=store.db_path)
        try:
            stub = RecordingLLM(
                (
                    personal_batch(
                        {
                            "statement": "The recorded session stands as noted",
                            "evidence": [_alias_of_push(seeds)],
                        }
                    ),
                )
            )
            result, run = run_cycle(
                AS_OF, SUBJECT, store, fact_store, stub, feed_pass=False
            )
            assert any(
                fact_store.fetch_facts(result.cycle_id, run),
            )
            facts = {
                row["fact_id"]: row
                for row in fact_store.fetch_facts(result.cycle_id, run)
            }
            model_fact = next(row for row in facts.values() if row["origin"] == "model")
            code_fact = next(row for row in facts.values() if row["origin"] == "code")
            snapshot = fact_store.fetch_cycle(result.cycle_id, run)["snapshot"]
            proposal_store = ProposalStore(db_path=store.db_path)
            try:
                metric_id = "calendar.busy_hours"
                briefing = _briefing(
                    code_fact["fact_id"],
                    model_fact["fact_id"],
                    metric_id,
                    float(snapshot[metric_id]),
                )
                produced = ProposalResult(
                    kind="proposal",
                    profile_id="builder",
                    subject_id=SUBJECT,
                    cycle_id=result.cycle_id,
                    run=run,
                    slot=SLOT,
                    hour=TimeInterval(start=HOUR_START, end=HOUR_END),
                    briefing=briefing,
                    fallback=None,
                    reason_codes=(),
                    attempts=(_attempt(),),
                    cycle_age_s=0.0,
                    prompt_hash="synthetic-hash",
                )
                proposal_store.record(produced, snapshot=dict(snapshot))
                commitment = Commitment.model_validate(
                    {
                        "id": "b-1",
                        "profile_id": "builder",
                        "title": "Quiet pages draft",
                        "kind": "build",
                        "dimension": "love",
                        "evidence": "github_push",
                    }
                )
                built = build_card(
                    slot=SLOT,
                    subject_id=SUBJECT,
                    as_of=AS_OF,
                    bucket="evening",
                    results=(produced,),
                    commitments_by_id={"b-1": commitment},
                    picks={"builder": ("b-1", None)},
                    since_line="Since 13:30: nothing new recorded.",
                )
                assert built.card is not None
                ledger = SlotLedger(db)
                ledger.append_step(SLOT, "start", "ok", 0.0, None, None)
                chart = minimal_chart_data()
                ledger.save_card_step(
                    SLOT,
                    built.card.card_id,
                    {"codes": "-"},
                    built.sides,
                    built.card.model_dump_json(),
                    chart.model_dump_json(),
                    0.1,
                )
                ledger.append_step(
                    SLOT, "send_intent", "intent", 0.2, built.card.card_id, None
                )
                ledger.append_step(
                    SLOT,
                    "send",
                    "delivered",
                    0.3,
                    built.card.card_id,
                    {"message_id": "77"},
                )
                return built.card.card_id
            finally:
                proposal_store.close()
        finally:
            fact_store.close()
    finally:
        store.close()


def test_trace_metric_line_counts_block_starting_before_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A block starting before the window shows in the printed metric line.

    The trace loads calendar rows whole through the stored card, so the
    `calendar.busy_hours` line counts both the inside block and the one
    starting before the window's start: `source_events=2`.
    """
    from framework.cycle.trace import trace

    db = tmp_path / "prewindow.db"
    card_id = _build_db_with_pre_window_block(db)
    assert trace(card_id=card_id, db_path=db) == 0
    out = capsys.readouterr().out
    lines = [
        line
        for line in out.splitlines()
        if line.startswith("metric calendar.busy_hours")
    ]
    assert len(lines) == 1
    assert "source_events=2" in lines[0]


def test_trace_parent_snapshot_skips_noop_slot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    first = datetime(2026, 11, 2, 13, 30, tzinfo=MADRID)
    noop_slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    second = datetime(2026, 11, 2, 18, 0, tzinfo=MADRID)
    db = tmp_path / "parent.db"
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(_seeds())) == len(_seeds())
        fact_store = FactStore(db_path=store.db_path)
        fact_store.close()
        proposal_store = ProposalStore(db_path=store.db_path)
        try:
            hour = TimeInterval(start=HOUR_START, end=HOUR_END)
            first_briefing = _briefing("fact-x", "fact-y", "period.last.pushes", 2.0)
            first_result = ProposalResult(
                kind="proposal",
                profile_id="builder",
                subject_id=SUBJECT,
                cycle_id="cycle-one",
                run=1,
                slot=first,
                hour=hour,
                briefing=first_briefing,
                fallback=None,
                reason_codes=(),
                attempts=(_attempt(),),
                cycle_age_s=0.0,
                prompt_hash="synthetic-hash",
            )
            proposal_store.record(first_result, snapshot={"period.last.pushes": 2.0})
            noop_result = ProposalResult(
                kind="noop",
                profile_id="builder",
                subject_id=SUBJECT,
                cycle_id="cycle-noop",
                run=1,
                slot=noop_slot,
                hour=None,
                briefing=None,
                fallback=None,
                reason_codes=("NOOP_NO_FREE_HOUR",),
                attempts=(),
                cycle_age_s=0.0,
                prompt_hash="",
            )
            proposal_store.record(noop_result, snapshot={"period.last.pushes": 99.0})
            since_briefing = Briefing.model_validate(
                {
                    "id": "brf-trace-since",
                    "profile_id": "builder",
                    "subject_id": SUBJECT,
                    "slot": second.isoformat(),
                    "sections": [
                        {
                            "type": "overall_state",
                            "claims": [
                                {
                                    "id": "c-o-1",
                                    "text": "The recorded session stands as noted",
                                    "fact_ids": [],
                                }
                            ],
                        },
                        {
                            "type": "since_last",
                            "claims": [
                                {
                                    "id": "c-s-1",
                                    "text": "Pushes rose since the last card",
                                    "fact_ids": [],
                                    "metric_refs": [
                                        {
                                            "metric_id": "period.last.pushes",
                                            "value": 3.0,
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "claims": [],
                            "actions": [
                                {
                                    "id": "act-1",
                                    "commitment_id": "b-1",
                                    "kind": "build",
                                    "text": "Model action wording",
                                    "dimension": "love",
                                    "proposed_start": HOUR_START.isoformat(),
                                    "proposed_end": HOUR_END.isoformat(),
                                }
                            ],
                        },
                    ],
                }
            )
            second_result = ProposalResult(
                kind="proposal",
                profile_id="builder",
                subject_id=SUBJECT,
                cycle_id="cycle-two",
                run=1,
                slot=second,
                hour=hour,
                briefing=since_briefing,
                fallback=None,
                reason_codes=(),
                attempts=(_attempt(),),
                cycle_age_s=0.0,
                prompt_hash="synthetic-hash",
            )
            proposal_store.record(second_result, snapshot={"period.last.pushes": 5.0})
        finally:
            proposal_store.close()
        from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
        from framework.telegram.models import Card

        ledger = SlotLedger(db)
        for slot, card_id in ((first, "card-one"), (second, "card-two")):
            ledger.save_slot_cards(
                (
                    SlotCardRow(
                        card_id=card_id,
                        letter="A",
                        slot=slot,
                        subject_id=SUBJECT,
                        as_of=slot,
                        bucket="evening",
                        profile_id="builder",
                        commitment_id="b-1",
                        kind="proposal",
                        policy_pick="b-1",
                        policy_alternative=None,
                    ),
                )
            )
            card = Card.model_validate(
                {
                    "slot": slot.isoformat(),
                    "since_line": "Since 13:30: nothing new recorded.",
                    "proposals": [
                        {
                            "letter": "A",
                            "kind": "proposal",
                            "profile": "Builder",
                            "title": "Quiet pages draft",
                            "start": HOUR_START.isoformat(),
                            "end": HOUR_END.isoformat(),
                        }
                    ],
                    "statements": [],
                }
            )
            ledger.save_card_payload(
                card_id, card.model_dump_json(), minimal_chart_data().model_dump_json()
            )
            ledger.append_step(slot, "send_intent", "intent", 0.1, card_id, None)
            ledger.append_step(
                slot, "send", "delivered", 0.2, card_id, {"message_id": "7"}
            )
    finally:
        store.close()
    assert trace(card_id="card-two", db_path=db) == 0
    out = capsys.readouterr().out
    assert "metric period.last.pushes" in out
    assert "parent=2.0" in out


def test_trace_ghost_evidence_shows_found_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    db = tmp_path / "ghost.db"
    ids = _build_db(db, ghost=True)
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    out = capsys.readouterr().out
    assert "fact:ghost-1" in out
    assert "found=0" in out


def _delivered_card(
    db: Path,
    card_id: str,
    slot: datetime,
    as_of: datetime,
    message: str,
    *,
    kind: str = "proposal",
    since_line: str = "Since 13:30: nothing new recorded.",
) -> None:
    from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
    from framework.telegram.models import Card

    store = EventStore(db_path=db)
    store.close()
    fact_store = FactStore(db_path=store.db_path)
    fact_store.close()
    proposal_store = ProposalStore(db_path=store.db_path)
    proposal_store.close()
    ledger = SlotLedger(db)
    ledger.save_slot_cards(
        (
            SlotCardRow(
                card_id=card_id,
                letter="A",
                slot=slot,
                subject_id=SUBJECT,
                as_of=as_of,
                bucket="evening",
                profile_id="builder",
                commitment_id="b-1",
                kind=kind,  # type: ignore[arg-type]
                policy_pick="b-1" if kind == "proposal" else None,
                policy_alternative=None,
            ),
        )
    )
    side: dict[str, Any] = {
        "letter": "A",
        "kind": kind,
        "profile": "Builder",
        "title": "Quiet pages draft",
        "start": HOUR_START.isoformat(),
        "end": HOUR_END.isoformat(),
    }
    if kind == "fallback":
        side["reason_codes"] = ["FALLBACK_NO_EVIDENCE"]
    card = Card.model_validate(
        {
            "slot": slot.isoformat(),
            "since_line": since_line if kind == "proposal" else None,
            "proposals": [side],
            "statements": [],
        }
    )
    ledger.save_card_payload(
        card_id, card.model_dump_json(), minimal_chart_data().model_dump_json()
    )
    ledger.append_step(slot, "send_intent", "intent", 0.1, card_id, None)
    ledger.append_step(slot, "send", "delivered", 0.2, card_id, {"message_id": message})


def test_trace_fact_evidence_missing_id_shows_found_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json as _json
    import sqlite3 as _sqlite3

    from framework.cycle.trace import trace

    db = tmp_path / "found.db"
    ids = _build_db(db)
    extra_fact = "fact:synthetic-missing-1"
    raw = _sqlite3.connect(db)
    try:
        row = raw.execute(
            "SELECT cycle_id, run, subject_id, briefing_json, snapshot,"
            " hour_start, hour_end, proposal_key"
            " FROM proposal_results WHERE profile_id = ?",
            ("builder",),
        ).fetchone()
        assert row is not None
        (window_start, window_end) = raw.execute(
            "SELECT window_start, window_end FROM facts WHERE fact_id = ?",
            (ids["model_fact"],),
        ).fetchone()
        raw.execute(
            "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
            " window_start, window_end, statement, evidence, tier, origin)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row[0],
                row[1],
                extra_fact,
                row[2],
                str(window_start),
                str(window_end),
                "The recorded push stands with a missing row",
                _json.dumps(["evt-push-2", "evt-no-such-row"]),
                "public",
                "model",
            ),
        )
        briefing = _json.loads(str(row[3]))
        working = next(
            section for section in briefing["sections"] if section["type"] == "working"
        )
        working["claims"].append(
            {
                "id": "c-working-extra",
                "text": "The recorded push stands with a missing row",
                "fact_ids": [extra_fact],
                "metric_refs": [],
            }
        )
        raw.execute(
            "INSERT INTO proposal_results (proposal_key, cycle_id, run,"
            " profile_id, subject_id, slot, kind, briefing_json,"
            " fallback_json, snapshot, hour_start, hour_end, reason_codes,"
            " cycle_age_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(row[7]) + "-extra",
                row[0],
                row[1],
                "builder",
                row[2],
                SLOT.isoformat(),
                "proposal",
                _json.dumps(briefing),
                None,
                row[4],
                row[5],
                row[6],
                "",
                0.0,
            ),
        )
        raw.commit()
    finally:
        raw.close()
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    out = capsys.readouterr().out
    assert f"fact {extra_fact}" in out
    assert "cited=2 found=1" in out
    assert "event evt-no-such-row missing" in out
    assert "event evt-push-2 github.push" in out


def test_trace_delivery_reads_last_send_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace

    db = tmp_path / "delivery.db"
    _delivered_card(db, "card-delivery-1", SLOT, AS_OF, "99")
    ledger = SlotLedger(db)
    ledger.append_step(SLOT, "send_intent", "intent", 0.3, "card-delivery-1", None)
    ledger.append_step(
        SLOT, "send", "SEND_NOT_SENT", 0.4, "card-delivery-1", {"reason": "X"}
    )
    ledger.append_step(SLOT, "send_intent", "intent", 0.5, "card-delivery-1", None)
    ledger.append_step(
        SLOT, "send", "delivered", 0.6, "card-delivery-1", {"message_id": "100"}
    )
    assert trace(card_id="card-delivery-1", db_path=db) == 0
    out = capsys.readouterr().out
    assert "delivery=delivered" in out
    assert "message=100" in out


def test_trace_since_reads_latest_earlier_delivered_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    first = datetime(2026, 11, 2, 13, 30, tzinfo=MADRID)
    second = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    third = datetime(2026, 11, 2, 18, 0, tzinfo=MADRID)
    db = tmp_path / "since.db"
    store = EventStore(db_path=db)
    try:
        push = _event(
            "evt-since-push",
            "github.push",
            datetime(2026, 11, 2, 14, 0, tzinfo=MADRID),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
            source="github",
        )
        assert store.append_events([push]) == 1
    finally:
        store.close()
    _delivered_card(db, "card-since-1", first, first, "11")
    _delivered_card(db, "card-since-2", second, second, "12")
    _delivered_card(db, "card-since-3", third, third, "13")
    assert trace(card_id="card-since-3", db_path=db) == 0
    out = capsys.readouterr().out
    assert "pushes=0.0" in out
    assert "rows=0" in out


def test_trace_parent_skips_fallback_delivered_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    first = datetime(2026, 11, 2, 13, 30, tzinfo=MADRID)
    middle = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    second = datetime(2026, 11, 2, 18, 0, tzinfo=MADRID)
    db = tmp_path / "fallback-parent.db"
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(_seeds())) == len(_seeds())
        fact_store = FactStore(db_path=store.db_path)
        fact_store.close()
        proposal_store = ProposalStore(db_path=store.db_path)
        try:
            hour = TimeInterval(start=HOUR_START, end=HOUR_END)
            proposal_store.record(
                ProposalResult(
                    kind="proposal",
                    profile_id="builder",
                    subject_id=SUBJECT,
                    cycle_id="cycle-one",
                    run=1,
                    slot=first,
                    hour=hour,
                    briefing=_briefing("fact-x", "fact-y", "period.last.pushes", 2.0),
                    fallback=None,
                    reason_codes=(),
                    attempts=(_attempt(),),
                    cycle_age_s=0.0,
                    prompt_hash="synthetic-hash",
                ),
                snapshot={"period.last.pushes": 2.0},
            )
            since_briefing = Briefing.model_validate(
                {
                    "id": "brf-trace-since",
                    "profile_id": "builder",
                    "subject_id": SUBJECT,
                    "slot": second.isoformat(),
                    "sections": [
                        {
                            "type": "overall_state",
                            "claims": [
                                {
                                    "id": "c-o-1",
                                    "text": "The recorded session stands as noted",
                                    "fact_ids": [],
                                }
                            ],
                        },
                        {
                            "type": "since_last",
                            "claims": [
                                {
                                    "id": "c-s-1",
                                    "text": "Pushes rose since the last card",
                                    "fact_ids": [],
                                    "metric_refs": [
                                        {
                                            "metric_id": "period.last.pushes",
                                            "value": 5.0,
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "claims": [],
                            "actions": [
                                {
                                    "id": "act-1",
                                    "commitment_id": "b-1",
                                    "kind": "build",
                                    "text": "Model action wording",
                                    "dimension": "love",
                                    "proposed_start": HOUR_START.isoformat(),
                                    "proposed_end": HOUR_END.isoformat(),
                                }
                            ],
                        },
                    ],
                }
            )
            proposal_store.record(
                ProposalResult(
                    kind="proposal",
                    profile_id="builder",
                    subject_id=SUBJECT,
                    cycle_id="cycle-two",
                    run=1,
                    slot=second,
                    hour=hour,
                    briefing=since_briefing,
                    fallback=None,
                    reason_codes=(),
                    attempts=(_attempt(),),
                    cycle_age_s=0.0,
                    prompt_hash="synthetic-hash",
                ),
                snapshot={"period.last.pushes": 5.0},
            )
        finally:
            proposal_store.close()
    finally:
        store.close()
    _delivered_card(db, "card-one", first, first, "11")
    _delivered_card(db, "card-fb", middle, middle, "12", kind="fallback")
    _delivered_card(db, "card-two", second, second, "13")
    assert trace(card_id="card-two", db_path=db) == 0
    out = capsys.readouterr().out
    assert "metric period.last.pushes" in out
    assert "parent=2.0" in out


def test_trace_unknown_card_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    db = tmp_path / "empty.db"
    store = EventStore(db_path=db)
    store.close()
    assert trace(card_id="card-0000000000000000", db_path=db) == 2
    assert "code=UNKNOWN_CARD" in capsys.readouterr().out


def test_trace_missing_db_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    assert trace(card_id="card-0000000000000000", db_path=tmp_path / "no.db") == 2
    assert "code=NO_DB" in capsys.readouterr().out


def test_trace_builds_no_store_or_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle.trace import trace

    db = tmp_path / "sealed.db"
    ids = _build_db(db)

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("trace must not construct a store")

    monkeypatch.setattr("framework.store.store.EventStore.__init__", _boom)
    monkeypatch.setattr("framework.store.fact_store.FactStore.__init__", _boom)
    monkeypatch.setattr("framework.store.proposal_store.ProposalStore.__init__", _boom)
    monkeypatch.setattr("framework.telegram.ledger.CardLedger.__init__", _boom)
    monkeypatch.setattr("framework.cycle.slot_ledger.SlotLedger.__init__", _boom)
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert ids["card_id"] in capsys.readouterr().out


def test_trace_prints_local_retries_masked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace
    from framework.proposal.local_retry import mask_stderr

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    ledger = SlotLedger(db)
    raw = b"launcher hiccup ZzPrivateTerm fellow@example.invalid\n"
    masked = mask_stderr(raw, ("ZzPrivateTerm",))
    ledger.append_local_retry(SLOT, "builder", 1, "exit 1", 150, 1, masked)
    ledger.append_local_retry(SLOT, "builder", 2, "exit 1", 140, 1, masked)
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    out = capsys.readouterr().out
    assert "local_retries=2" in out
    assert "local_retry try=1 reason=exit 1" in out
    assert "local_retry try=2 reason=exit 1" in out
    assert "hiccup" in out
    assert "ZzPrivateTerm" not in out
    assert "fellow@example.invalid" not in out


def test_trace_without_retry_table_prints_nothing_and_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import sqlite3

    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    raw = sqlite3.connect(db)
    try:
        raw.execute("DROP TABLE local_start_retries")
        raw.commit()
    finally:
        raw.close()
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    out = capsys.readouterr().out
    assert "local_retries=" not in out
    assert "local_retry" not in out


def _side_line(out: str) -> str:
    lines = [line for line in out.splitlines() if line.startswith("side ")]
    assert len(lines) == 1
    return lines[0]


def test_trace_prints_timeout_retries_on_the_side_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import hashlib as _hashlib

    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    SlotLedger(db).append_step(
        SLOT, "propose_builder", "proposal", 0.1, None, {"timeout_retries": "2"}
    )
    before = _hashlib.sha256(db.read_bytes()).hexdigest()
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert _hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert " timeout_retries=2" in _side_line(capsys.readouterr().out)


def test_trace_sums_timeout_retries_over_two_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    ledger = SlotLedger(db)
    ledger.append_step(
        SLOT, "propose_builder", "proposal", 0.1, None, {"timeout_retries": "1"}
    )
    ledger.append_step(
        SLOT, "propose_builder", "proposal", 0.2, None, {"timeout_retries": "2"}
    )
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert " timeout_retries=3" in _side_line(capsys.readouterr().out)


def test_trace_resumed_row_without_the_key_keeps_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    ledger = SlotLedger(db)
    ledger.append_step(
        SLOT, "propose_builder", "proposal", 0.1, None, {"timeout_retries": "1"}
    )
    ledger.append_step(SLOT, "propose_builder", "proposal", 0.2, None, {"cycle": "c1"})
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert " timeout_retries=1" in _side_line(capsys.readouterr().out)


def test_trace_without_timeout_key_prints_nothing_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    out = capsys.readouterr().out
    assert "timeout_retries" not in out
    assert "side A builder proposal" in _side_line(out)


def test_trace_ignores_other_side_and_other_slot_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only this side's rows at this slot count on its line.

    A `timeout_retries` key on the other side's propose row at this
    slot, and one on this side's row at another slot, stay off this
    side's line.
    """
    from framework.cycle.slot_ledger import SlotLedger
    from framework.cycle.trace import trace

    db = tmp_path / "trace.db"
    ids = _build_db(db)
    ledger = SlotLedger(db)
    ledger.append_step(
        SLOT, "propose_disconnect", "proposal", 0.1, None, {"timeout_retries": "4"}
    )
    other = SLOT + timedelta(hours=2)
    ledger.append_step(
        other, "propose_builder", "proposal", 0.1, None, {"timeout_retries": "3"}
    )
    assert trace(card_id=ids["card_id"], db_path=db) == 0
    assert "timeout_retries" not in _side_line(capsys.readouterr().out)
