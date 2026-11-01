"""Ticket 11: the free hour, the busy list, and the fallback window check.

Pure: every instant comes from the arguments. The hour is picked once per
slot and shared by both profiles.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from framework.briefing.context import ProfileLimits, TimeInterval
from framework.briefing.gate import action_window_codes, slot_window_codes
from framework.glimmer.metrics import fixed_offset, select_winners
from framework.schemas.events import (
    CalendarEventCancelledData,
    CalendarEventCreatedData,
    CalendarEventUpdatedData,
    Event,
)

_QUARTER = timedelta(minutes=15)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)
_BUSY_WINDOW = timedelta(days=31)
_CYCLE_WINDOW = timedelta(hours=72)


def allowed_windows(slot: datetime, limits: ProfileLimits) -> tuple[TimeInterval, ...]:
    """The slot's local day window as UTC intervals for the gate."""
    zone = ZoneInfo(limits.timezone)
    local = slot.astimezone(zone)
    start = datetime(
        local.year,
        local.month,
        local.day,
        limits.allowed_start.hour,
        limits.allowed_start.minute,
        tzinfo=zone,
    )
    end = datetime(
        local.year,
        local.month,
        local.day,
        limits.allowed_end.hour,
        limits.allowed_end.minute,
        tzinfo=zone,
    )
    return (TimeInterval(start=start.astimezone(UTC), end=end.astimezone(UTC)),)


def pick_hour(
    slot: datetime,
    busy_intervals: Sequence[TimeInterval],
    limits: ProfileLimits,
) -> TimeInterval | None:
    """First free hour-long block at a quarter hour inside the local day."""
    zone = ZoneInfo(limits.timezone)
    local = slot.astimezone(zone)
    day = local.date()
    if local.minute % 15 == 0 and local.second == 0 and local.microsecond == 0:
        step = 0
    else:
        step = 15 - local.minute % 15
    current = slot.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(
        minutes=step
    )
    for _ in range(500):
        wall_start = current.astimezone(zone)
        wall_end = (current + _HOUR).astimezone(zone)
        if wall_start.date() != day or wall_start.time() >= limits.allowed_end:
            return None
        if (
            wall_start.time() >= limits.allowed_start
            and wall_end.date() == day
            and wall_end.time() <= limits.allowed_end
            and not any(
                current < busy.end and busy.start < current + _HOUR
                for busy in busy_intervals
            )
        ):
            return TimeInterval(
                start=fixed_offset(current.astimezone(zone)),
                end=fixed_offset((current + _HOUR).astimezone(zone)),
            )
        current = current + _QUARTER
    return None


def future_busy_intervals(
    events: Sequence[Event], *, as_of: datetime, slot: datetime
) -> tuple[TimeInterval, ...]:
    """Winner-first busy list overlapping the day around the slot."""
    fresh = [event for event in events if event.collected_at <= as_of]
    intervals: list[TimeInterval] = []
    for event in select_winners(fresh):
        data = event.data
        if isinstance(data, CalendarEventCancelledData):
            continue
        if not isinstance(data, (CalendarEventCreatedData, CalendarEventUpdatedData)):
            continue
        if not data.busy:
            continue
        if data.end <= data.start:
            continue
        intervals.append(TimeInterval(start=data.start, end=data.end))
    low = min(as_of, slot)
    high = max(as_of, slot) + timedelta(hours=24)
    return tuple(
        interval
        for interval in intervals
        if interval.start < high and low < interval.end
    )


def fallback_window_codes(
    *,
    slot: datetime,
    start: datetime,
    end: datetime,
    limits: ProfileLimits,
    busy_intervals: Sequence[TimeInterval] = (),
) -> tuple[str, ...]:
    """Slot plus action window verdicts for a fallback range."""
    codes = list(slot_window_codes(slot, limits))
    codes.extend(
        action_window_codes(
            start,
            end,
            slot=slot,
            busy_intervals=tuple(busy_intervals),
            free_intervals=allowed_windows(slot, limits),
        )
    )
    return tuple(codes)


def cycle_window(as_of: datetime) -> tuple[datetime, datetime]:
    """The D17 literal query window ending at the instant."""
    return (as_of - _CYCLE_WINDOW, as_of)


def busy_query_span(as_of: datetime) -> tuple[datetime, datetime]:
    """The D4 event-load span around the instant."""
    return (as_of - _BUSY_WINDOW, as_of + _BUSY_WINDOW)
