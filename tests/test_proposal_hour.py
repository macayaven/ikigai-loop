"""Ticket 11: hour picking, allowed windows, busy intervals, fallback check."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from framework.briefing.context import ProfileLimits, TimeInterval
from framework.proposal.hour import (
    allowed_windows,
    fallback_window_codes,
    future_busy_intervals,
    pick_hour,
)
from framework.schemas.events import (
    CalendarEventCreatedData,
    CalendarEventUpdatedData,
    Event,
)

MADRID = ZoneInfo("Europe/Madrid")


def _limits() -> ProfileLimits:
    from datetime import time

    return ProfileLimits(
        timezone="Europe/Madrid",
        allowed_start=time(13, 0),
        allowed_end=time(23, 30),
        max_actions=3,
    )


def _interval(start_iso: str, end_iso: str) -> TimeInterval:
    return TimeInterval(
        start=datetime.fromisoformat(start_iso), end=datetime.fromisoformat(end_iso)
    )


def _event(
    eid: str,
    etype: str,
    start_iso: str,
    end_iso: str,
    *,
    busy: bool = True,
    collected_iso: str = "2026-10-31T13:00:00+01:00",
    source_id: str | None = None,
    time_iso: str | None = None,
) -> Event:
    data: dict[str, Any] = {
        "start": start_iso,
        "end": end_iso,
        "busy": busy,
        "category": "synthetic",
        "tags": ["iki-review"],
        "is_new": False,
    }
    cls = (
        CalendarEventCreatedData
        if etype == "calendar.event.created"
        else CalendarEventUpdatedData
    )
    return Event(
        id=eid,
        subject_id="subject-1",
        source="synthetic",
        type=etype,  # type: ignore[arg-type]
        time=datetime.fromisoformat(time_iso or start_iso),
        source_id=source_id or f"key-{eid}",
        data=cls.model_validate({**data, "type": etype}),
        tier="public",
        collected_at=datetime.fromisoformat(collected_iso),
        collector_version="synthetic@1",
    )


AS_OF = datetime(2026, 10, 31, 14, 0, 0, tzinfo=MADRID)
SLOT = datetime(2026, 10, 31, 15, 7, 0, tzinfo=MADRID)


def test_base_fixture_picks_next_quarter_hour() -> None:
    hour = pick_hour(SLOT, (), _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T15:15:00+01:00"
    assert hour.end.isoformat() == "2026-10-31T16:15:00+01:00"


def test_block_ending_exactly_at_allowed_end_is_inside() -> None:
    slot = datetime(2026, 10, 31, 22, 20, 0, tzinfo=MADRID)
    hour = pick_hour(slot, (), _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T22:30:00+01:00"
    assert hour.end.isoformat() == "2026-10-31T23:30:00+01:00"


def test_one_minute_overlap_pushes_to_next_quarter() -> None:
    busy = (_interval("2026-10-31T15:15:00+01:00", "2026-10-31T15:16:00+01:00"),)
    hour = pick_hour(SLOT, busy, _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T15:30:00+01:00"


def test_slot_exactly_on_quarter_starts_at_itself() -> None:
    slot = datetime(2026, 10, 31, 15, 15, 0, tzinfo=MADRID)
    hour = pick_hour(slot, (), _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T15:15:00+01:00"


def test_empty_busy_gives_first_quarter_block() -> None:
    slot = datetime(2026, 10, 31, 13, 2, 0, tzinfo=MADRID)
    hour = pick_hour(slot, (), _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T13:15:00+01:00"


def test_seconds_count() -> None:
    slot = datetime(2026, 10, 31, 15, 15, 1, tzinfo=MADRID)
    hour = pick_hour(slot, (), _limits())
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T15:30:00+01:00"


def test_dst_fall_back_block_is_exactly_one_hour_utc() -> None:
    slot = datetime(2026, 10, 25, 12, 7, 0, tzinfo=MADRID)
    hour = pick_hour(slot, (), _limits())
    assert hour is not None
    span = hour.end.astimezone(ZoneInfo("UTC")) - hour.start.astimezone(ZoneInfo("UTC"))
    assert span == timedelta(hours=1)


def test_dst_fall_back_ambiguous_slots_round_in_absolute_time() -> None:
    from datetime import time

    from framework.briefing.context import ProfileLimits

    limits = ProfileLimits(
        timezone="Europe/Madrid",
        allowed_start=time(0, 0),
        allowed_end=time(6, 0),
        max_actions=3,
    )
    for slot_iso in (
        "2026-10-25T02:07:00+02:00",
        "2026-10-25T02:07:00+01:00",
    ):
        slot = datetime.fromisoformat(slot_iso)
        hour = pick_hour(slot, (), limits)
        assert hour is not None, slot_iso
        span = hour.end.astimezone(ZoneInfo("UTC")) - hour.start.astimezone(
            ZoneInfo("UTC")
        )
        assert span == timedelta(hours=1), slot_iso
        wall = hour.start.astimezone(MADRID)
        assert (wall.hour, wall.minute) == (2, 15), slot_iso
        assert wall.utcoffset() == slot.utcoffset(), slot_iso
        assert hour.start.astimezone(ZoneInfo("UTC")) >= slot.astimezone(
            ZoneInfo("UTC")
        ), slot_iso


def test_full_day_returns_none_instead_of_tomorrow() -> None:
    busy = (_interval("2026-10-31T13:00:00+01:00", "2026-10-31T23:30:00+01:00"),)
    assert pick_hour(SLOT, busy, _limits()) is None


def test_allowed_windows_is_the_local_day_in_utc() -> None:
    (window,) = allowed_windows(SLOT, _limits())
    assert window.start.isoformat() == "2026-10-31T12:00:00+00:00"
    assert window.end.isoformat() == "2026-10-31T22:30:00+00:00"


def _busy_events() -> list[Event]:
    return [
        _event(
            "e1",
            "calendar.event.created",
            "2026-10-31T15:00:00+01:00",
            "2026-10-31T16:00:00+01:00",
        ),
    ]


def test_future_busy_moved_out_of_window_unblocks() -> None:
    old = _event(
        "e1",
        "calendar.event.created",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T16:00:00+01:00",
        collected_iso="2026-10-31T10:00:00+01:00",
        source_id="same-key",
    )
    new = _event(
        "e2",
        "calendar.event.updated",
        "2026-11-05T15:00:00+01:00",
        "2026-11-05T16:00:00+01:00",
        collected_iso="2026-10-31T13:00:00+01:00",
        source_id="same-key",
        time_iso="2026-11-05T15:00:00+01:00",
    )
    found = future_busy_intervals([old, new], as_of=AS_OF, slot=SLOT)
    assert found == ()


def test_future_busy_moved_into_window_blocks() -> None:
    old = _event(
        "e1",
        "calendar.event.created",
        "2026-11-05T15:00:00+01:00",
        "2026-11-05T16:00:00+01:00",
        collected_iso="2026-10-31T10:00:00+01:00",
        source_id="same-key",
        time_iso="2026-11-05T15:00:00+01:00",
    )
    new = _event(
        "e2",
        "calendar.event.updated",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T16:00:00+01:00",
        collected_iso="2026-10-31T13:00:00+01:00",
        source_id="same-key",
    )
    (found,) = future_busy_intervals([old, new], as_of=AS_OF, slot=SLOT)
    assert found.start.isoformat() == "2026-10-31T15:00:00+01:00"


def test_future_busy_cancelled_and_updated_count_once() -> None:
    live = _event(
        "e1",
        "calendar.event.created",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T16:00:00+01:00",
        collected_iso="2026-10-31T10:00:00+01:00",
        source_id="same-key",
    )
    updated = _event(
        "e2",
        "calendar.event.updated",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T16:00:00+01:00",
        collected_iso="2026-10-31T12:00:00+01:00",
        source_id="same-key",
    )
    cancelled = _event(
        "e3",
        "calendar.event.created",
        "2026-10-31T17:00:00+01:00",
        "2026-10-31T18:00:00+01:00",
        collected_iso="2026-10-31T12:00:00+01:00",
        source_id="cancelled-key",
        busy=False,
    )
    found = future_busy_intervals([live, updated, cancelled], as_of=AS_OF, slot=SLOT)
    assert len(found) == 1
    assert found[0].start.isoformat() == "2026-10-31T15:00:00+01:00"


def test_future_busy_collected_after_as_of_ignored() -> None:
    late = _event(
        "e9",
        "calendar.event.created",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T16:00:00+01:00",
        collected_iso="2026-10-31T15:00:00+01:00",
    )
    assert future_busy_intervals([late], as_of=AS_OF, slot=SLOT) == ()


def test_future_busy_zero_length_dropped() -> None:
    point = _event(
        "e9",
        "calendar.event.created",
        "2026-10-31T15:00:00+01:00",
        "2026-10-31T15:00:00+01:00",
    )
    assert future_busy_intervals([point], as_of=AS_OF, slot=SLOT) == ()


def test_future_busy_running_since_before_as_of_kept() -> None:
    running = _event(
        "e9",
        "calendar.event.created",
        "2026-10-31T13:30:00+01:00",
        "2026-10-31T15:30:00+01:00",
        time_iso="2026-10-31T13:30:00+01:00",
    )
    (found,) = future_busy_intervals([running], as_of=AS_OF, slot=SLOT)
    assert found.start.isoformat() == "2026-10-31T13:30:00+01:00"


def test_future_busy_ending_exactly_at_as_of_dropped() -> None:
    ended = _event(
        "e9",
        "calendar.event.created",
        "2026-10-31T13:00:00+01:00",
        "2026-10-31T14:00:00+01:00",
        time_iso="2026-10-31T13:00:00+01:00",
    )
    assert future_busy_intervals([ended], as_of=AS_OF, slot=SLOT) == ()


def test_fallback_window_codes_clean_and_foreign() -> None:
    limits = _limits()
    hour = pick_hour(SLOT, (), limits)
    assert hour is not None
    assert (
        fallback_window_codes(slot=SLOT, start=hour.start, end=hour.end, limits=limits)
        == ()
    )
    foreign = fallback_window_codes(
        slot=SLOT,
        start=datetime.fromisoformat("2026-10-31T09:00:00+01:00"),
        end=datetime.fromisoformat("2026-10-31T10:00:00+01:00"),
        limits=limits,
    )
    assert "L1_ACTION_BEFORE_SLOT" in foreign
