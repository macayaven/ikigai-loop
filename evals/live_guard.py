"""Ticket 15b: shared live-run guard (D2, D12).

Quiet windows come from the product's own slot times. The guard is a pure
function of frozen instants so tests never wait on a clock. A started
repeat always finishes: callers consult ``start_blocked`` only between
repeats, so a stop can never manufacture a fallback.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from framework.cycle.orchestrator import EXTRA_SLOT, SLOT_TIMES

MADRID = ZoneInfo("Europe/Madrid")


class Refusal(Exception):
    """A pre-run refusal; the message names the rule only."""

    def __init__(self, message: str, *, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def live_disabled(variable: str) -> str | None:
    """One disabled line unless the live variable opts in, else None."""
    if os.environ.get(variable) == "1":
        return None
    return f"disabled: live runs need {variable}=1"


def quiet_windows(
    now: datetime,
    quiet_before_min: int = 25,
    quiet_after_min: int = 5,
) -> tuple[tuple[datetime, datetime], ...]:
    """[slot - before, slot + after) for each Madrid slot today and tomorrow.

    The dated extra slot (Deviation 18) is not a daily time, so it gets
    its own window when it falls today or tomorrow.
    """
    today = now.astimezone(MADRID).date()
    windows: list[tuple[datetime, datetime]] = []
    for day_offset in (0, 1):
        day = today + timedelta(days=day_offset)
        for slot_time in SLOT_TIMES:
            slot = datetime(
                day.year,
                day.month,
                day.day,
                slot_time.hour,
                slot_time.minute,
                tzinfo=MADRID,
            )
            windows.append(
                (
                    slot - timedelta(minutes=quiet_before_min),
                    slot + timedelta(minutes=quiet_after_min),
                )
            )
    if EXTRA_SLOT.date() in (today, today + timedelta(days=1)):
        windows.append(
            (
                EXTRA_SLOT - timedelta(minutes=quiet_before_min),
                EXTRA_SLOT + timedelta(minutes=quiet_after_min),
            )
        )
    return tuple(sorted(windows))


def start_blocked(
    now: datetime,
    windows: tuple[tuple[datetime, datetime], ...],
    drain: timedelta,
    stop_time: datetime | None,
) -> str | None:
    """Why no new repeat may start now, or None when one may."""
    if stop_time is not None and now >= stop_time:
        return "stop time"
    for start, end in windows:
        if start <= now < end:
            return "quiet window"
    for start, _end in windows:
        if now < start <= now + drain:
            return "drain margin"
    return None


def parse_stop_time(raw: str | None) -> datetime | None:
    """Parse an aware stop instant; naive or bad input is refused."""
    if raw is None:
        return None
    try:
        instant = datetime.fromisoformat(raw)
    except ValueError:
        raise Refusal("bad stop time") from None
    if instant.tzinfo is None:
        raise Refusal("bad stop time")
    return instant


def add_shared_args(parser: argparse.ArgumentParser, results_default: str) -> None:
    """R1b's words where the thing is the same: stop, limit, dir, workers."""
    parser.add_argument("--stop-time", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--results-dir", default=results_default)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--quiet-before-minutes", type=int, default=25)
    parser.add_argument("--quiet-after-minutes", type=int, default=5)
    parser.add_argument("--drain-minutes", type=int, default=10)
    parser.add_argument("--no-quiet-guard", action="store_true")
