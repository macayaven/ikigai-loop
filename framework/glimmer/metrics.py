"""Deterministic metrics and period rollup (Ticket 9). Pure, no model."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from framework.briefing.context import MetricSnapshot
from framework.schemas.events import Event

PERIOD_NAMES: tuple[str, str, str] = ("earlier", "prior", "last")
WINDOW = timedelta(hours=72)


def fixed_offset(as_of: datetime) -> datetime:
    """Pin a zoned instant to its own fixed offset.

    Arithmetic on a named zone is wall-clock, so a span crossing a DST
    change is not 24 h; the pinned copy measures absolute time.
    """
    offset = as_of.utcoffset()
    if offset is None:
        raise ValueError("as_of must carry a UTC offset")
    return as_of.astimezone(timezone(offset))


def _logical_key(event: Event) -> tuple[str, ...]:
    if event.type.startswith("calendar.event."):
        sid = event.source_id
        sid = sid.removesuffix("#cancelled")
        if "@" in sid:
            sid = sid.rsplit("@", 1)[0]
        return ("calendar", sid)
    if event.type == "screen.hour":
        device = getattr(event.data, "device", "")
        instant = event.time.astimezone(UTC).isoformat()
        return ("screen", str(device), instant)
    if event.type == "feed.item":
        sid = (
            event.source_id.rsplit("@", 1)[0]
            if "@" in event.source_id
            else event.source_id
        )
        return ("feed", sid)
    return ("event", event.id)


def select_winners(events: Sequence[Event]) -> tuple[Event, ...]:
    """One winner per logical key: greatest collected_at, then greatest id."""
    best: dict[tuple[str, ...], Event] = {}
    for event in events:
        key = _logical_key(event)
        current = best.get(key)
        if current is None or (event.collected_at, event.id) > (
            current.collected_at,
            current.id,
        ):
            best[key] = event
    return tuple(sorted(best.values(), key=lambda e: (e.time, e.id)))


def period_bounds(
    as_of: datetime,
) -> tuple[tuple[str, datetime, datetime], ...]:
    as_of = fixed_offset(as_of)
    return tuple(
        (
            name,
            as_of - timedelta(hours=(3 - i) * 24),
            as_of - timedelta(hours=(2 - i) * 24),
        )
        for i, name in enumerate(PERIOD_NAMES)
    )


def _period_name_for(
    moment: datetime, bounds: Sequence[tuple[str, datetime, datetime]]
) -> str | None:
    for name, start, end in bounds:
        if start <= moment < end:
            return name
    return None


def _clipped_hours(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    s, e = max(start, lo), min(end, hi)
    return max(0.0, (e - s).total_seconds() / 3600.0)


def build_period_rollup(
    as_of: datetime, winners: Sequence[Event]
) -> dict[str, dict[str, Any]]:
    """Three 24h periods ending at as_of, over the given winners only."""
    bounds = period_bounds(as_of)
    rollup: dict[str, dict[str, Any]] = {
        name: {
            "start": start,
            "end": end,
            "screen_hours": {},
            "pushes": 0,
            "prs": 0,
            "calendar_hours_by_tag": {},
            "cancelled_blocks_by_tag": {},
        }
        for name, start, end in bounds
    }
    for event in winners:
        data: Any = event.data
        if event.type == "screen.hour":
            name = _period_name_for(event.time, bounds)
            if name is None:
                continue
            target = rollup[name]["screen_hours"]
            for category, minutes in data.minutes_by_category.items():
                target[category] = target.get(category, 0.0) + float(minutes) / 60.0
        elif event.type == "github.push":
            name = _period_name_for(event.time, bounds)
            if name is not None:
                rollup[name]["pushes"] += 1
        elif event.type == "github.pr":
            name = _period_name_for(event.time, bounds)
            if name is not None:
                rollup[name]["prs"] += 1
        elif event.type.startswith("calendar.event."):
            if event.type == "calendar.event.cancelled":
                name = _period_name_for(event.time, bounds)
                if name is not None:
                    target = rollup[name]["cancelled_blocks_by_tag"]
                    for tag in data.tags:
                        target[tag] = target.get(tag, 0) + 1
            else:
                for name, start, end in bounds:
                    hours = _clipped_hours(data.start, data.end, start, end)
                    if hours <= 0:
                        continue
                    target = rollup[name]["calendar_hours_by_tag"]
                    for tag in data.tags:
                        target[tag] = target.get(tag, 0.0) + hours
    return rollup


def build_metric_snapshot(as_of: datetime, winners: Sequence[Event]) -> MetricSnapshot:
    as_of = fixed_offset(as_of)
    window_start = as_of - WINDOW
    values: dict[str, float] = {"calendar.busy_hours": 0.0, "feed.item.count": 0.0}
    for event in winners:
        data: Any = event.data
        if event.type == "screen.hour":
            for category, minutes in data.minutes_by_category.items():
                key = f"screen_hours.{category}"
                values[key] = values.get(key, 0.0) + float(minutes) / 60.0
        elif event.type == "github.push":
            values["github.push.count"] = values.get("github.push.count", 0.0) + 1.0
        elif event.type == "github.pr":
            values["github.pr.count"] = values.get("github.pr.count", 0.0) + 1.0
        elif event.type == "feed.item":
            values["feed.item.count"] += 1.0
            key = f"feed.item.count.{data.source}"
            values[key] = values.get(key, 0.0) + 1.0
        elif event.type.startswith("calendar.event."):
            if event.type == "calendar.event.cancelled":
                continue
            hours = _clipped_hours(data.start, data.end, window_start, as_of)
            if data.busy:
                values["calendar.busy_hours"] += hours
            for tag in data.tags:
                key = f"tag_hours.{tag}"
                values[key] = values.get(key, 0.0) + hours
    rollup = build_period_rollup(as_of, winners)
    for name in PERIOD_NAMES:
        period = rollup[name]
        values[f"period.{name}.pushes"] = float(period["pushes"])
        values[f"period.{name}.prs"] = float(period["prs"])
        for category, hours in period["screen_hours"].items():
            if hours:
                values[f"period.{name}.screen_hours.{category}"] = float(hours)
        for tag, hours in period["calendar_hours_by_tag"].items():
            if hours:
                values[f"period.{name}.tag_hours.{tag}"] = float(hours)
        for tag, count in period["cancelled_blocks_by_tag"].items():
            if count:
                values[f"period.{name}.cancelled.{tag}"] = float(count)
    values = {
        k: v
        for k, v in values.items()
        if v != 0.0
        or k
        in (
            "calendar.busy_hours",
            "feed.item.count",
            *(f"period.{n}.pushes" for n in PERIOD_NAMES),
            *(f"period.{n}.prs" for n in PERIOD_NAMES),
        )
    }
    return MetricSnapshot(values=values)
