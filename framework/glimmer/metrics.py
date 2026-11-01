"""Deterministic metrics and period rollup (Ticket 9). Pure, no model."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from framework.briefing.context import MetricSnapshot
from framework.schemas.events import Event, GitHubPrData

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


def floor_hour(as_of: datetime) -> datetime:
    """Floor an instant to the whole UTC hour, keeping its fixed offset.

    The floor is taken in UTC, not on the pinned wall clock: screen buckets
    are UTC hours, and in a half-hour zone a wall-clock replace would land
    inside a bucket and split it.
    """
    pinned = fixed_offset(as_of)
    return (
        pinned.astimezone(UTC)
        .replace(minute=0, second=0, microsecond=0)
        .astimezone(pinned.tzinfo)
    )


def window_bounds(as_of: datetime) -> tuple[datetime, datetime]:
    """Floored data window: (window_start, window_end)."""
    end = floor_hour(as_of)
    return (end - WINDOW, end)


def _logical_key(event: Event) -> tuple[str, ...]:
    if event.type.startswith("calendar.event."):
        sid = event.source_id
        sid = sid.removesuffix("#cancelled")
        if "@" in sid:
            sid = sid.rsplit("@", 1)[0]
        return ("calendar", event.source, sid)
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


def is_opened_pr(event: Event) -> bool:
    """True when a ``github.pr`` row opens a pull request.

    One pull request emits one row per action, so it counts once, on its
    opened row. Any other action (``merged``, ``closed``, ``reopened``,
    ...) or an ``opened`` count of 0 counts nothing.
    """
    if event.type != "github.pr":
        return False
    data = event.data
    if not isinstance(data, GitHubPrData):
        return False
    return data.counts.get("opened", 0) > 0


def _split_uid_rid(uid_rid: str) -> tuple[str, str]:
    if "@" in uid_rid:
        uid, _, rid = uid_rid.rpartition("@")
        return (uid, rid)
    return (uid_rid, "")


def _drop_moved_cancellations(
    events: Sequence[Event], best: dict[tuple[str, ...], Event]
) -> list[Event]:
    """Drop a cancelled winner that is one half of a same-poll move (D4 2a).

    Within one source, a cancelled winner is a move — not a real
    cancellation — only when the same source holds an appearance of the same
    UID under a different rid with the same collected_at. An appearance is a
    key's first row, or a row following a cancelled row for its key. The scan
    reads all input rows, not only the winners, so a later stamp bump cannot
    bring the cancellation back.
    """
    rows_by_key: dict[tuple[str, str], list[Event]] = {}
    for event in events:
        if not event.type.startswith("calendar.event."):
            continue
        key = _logical_key(event)
        rows_by_key.setdefault((key[1], key[2]), []).append(event)
    appearances: set[tuple[str, str, str, datetime]] = set()
    for (source, uid_rid), rows in rows_by_key.items():
        uid, rid = _split_uid_rid(uid_rid)
        rows.sort(key=lambda e: (e.collected_at, e.id))
        prev_cancelled = False
        for index, row in enumerate(rows):
            if row.type == "calendar.event.cancelled":
                prev_cancelled = True
                continue
            if index == 0 or prev_cancelled:
                appearances.add((source, uid, rid, row.collected_at))
            prev_cancelled = False
    kept: list[Event] = []
    for key, winner in best.items():
        if key[0] != "calendar" or winner.type != "calendar.event.cancelled":
            kept.append(winner)
            continue
        uid, rid = _split_uid_rid(key[2])
        if any(
            source == key[1]
            and other_uid == uid
            and other_rid != rid
            and collected == winner.collected_at
            for source, other_uid, other_rid, collected in appearances
        ):
            continue
        kept.append(winner)
    return kept


def _combine_calendars(winners: list[Event]) -> list[Event]:
    """Combine winners across calendars by uid@rid (D4 step 3).

    If any calendar's winner for the invitation is active, every cancelled
    winner for it is dropped. If every winner is cancelled, exactly one
    cancelled row is kept: greatest collected_at, then id.
    """
    groups: dict[str, list[Event]] = {}
    others: list[Event] = []
    for winner in winners:
        key = _logical_key(winner)
        if key[0] == "calendar":
            groups.setdefault(key[2], []).append(winner)
        else:
            others.append(winner)
    combined: list[Event] = list(others)
    for rows in groups.values():
        active = [row for row in rows if row.type != "calendar.event.cancelled"]
        if active:
            combined.extend(active)
        else:
            combined.append(max(rows, key=lambda e: (e.collected_at, e.id)))
    return combined


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
    kept = _drop_moved_cancellations(events, best)
    combined = _combine_calendars(kept)
    return tuple(sorted(combined, key=lambda e: (e.time, e.id)))


def period_bounds(
    as_of: datetime,
) -> tuple[tuple[str, datetime, datetime], ...]:
    end = floor_hour(as_of)
    return tuple(
        (
            name,
            end - timedelta(hours=(3 - i) * 24),
            end - timedelta(hours=(2 - i) * 24),
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


def _union_hours(
    intervals: Sequence[tuple[datetime, datetime]], lo: datetime, hi: datetime
) -> float:
    """Union of clipped intervals in hours (D3): overlapping clock time once."""
    clipped = sorted(
        (max(start, lo), min(end, hi))
        for start, end in intervals
        if max(start, lo) < min(end, hi)
    )
    total = 0.0
    current_start: datetime | None = None
    current_end: datetime | None = None
    for start, end in clipped:
        if current_start is None or current_end is None or start > current_end:
            if current_start is not None and current_end is not None:
                total += (current_end - current_start).total_seconds() / 3600.0
            current_start, current_end = start, end
        elif end > current_end:
            current_end = end
    if current_start is not None and current_end is not None:
        total += (current_end - current_start).total_seconds() / 3600.0
    return total


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
    tag_intervals: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
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
            if name is not None and is_opened_pr(event):
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
                    if _clipped_hours(data.start, data.end, start, end) <= 0:
                        continue
                    for tag in data.tags:
                        tag_intervals.setdefault((name, tag), []).append(
                            (data.start, data.end)
                        )
    period_start = {name: start for name, start, _ in bounds}
    period_end = {name: end for name, _, end in bounds}
    for (name, tag), intervals in tag_intervals.items():
        hours = _union_hours(intervals, period_start[name], period_end[name])
        if hours > 0:
            rollup[name]["calendar_hours_by_tag"][tag] = hours
    return rollup


def build_metric_snapshot(
    as_of: datetime,
    winners: Sequence[Event],
    *,
    open_families: frozenset[str] = frozenset(),
) -> MetricSnapshot:
    window_start, window_end = window_bounds(as_of)
    values: dict[str, float] = {"calendar.busy_hours": 0.0, "feed.item.count": 0.0}
    busy_intervals: list[tuple[datetime, datetime]] = []
    window_tag_intervals: dict[str, list[tuple[datetime, datetime]]] = {}
    for event in winners:
        data: Any = event.data
        if event.type == "screen.hour":
            if not (window_start <= event.time < window_end):
                continue
            for category, minutes in data.minutes_by_category.items():
                key = f"screen_hours.{category}"
                values[key] = values.get(key, 0.0) + float(minutes) / 60.0
        elif event.type == "github.push":
            if not (window_start <= event.time < window_end):
                continue
            values["github.push.count"] = values.get("github.push.count", 0.0) + 1.0
        elif event.type == "github.pr":
            if not (window_start <= event.time < window_end):
                continue
            if is_opened_pr(event):
                values["github.pr.count"] = values.get("github.pr.count", 0.0) + 1.0
        elif event.type == "feed.item":
            if not (window_start <= event.time < window_end):
                continue
            values["feed.item.count"] += 1.0
            key = f"feed.item.count.{data.source}"
            values[key] = values.get(key, 0.0) + 1.0
        elif event.type.startswith("calendar.event."):
            if event.type == "calendar.event.cancelled":
                continue
            if data.busy:
                busy_intervals.append((data.start, data.end))
            for tag in data.tags:
                window_tag_intervals.setdefault(tag, []).append((data.start, data.end))
    values["calendar.busy_hours"] = _union_hours(
        busy_intervals, window_start, window_end
    )
    for tag, intervals in window_tag_intervals.items():
        hours = _union_hours(intervals, window_start, window_end)
        if hours > 0:
            values[f"tag_hours.{tag}"] = hours
    rollup = build_period_rollup(as_of, winners)
    screen_universe = {
        category
        for name in PERIOD_NAMES
        for category, hours in rollup[name]["screen_hours"].items()
        if hours
    }
    tag_universe = {
        tag
        for name in PERIOD_NAMES
        for tag, hours in rollup[name]["calendar_hours_by_tag"].items()
        if hours
    }
    cancelled_universe = {
        tag
        for name in PERIOD_NAMES
        for tag, count in rollup[name]["cancelled_blocks_by_tag"].items()
        if count
    }
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
        for category in sorted(screen_universe):
            values.setdefault(f"period.{name}.screen_hours.{category}", 0.0)
        for tag in sorted(tag_universe):
            values.setdefault(f"period.{name}.tag_hours.{tag}", 0.0)
        for tag in sorted(cancelled_universe):
            values.setdefault(f"period.{name}.cancelled.{tag}", 0.0)
    keep_zero = (
        {
            f"period.{name}.screen_hours.{category}"
            for name in PERIOD_NAMES
            for category in screen_universe
        }
        | {
            f"period.{name}.tag_hours.{tag}"
            for name in PERIOD_NAMES
            for tag in tag_universe
        }
        | {
            f"period.{name}.cancelled.{tag}"
            for name in PERIOD_NAMES
            for tag in cancelled_universe
        }
    )
    values = {
        k: v
        for k, v in values.items()
        if v != 0.0
        or k in keep_zero
        or k
        in (
            "calendar.busy_hours",
            "feed.item.count",
            *(f"period.{n}.pushes" for n in PERIOD_NAMES),
            *(f"period.{n}.prs" for n in PERIOD_NAMES),
        )
    }
    if open_families:
        for rest in open_families:
            key = f"period.last.{rest}"
            if values.get(key) == 0.0:
                del values[key]
    return MetricSnapshot(values=values)
