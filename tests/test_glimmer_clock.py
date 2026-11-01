"""Ticket 9e Slice A: floor, union, per-calendar, and move-drop regressions.

Synthetic data only, no network. Slice A covers framework/glimmer/metrics.py
only (D1 bounds, D3 unions, D4 steps 2/2a/3 in select_winners/_logical_key).
Facts, checks, cycle loading, and collectors are other slices.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from evals.glimmer_cases import (
    PLUS1,
    SUBJECT_ID,
    RecordingLLM,
    _dt,
    cal_event,
    feed_batch,
    feed_event,
    make_event,
    personal_aliases,
    personal_batch,
    pr_event,
    push_event,
    screen_event,
)
from framework.briefing.context import MetricSnapshot
from framework.briefing.gate import evaluate_briefing
from framework.cycle import run_cycle
from framework.glimmer.facts import extract_facts
from framework.glimmer.metrics import (
    build_metric_snapshot,
    build_period_rollup,
    select_winners,
)
from framework.schemas.events import CalendarEventData, Event
from framework.store.fact_store import FactStore
from framework.store.store import EventStore


def _start_hour(event: Event) -> int:
    assert isinstance(event.data, CalendarEventData)
    return event.data.start.hour


SLOT_AS_OFS = ["13:30", "15:30", "18:00", "20:30", "22:30"]
TICKET13_AS_OFS = ["13:05", "15:05", "17:35", "20:05", "22:05"]


def _cal(
    source: str,
    eid: str,
    uid: str,
    rid: str,
    start: datetime,
    end: datetime,
    *,
    stamp: str,
    collected: datetime,
    kind: str = "created",
    cancelled: bool = False,
    tags: tuple[str, ...] = ("iki-family",),
    busy: bool = True,
) -> Any:
    etype = "calendar.event.cancelled" if cancelled else f"calendar.event.{kind}"
    return make_event(
        eid=eid,
        source=source,
        source_id=f"{uid}@{rid}@{stamp}" + ("#cancelled" if cancelled else ""),
        type=etype,
        time=start,
        data={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "busy": busy,
            "category": source.removeprefix("calendar-"),
            "tags": list(tags),
            "is_new": False,
        },
        tier="private",
        collected_at=collected,
    )


@pytest.mark.parametrize("hhmm", SLOT_AS_OFS + TICKET13_AS_OFS)
def test_half_hour_cut_invents_no_change(hhmm: str) -> None:
    from framework.glimmer.metrics import floor_hour, period_bounds

    hour, minute = (int(v) for v in hhmm.split(":"))
    as_of = datetime(2026, 11, 2, hour, minute, tzinfo=PLUS1)
    expected_end = as_of.replace(minute=0, second=0, microsecond=0)
    assert floor_hour(as_of) == expected_end
    bounds = period_bounds(as_of)
    assert bounds[-1][2] == expected_end
    assert bounds[-1][1] == expected_end - timedelta(hours=24)
    bucket_time = expected_end - timedelta(days=1)
    row = screen_event(
        eid=f"evt_half_hour_{hhmm.replace(':', '')}",
        time=bucket_time,
        minutes={"code": 60.0},
        collected_at=bucket_time + timedelta(hours=1),
    )
    rollup = build_period_rollup(as_of, [row])
    assert rollup["last"]["screen_hours"] == {"code": 1.0}
    assert rollup["prior"]["screen_hours"].get("code", 0.0) == 0.0
    snapshot = build_metric_snapshot(as_of, [row])
    assert snapshot.values["period.last.screen_hours.code"] == 1.0


def test_floor_madrid_fall_back() -> None:
    from framework.glimmer.metrics import _period_name_for, floor_hour, period_bounds

    madrid = ZoneInfo("Europe/Madrid")
    as_of = datetime(2026, 10, 25, 2, 30, tzinfo=madrid, fold=1)
    end = floor_hour(as_of)
    assert end.utcoffset() == timedelta(hours=1)
    assert (end.hour, end.minute) == (2, 0)
    bounds = period_bounds(as_of)
    for _, start, stop in bounds:
        assert stop.astimezone(UTC) - start.astimezone(UTC) == timedelta(hours=24)
    first = screen_event(
        eid="evt_fallback_first",
        time=datetime(2026, 10, 25, 2, 0, tzinfo=madrid, fold=0),
        minutes={"code": 60.0},
    )
    second = screen_event(
        eid="evt_fallback_second",
        time=datetime(2026, 10, 25, 2, 0, tzinfo=madrid, fold=1),
        minutes={"code": 60.0},
    )
    assert first.time.astimezone(UTC) != second.time.astimezone(UTC)
    assert _period_name_for(first.time, bounds) != _period_name_for(second.time, bounds)


def test_floor_hour_half_hour_offset_lands_on_utc_hour() -> None:
    from framework.glimmer.metrics import floor_hour

    tz = timezone(timedelta(hours=5, minutes=30))
    as_of = datetime(2026, 10, 31, 13, 35, tzinfo=tz)
    floored = floor_hour(as_of)
    assert floored.astimezone(UTC).minute == 0
    assert floored.minute == 30
    bucket_time = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
    row = screen_event(
        eid="evt_half_offset_bucket",
        time=bucket_time,
        minutes={"code": 60.0},
        collected_at=bucket_time + timedelta(hours=1),
    )
    rollup = build_period_rollup(as_of, [row])
    assert rollup["last"]["screen_hours"] == {"code": 1.0}
    assert rollup["prior"]["screen_hours"].get("code", 0.0) == 0.0


def test_overlapping_blocks_union() -> None:
    as_of = _dt(31, 13)
    first = cal_event(
        eid="evt_union_a",
        key="ov-a@20261030T160000",
        lm="seq1",
        time=_dt(30, 16),
        end=_dt(30, 17),
        tags=("iki-focus",),
        collected_at=_dt(30, 17),
    )
    second = cal_event(
        eid="evt_union_b",
        key="ov-b@20261030T160000",
        lm="seq1",
        time=_dt(30, 16),
        end=_dt(30, 17),
        tags=("iki-focus",),
        collected_at=_dt(30, 17),
    )
    snapshot = build_metric_snapshot(as_of, select_winners([first, second]))
    assert snapshot.values["calendar.busy_hours"] == 1.0
    assert snapshot.values["tag_hours.iki-focus"] == 1.0
    assert snapshot.values["period.last.tag_hours.iki-focus"] == 1.0
    left = cal_event(
        eid="evt_union_c",
        key="ov-c@20261030T180000",
        lm="seq1",
        time=_dt(30, 18),
        end=_dt(30, 19),
        tags=("iki-a",),
        collected_at=_dt(30, 19),
    )
    right = cal_event(
        eid="evt_union_d",
        key="ov-d@20261030T180000",
        lm="seq1",
        time=_dt(30, 18),
        end=_dt(30, 19),
        tags=("iki-b",),
        collected_at=_dt(30, 19),
    )
    mixed = build_metric_snapshot(as_of, select_winners([left, right]))
    assert mixed.values["calendar.busy_hours"] == 1.0
    assert mixed.values["tag_hours.iki-a"] == 1.0
    assert mixed.values["tag_hours.iki-b"] == 1.0


def test_cancellation_is_per_calendar() -> None:
    as_of = _dt(31, 13)
    personal = _cal(
        "calendar-personal",
        "evt_percal_p_active",
        "invite-7",
        "20261030T090000",
        _dt(30, 9),
        _dt(30, 10),
        stamp="seq1",
        collected=_dt(30, 10),
        tags=("iki-a",),
    )
    work = _cal(
        "calendar-work",
        "evt_percal_w_active",
        "invite-7",
        "20261030T090000",
        _dt(30, 9),
        _dt(30, 10),
        stamp="seq1",
        collected=_dt(30, 11),
        tags=("iki-b",),
    )
    both = build_metric_snapshot(as_of, select_winners([personal, work]))
    assert both.values["calendar.busy_hours"] == 1.0
    assert both.values["tag_hours.iki-a"] == 1.0
    assert both.values["tag_hours.iki-b"] == 1.0
    personal_gone = _cal(
        "calendar-personal",
        "evt_percal_p_cancelled",
        "invite-7",
        "20261030T090000",
        _dt(30, 9),
        _dt(30, 10),
        stamp="seq2",
        collected=_dt(30, 12),
        cancelled=True,
        tags=("iki-a",),
    )
    one_left = select_winners([personal, work, personal_gone])
    assert not [e for e in one_left if e.type == "calendar.event.cancelled"]
    snapshot = build_metric_snapshot(as_of, one_left)
    assert snapshot.values["calendar.busy_hours"] == 1.0
    assert snapshot.values["tag_hours.iki-b"] == 1.0
    work_gone = _cal(
        "calendar-work",
        "evt_percal_w_cancelled",
        "invite-7",
        "20261030T090000",
        _dt(30, 9),
        _dt(30, 10),
        stamp="seq2",
        collected=_dt(30, 13),
        cancelled=True,
        tags=("iki-b",),
    )
    none_left = select_winners([personal, work, personal_gone, work_gone])
    cancelled = [e for e in none_left if e.type == "calendar.event.cancelled"]
    assert len(cancelled) == 1
    rollup = build_period_rollup(as_of, none_left)
    total = sum(
        rollup[name]["cancelled_blocks_by_tag"].get(tag, 0)
        for name in ("earlier", "prior", "last")
        for tag in ("iki-a", "iki-b")
    )
    assert total == 1


def _moved_fixture() -> tuple[Any, Any, Any, datetime]:
    as_of = _dt(1, 22)
    created_old = _cal(
        "calendar-personal",
        "evt_move_created_old",
        "move-1",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq1",
        collected=_dt(1, 18),
    )
    cancelled_old = _cal(
        "calendar-personal",
        "evt_move_cancelled_old",
        "move-1",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq2",
        collected=_dt(1, 20, 30),
        cancelled=True,
    )
    created_new = _cal(
        "calendar-personal",
        "evt_move_created_new",
        "move-1",
        "20261101T200000",
        _dt(1, 20),
        _dt(1, 21),
        stamp="seq2",
        collected=_dt(1, 20, 30),
    )
    return created_old, cancelled_old, created_new, as_of


def test_moved_block_is_not_cancelled() -> None:
    created_old, cancelled_old, created_new, as_of = _moved_fixture()
    winners = select_winners([created_old, cancelled_old, created_new])
    assert not [e for e in winners if e.type == "calendar.event.cancelled"]
    snapshot = build_metric_snapshot(as_of, winners)
    assert snapshot.values["calendar.busy_hours"] == 1.0
    assert snapshot.values["tag_hours.iki-family"] == 1.0
    rollup = build_period_rollup(as_of, winners)
    assert rollup["last"]["calendar_hours_by_tag"] == {"iki-family": 1.0}
    assert rollup["last"]["cancelled_blocks_by_tag"] == {}


def test_moved_block_stamp_bump_keeps_move_suppression() -> None:
    created_old, cancelled_old, created_new, as_of = _moved_fixture()
    bumped_new = _cal(
        "calendar-personal",
        "evt_move_bumped_new",
        "move-1",
        "20261101T200000",
        _dt(1, 20),
        _dt(1, 21),
        stamp="seq3",
        collected=_dt(1, 21),
        kind="updated",
    )
    winners = select_winners([created_old, cancelled_old, created_new, bumped_new])
    assert not [e for e in winners if e.type == "calendar.event.cancelled"]
    snapshot = build_metric_snapshot(as_of, winners)
    assert snapshot.values["calendar.busy_hours"] == 1.0
    rollup = build_period_rollup(as_of, winners)
    assert rollup["last"]["cancelled_blocks_by_tag"] == {}


def test_moved_block_there_and_back_active() -> None:
    created_old, cancelled_old, created_new, _ = _moved_fixture()
    as_of = _dt(1, 23)
    cancelled_new = _cal(
        "calendar-personal",
        "evt_moveback_cancelled_new",
        "move-1",
        "20261101T200000",
        _dt(1, 20),
        _dt(1, 21),
        stamp="seq3",
        collected=_dt(1, 21, 30),
        cancelled=True,
    )
    restored_old = _cal(
        "calendar-personal",
        "evt_moveback_restored_old",
        "move-1",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq3",
        collected=_dt(1, 21, 30),
    )
    rows = [created_old, cancelled_old, created_new, cancelled_new, restored_old]
    winners = select_winners(rows)
    assert not [e for e in winners if e.type == "calendar.event.cancelled"]
    active = [e for e in winners if e.type != "calendar.event.cancelled"]
    assert {_start_hour(e) for e in active} == {19}
    snapshot = build_metric_snapshot(as_of, winners)
    assert snapshot.values["calendar.busy_hours"] == 1.0


def test_moved_block_then_delete_one_cancelled() -> None:
    created_old, cancelled_old, created_new, as_of = _moved_fixture()
    deleted_new = _cal(
        "calendar-personal",
        "evt_movedelete_cancelled_new",
        "move-1",
        "20261101T200000",
        _dt(1, 20),
        _dt(1, 21),
        stamp="seq3",
        collected=_dt(1, 21, 30),
        cancelled=True,
    )
    rows = [created_old, cancelled_old, created_new, deleted_new]
    winners = select_winners(rows)
    cancelled = [e for e in winners if e.type == "calendar.event.cancelled"]
    assert len(cancelled) == 1
    assert _start_hour(cancelled[0]) == 20
    rollup = build_period_rollup(as_of, winners)
    assert rollup["last"]["cancelled_blocks_by_tag"] == {"iki-family": 1}
    snapshot = build_metric_snapshot(as_of, winners)
    assert snapshot.values["calendar.busy_hours"] == 0.0


def test_recurring_instance_removed_alone_still_cancels() -> None:
    as_of = _dt(2, 12)
    created_a = _cal(
        "calendar-personal",
        "evt_series_a_created",
        "series-9",
        "20261101T090000",
        _dt(1, 9),
        _dt(1, 10),
        stamp="seq1",
        collected=_dt(1, 8),
    )
    created_b = _cal(
        "calendar-personal",
        "evt_series_b_created",
        "series-9",
        "20261102T090000",
        _dt(2, 9),
        _dt(2, 10),
        stamp="seq1",
        collected=_dt(1, 8),
    )
    removed_a = _cal(
        "calendar-personal",
        "evt_series_a_removed",
        "series-9",
        "20261101T090000",
        _dt(1, 9),
        _dt(1, 10),
        stamp="seq2",
        collected=_dt(1, 20),
        cancelled=True,
    )
    winners = select_winners([created_a, created_b, removed_a])
    cancelled = [e for e in winners if e.type == "calendar.event.cancelled"]
    assert len(cancelled) == 1
    rollup = build_period_rollup(as_of, winners)
    total = sum(
        rollup[name]["cancelled_blocks_by_tag"].get("iki-family", 0)
        for name in ("earlier", "prior", "last")
    )
    assert total == 1


def test_recurring_instance_removed_with_master_stamp_bump_still_cancels() -> None:
    as_of = _dt(3, 12)
    created_a = _cal(
        "calendar-personal",
        "evt_bump_a_created",
        "series-9",
        "20261101T090000",
        _dt(1, 9),
        _dt(1, 10),
        stamp="seq1",
        collected=_dt(1, 8),
    )
    created_b = _cal(
        "calendar-personal",
        "evt_bump_b_created",
        "series-9",
        "20261102T090000",
        _dt(2, 9),
        _dt(2, 10),
        stamp="seq1",
        collected=_dt(1, 8),
    )
    created_c = _cal(
        "calendar-personal",
        "evt_bump_c_created",
        "series-9",
        "20261103T090000",
        _dt(3, 9),
        _dt(3, 10),
        stamp="seq1",
        collected=_dt(1, 8),
    )
    removed_a = _cal(
        "calendar-personal",
        "evt_bump_a_removed",
        "series-9",
        "20261101T090000",
        _dt(1, 9),
        _dt(1, 10),
        stamp="seq2",
        collected=_dt(2, 8),
        cancelled=True,
    )
    bumped_b = _cal(
        "calendar-personal",
        "evt_bump_b_updated",
        "series-9",
        "20261102T090000",
        _dt(2, 9),
        _dt(2, 10),
        stamp="seq2",
        collected=_dt(2, 8),
        kind="updated",
    )
    bumped_c = _cal(
        "calendar-personal",
        "evt_bump_c_updated",
        "series-9",
        "20261103T090000",
        _dt(3, 9),
        _dt(3, 10),
        stamp="seq2",
        collected=_dt(2, 8),
        kind="updated",
    )
    rows = [created_a, created_b, created_c, removed_a, bumped_b, bumped_c]
    winners = select_winners(rows)
    cancelled = [e for e in winners if e.type == "calendar.event.cancelled"]
    assert len(cancelled) == 1
    rollup = build_period_rollup(as_of, winners)
    total = sum(
        rollup[name]["cancelled_blocks_by_tag"].get("iki-family", 0)
        for name in ("earlier", "prior", "last")
    )
    assert total == 1


def test_moved_block_second_calendar_not_yet_polled() -> None:
    as_of = _dt(1, 22)
    personal_old = _cal(
        "calendar-personal",
        "evt_twocal_p_old",
        "move-2",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq1",
        collected=_dt(1, 18),
    )
    personal_gone = _cal(
        "calendar-personal",
        "evt_twocal_p_gone",
        "move-2",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq2",
        collected=_dt(1, 20, 30),
        cancelled=True,
    )
    personal_new = _cal(
        "calendar-personal",
        "evt_twocal_p_new",
        "move-2",
        "20261101T200000",
        _dt(1, 20),
        _dt(1, 21),
        stamp="seq2",
        collected=_dt(1, 20, 30),
    )
    work_old = _cal(
        "calendar-work",
        "evt_twocal_w_old",
        "move-2",
        "20261101T190000",
        _dt(1, 19),
        _dt(1, 20),
        stamp="seq1",
        collected=_dt(1, 18),
    )
    winners = select_winners([personal_old, personal_gone, personal_new, work_old])
    assert not [e for e in winners if e.type == "calendar.event.cancelled"]
    snapshot = build_metric_snapshot(as_of, winners)
    assert snapshot.values["calendar.busy_hours"] == 2.0


HALF_AS_OF = datetime(2026, 11, 2, 13, 30, tzinfo=PLUS1)


def _nov(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=PLUS1)


def _code_dropped(result: object, code: str) -> bool:
    return any(d.code == code for d in result.dropped)  # type: ignore[union-attr]


def test_open_hour_push_blocks_false_zero() -> None:
    prior_push = push_event(eid="evt_oh_prior", time=_nov(1, 10))
    open_push = push_event(eid="evt_oh_open", time=_nov(2, 13, 27))
    events = [prior_push, open_push]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Pushes were 0 in last",
                    "evidence": [aliases[prior_push.id]],
                },
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(HALF_AS_OF, SUBJECT_ID, events, llm)
    statements = [f.statement for f in result.facts]
    assert "Pushes fell from 1 in prior to 0 in last." not in statements
    assert _code_dropped(result, "FACT_OPEN_HOUR_ZERO")
    assert _code_dropped(result, "CODE_FACT_OPEN_HOUR_ZERO")


def test_open_hour_push_whole_hour_twin_passes_as_today() -> None:
    whole = datetime(2026, 11, 2, 13, 0, tzinfo=PLUS1)
    prior_push = push_event(eid="evt_ohw_prior", time=_nov(1, 10))
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(whole, SUBJECT_ID, [prior_push], llm)
    assert [f.statement for f in result.facts] == [
        "Pushes fell from 1 in prior to 0 in last."
    ]
    assert result.dropped == ()


def test_open_hour_screen_blocks_false_zero() -> None:
    prior = screen_event(eid="evt_ohs_prior", time=_nov(1, 10), minutes={"code": 60.0})
    open_bucket = screen_event(
        eid="evt_ohs_open", time=_nov(2, 13), minutes={"code": 60.0}
    )
    events = [prior, open_bucket]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Code screen hours fell from 1 in prior to 0 in last",
                    "evidence": [aliases[prior.id]],
                },
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(HALF_AS_OF, SUBJECT_ID, events, llm)
    statements = [f.statement for f in result.facts]
    assert "Code screen hours fell from 1 in prior to 0 in last." not in statements
    assert _code_dropped(result, "FACT_OPEN_HOUR_ZERO")
    assert _code_dropped(result, "CODE_FACT_OPEN_HOUR_ZERO")


def test_open_hour_calendar_blocks_false_zero() -> None:
    prior = cal_event(
        eid="evt_ohc_prior",
        key="ohc-a@20261101T100000",
        lm="seq1",
        time=_nov(1, 10),
        end=_nov(1, 11),
        tags=("iki-focus",),
        collected_at=_nov(1, 12),
    )
    overlapping = cal_event(
        eid="evt_ohc_open",
        key="ohc-b@20261102T130000",
        lm="seq1",
        time=_nov(2, 13),
        end=_nov(2, 14),
        tags=("iki-focus",),
        collected_at=_nov(2, 13, 28),
    )
    events = [prior, overlapping]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "iki-focus calendar hours fell from 1 in prior to 0 in last",
                    "evidence": [aliases[prior.id]],
                },
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(HALF_AS_OF, SUBJECT_ID, events, llm)
    statements = [f.statement for f in result.facts]
    assert (
        "iki-focus calendar hours fell from 1 in prior to 0 in last." not in statements
    )
    assert _code_dropped(result, "FACT_OPEN_HOUR_ZERO")
    assert _code_dropped(result, "CODE_FACT_OPEN_HOUR_ZERO")


def test_open_hour_cancelled_blocks_false_zero() -> None:
    prior = cal_event(
        eid="evt_ohx_prior",
        key="ohx-a@20261101T100000",
        lm="seq1",
        time=_nov(1, 10),
        end=_nov(1, 10, 30),
        tags=("iki-x",),
        cancelled=True,
        collected_at=_nov(1, 12),
    )
    open_row = cal_event(
        eid="evt_ohx_open",
        key="ohx-b@20261102T131000",
        lm="seq1",
        time=_nov(2, 13, 10),
        end=_nov(2, 13, 20),
        tags=("iki-x",),
        cancelled=True,
        collected_at=_nov(2, 13, 28),
    )
    events = [prior, open_row]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Cancelled iki-x blocks fell from 1 in prior to 0 in last",
                    "evidence": [aliases[prior.id]],
                },
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(HALF_AS_OF, SUBJECT_ID, events, llm)
    statements = [f.statement for f in result.facts]
    assert "Cancelled iki-x blocks fell from 1 in prior to 0 in last." not in statements
    assert _code_dropped(result, "FACT_OPEN_HOUR_ZERO")
    assert _code_dropped(result, "CODE_FACT_OPEN_HOUR_ZERO")


def _gate_claim(briefing: dict, text: str, metric_id: str, value: float) -> None:
    section = next(s for s in briefing["sections"] if s["type"] == "working")
    claim = section["claims"][0]
    claim["text"] = text
    claim["metric_refs"] = [{"metric_id": metric_id, "value": value}]
    claim["fact_ids"] = []


def test_open_hour_zero_omitted_from_snapshot_and_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import copy

    from evals.briefing_cases import base_case as briefing_base_case

    prior_push = push_event(eid="evt_ohg_prior", time=_nov(1, 10))
    open_push = push_event(eid="evt_ohg_open", time=_nov(2, 13, 27))
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(HALF_AS_OF, SUBJECT_ID, [prior_push, open_push], llm)
    assert "period.last.pushes" not in result.snapshot.values

    case = briefing_base_case("builder")
    briefing = copy.deepcopy(case.briefing)
    context = case.context.model_copy(
        update={"metrics": MetricSnapshot(values=dict(result.snapshot.values))}
    )
    _gate_claim(
        briefing, "Pushes stalled in the last period", "period.last.pushes", 0.0
    )
    violations = [v.code for v in evaluate_briefing(briefing, context).violations]
    assert "L1B_UNKNOWN_METRIC" in violations


def test_open_hour_zero_whole_hour_twin_passes_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import copy

    from evals.briefing_cases import base_case as briefing_base_case

    whole = datetime(2026, 11, 2, 13, 0, tzinfo=PLUS1)
    prior_push = push_event(eid="evt_ohgw_prior", time=_nov(1, 10))
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(whole, SUBJECT_ID, [prior_push], llm)
    assert result.snapshot.values["period.last.pushes"] == 0.0

    case = briefing_base_case("builder")
    briefing = copy.deepcopy(case.briefing)
    context = case.context.model_copy(
        update={"metrics": MetricSnapshot(values=dict(result.snapshot.values))}
    )
    _gate_claim(
        briefing, "Pushes stalled in the last period", "period.last.pushes", 0.0
    )
    gate_result = evaluate_briefing(briefing, context)
    assert "L1B_UNKNOWN_METRIC" not in [v.code for v in gate_result.violations]
    assert gate_result.passed is True


def test_open_hour_nonzero_last_stays_in_snapshot() -> None:
    prior_push = push_event(eid="evt_ohn_prior", time=_nov(1, 10))
    last_push = push_event(eid="evt_ohn_last", time=_nov(2, 12))
    open_push = push_event(eid="evt_ohn_open", time=_nov(2, 13, 27))
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(
        HALF_AS_OF, SUBJECT_ID, [prior_push, last_push, open_push], llm
    )
    assert result.snapshot.values["period.last.pushes"] == 1.0


def _seeded(tmp_path, events):  # type: ignore[no-untyped-def]
    store = EventStore(db_path=tmp_path / "events.db")
    fact_store = FactStore(db_path=tmp_path / "facts.db")
    try:
        assert store.append_events(events) == len(events)
        return store, fact_store
    except BaseException:
        store.close()
        fact_store.close()
        raise


def test_revision_moved_out_wins(tmp_path) -> None:  # type: ignore[no-untyped-def]
    old = make_event(
        eid="evt_rev_old",
        source="calendar-personal",
        source_id="mv-1@20261101T140000@seq1",
        type="calendar.event.created",
        time=_nov(1, 14),
        data={
            "start": _nov(1, 14).isoformat(),
            "end": _nov(1, 15).isoformat(),
            "busy": True,
            "category": "personal",
            "tags": ["iki-focus"],
            "is_new": False,
        },
        collected_at=_nov(1, 16),
    )
    old_gone = make_event(
        eid="evt_rev_gone",
        source="calendar-personal",
        source_id="mv-1@20261101T140000@seq1#cancelled",
        type="calendar.event.cancelled",
        time=_nov(1, 14),
        data={
            "start": _nov(1, 14).isoformat(),
            "end": _nov(1, 15).isoformat(),
            "busy": True,
            "category": "personal",
            "tags": ["iki-focus"],
            "is_new": False,
        },
        collected_at=_nov(2, 10),
    )
    new = make_event(
        eid="evt_rev_new",
        source="calendar-personal",
        source_id="mv-1@20261103T100000@seq2",
        type="calendar.event.created",
        time=_nov(3, 10),
        data={
            "start": _nov(3, 10).isoformat(),
            "end": _nov(3, 11).isoformat(),
            "busy": True,
            "category": "personal",
            "tags": ["iki-focus"],
            "is_new": False,
        },
        collected_at=_nov(2, 10),
    )
    store, fact_store = _seeded(tmp_path, [old, old_gone, new])
    try:
        result, _ = run_cycle(
            HALF_AS_OF,
            SUBJECT_ID,
            store,
            fact_store,
            RecordingLLM(),
            personal_pass=False,
            feed_pass=False,
        )
    finally:
        store.close()
        fact_store.close()
    assert not [k for k in result.snapshot.values if "iki-focus" in k]
    assert not [
        f.statement for f in result.facts if "fell from 1 in prior" in f.statement
    ]
    assert result.is_noop is True


def test_block_crossing_window_start_counts_clipped(tmp_path) -> None:  # type: ignore[no-untyped-def]
    as_of = datetime(2026, 11, 1, 13, 0, tzinfo=PLUS1)
    crosser = make_event(
        eid="evt_cross_a",
        source="calendar-personal",
        source_id="cross-a@20261029T120000@seq1",
        type="calendar.event.created",
        time=datetime(2026, 10, 29, 12, 0, tzinfo=PLUS1),
        data={
            "start": datetime(2026, 10, 29, 12, 0, tzinfo=PLUS1).isoformat(),
            "end": datetime(2026, 10, 29, 14, 0, tzinfo=PLUS1).isoformat(),
            "busy": True,
            "category": "personal",
            "tags": [],
            "is_new": False,
        },
        collected_at=datetime(2026, 10, 29, 15, 0, tzinfo=PLUS1),
    )
    crosser_label = make_event(
        eid="evt_cross_a_label",
        source="calendar-personal",
        source_id="label-cross-a",
        type="calendar.label",
        time=datetime(2026, 10, 29, 12, 0, tzinfo=PLUS1),
        data={
            "target_event_id": "evt_cross_a",
            "label": "iki-deep",
            "model_id": "mock-model",
            "valid": True,
        },
        collected_at=datetime(2026, 10, 29, 15, 30, tzinfo=PLUS1),
    )
    middle = cal_event(
        eid="evt_cross_b",
        key="cross-b@20261030T140000",
        lm="seq1",
        time=datetime(2026, 10, 30, 14, 0, tzinfo=PLUS1),
        end=datetime(2026, 10, 30, 16, 0, tzinfo=PLUS1),
        tags=("iki-deep",),
        collected_at=datetime(2026, 10, 30, 17, 0, tzinfo=PLUS1),
    )
    late = cal_event(
        eid="evt_cross_c",
        key="cross-c@20261031T140000",
        lm="seq1",
        time=datetime(2026, 10, 31, 14, 0, tzinfo=PLUS1),
        end=datetime(2026, 10, 31, 16, 0, tzinfo=PLUS1),
        tags=("iki-deep",),
        collected_at=datetime(2026, 10, 31, 17, 0, tzinfo=PLUS1),
    )
    store, fact_store = _seeded(tmp_path, [crosser, crosser_label, middle, late])
    try:
        result, _ = run_cycle(
            as_of,
            SUBJECT_ID,
            store,
            fact_store,
            RecordingLLM(),
            personal_pass=False,
            feed_pass=False,
        )
    finally:
        store.close()
        fact_store.close()
    assert result.snapshot.values["calendar.busy_hours"] == 5.0
    assert result.snapshot.values["period.earlier.tag_hours.iki-deep"] == 1.0
    assert result.snapshot.values["period.prior.tag_hours.iki-deep"] == 2.0
    assert result.snapshot.values["period.last.tag_hours.iki-deep"] == 2.0
    assert "iki-deep calendar hours rose from 1 in earlier to 2 in prior." in [
        f.statement for f in result.facts
    ]


def test_snapshot_totals_stop_at_the_floor() -> None:
    # Derived by hand: as_of 13:30 floors to 13:00, so the window is
    # half-open below 13:00. Only the 12:10 push counts; the 13:10 push,
    # the 13:10 PR, the 13:00 screen bucket, and the 13:10 feed item all
    # fall in [13:00, 13:30) and count in no total. feed.item.count stays
    # present at 0.0 while the other untouched families stay absent.
    as_of = datetime(2026, 10, 31, 13, 30, tzinfo=PLUS1)
    before = push_event(
        eid="evt_floor_before",
        time=datetime(2026, 10, 31, 12, 10, tzinfo=PLUS1),
    )
    open_push = push_event(
        eid="evt_floor_open_push",
        time=datetime(2026, 10, 31, 13, 10, tzinfo=PLUS1),
    )
    open_pr = pr_event(
        eid="evt_floor_open_pr",
        time=datetime(2026, 10, 31, 13, 10, tzinfo=PLUS1),
    )
    open_screen = screen_event(
        eid="evt_floor_open_screen",
        time=datetime(2026, 10, 31, 13, 0, tzinfo=PLUS1),
        minutes={"code": 60.0},
    )
    open_feed = feed_event(
        eid="evt_floor_open_feed",
        item="item-floor-open",
        day="2026-10-31",
        time=datetime(2026, 10, 31, 13, 10, tzinfo=PLUS1),
        title="Synthetic floor guard feed item",
    )
    snapshot = build_metric_snapshot(
        as_of, [before, open_push, open_pr, open_screen, open_feed]
    )
    assert snapshot.values["github.push.count"] == 1.0
    assert "github.pr.count" not in snapshot.values
    assert "screen_hours.code" not in snapshot.values
    assert snapshot.values["feed.item.count"] == 0.0
