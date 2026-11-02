"""Ticket 15b: live-guard tests (D2, D12).

Frozen instants only: no test waits on a clock, touches the network,
or calls a model.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from evals import live_guard
from evals.live_guard import Refusal
from framework.cycle.orchestrator import EXTRA_SLOT, SLOT_TIMES

MADRID = ZoneInfo("Europe/Madrid")


def _at(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=MADRID)


def test_windows_come_from_slot_times() -> None:
    now = _at("2026-11-03", "10:00:00")
    windows = live_guard.quiet_windows(now)
    assert len(windows) == 2 * len(SLOT_TIMES) + 1
    for start, end in windows:
        assert start.tzinfo is not None and end.tzinfo is not None
    first_day = sorted(
        (start, end)
        for start, end in windows
        if start.astimezone(MADRID).date().isoformat() == "2026-11-03"
    )
    assert len(first_day) == len(SLOT_TIMES) + 1
    assert EXTRA_SLOT == _at("2026-11-03", "11:30:00")
    expected = {
        (
            _at("2026-11-03", slot_time.strftime("%H:%M:%S")) - timedelta(minutes=25),
            _at("2026-11-03", slot_time.strftime("%H:%M:%S")) + timedelta(minutes=5),
        )
        for slot_time in SLOT_TIMES
    } | {
        (
            EXTRA_SLOT - timedelta(minutes=25),
            EXTRA_SLOT + timedelta(minutes=5),
        )
    }
    assert set(first_day) == expected


def test_extra_slot_window_blocks_its_morning() -> None:
    now = _at("2026-11-03", "10:00:00")
    windows = live_guard.quiet_windows(now)
    drain = timedelta(minutes=10)
    assert (
        live_guard.start_blocked(_at("2026-11-03", "11:30:00"), windows, drain, None)
        == "quiet window"
    )
    assert (
        live_guard.start_blocked(_at("2026-11-03", "11:04:59"), windows, drain, None)
        == "drain margin"
    )
    assert (
        live_guard.start_blocked(_at("2026-11-03", "11:34:59"), windows, drain, None)
        == "quiet window"
    )
    assert (
        live_guard.start_blocked(_at("2026-11-03", "11:35:00"), windows, drain, None)
        is None
    )


def test_start_blocked_at_frozen_boundaries() -> None:
    slot = _at("2026-11-03", "15:30:00")
    windows = ((slot - timedelta(minutes=25), slot + timedelta(minutes=5)),)
    drain = timedelta(minutes=5)
    assert (
        live_guard.start_blocked(
            slot - timedelta(minutes=30, seconds=1), windows, drain, None
        )
        is None
    )
    assert (
        live_guard.start_blocked(slot - timedelta(minutes=30), windows, drain, None)
        == "drain margin"
    )
    assert (
        live_guard.start_blocked(slot - timedelta(minutes=25), windows, drain, None)
        == "quiet window"
    )
    assert live_guard.start_blocked(slot, windows, drain, None) == "quiet window"
    assert (
        live_guard.start_blocked(
            slot + timedelta(minutes=5) - timedelta(seconds=1), windows, drain, None
        )
        == "quiet window"
    )
    assert (
        live_guard.start_blocked(slot + timedelta(minutes=5), windows, drain, None)
        is None
    )


def test_start_blocked_with_ten_minute_drain_boundaries() -> None:
    slot = _at("2026-11-03", "15:30:00")
    windows = ((slot - timedelta(minutes=25), slot + timedelta(minutes=5)),)
    drain = timedelta(minutes=10)
    assert (
        live_guard.start_blocked(
            slot - timedelta(minutes=35, seconds=1), windows, drain, None
        )
        is None
    )
    assert (
        live_guard.start_blocked(slot - timedelta(minutes=35), windows, drain, None)
        == "drain margin"
    )
    assert (
        live_guard.start_blocked(slot - timedelta(minutes=25), windows, drain, None)
        == "quiet window"
    )


def test_start_blocked_across_midnight() -> None:
    start = _at("2026-11-03", "23:58:00")
    end = _at("2026-11-04", "00:03:00")
    windows = ((start, end),)
    drain = timedelta(minutes=5)
    assert live_guard.start_blocked(start, windows, drain, None) == "quiet window"
    assert (
        live_guard.start_blocked(_at("2026-11-04", "00:02:59"), windows, drain, None)
        == "quiet window"
    )
    assert (
        live_guard.start_blocked(_at("2026-11-04", "00:03:00"), windows, drain, None)
        is None
    )
    assert (
        live_guard.start_blocked(
            start - drain - timedelta(seconds=1), windows, drain, None
        )
        is None
    )


def test_windows_hold_on_dst_dates() -> None:
    now = datetime(2026, 3, 29, 10, 0, tzinfo=MADRID)
    windows = live_guard.quiet_windows(now)
    assert len(windows) == 2 * len(SLOT_TIMES)
    for start, end in windows:
        assert start < end


def test_stop_time_blocks_starts_at_and_after_it() -> None:
    stop = _at("2026-11-03", "12:00:00")
    assert (
        live_guard.start_blocked(stop - timedelta(seconds=1), (), timedelta(0), stop)
        is None
    )
    assert live_guard.start_blocked(stop, (), timedelta(0), stop) == "stop time"
    assert (
        live_guard.start_blocked(stop + timedelta(hours=1), (), timedelta(0), stop)
        == "stop time"
    )


def test_parse_stop_time_refuses_naive_and_bad() -> None:
    with pytest.raises(Refusal):
        live_guard.parse_stop_time("2026-11-03T12:00:00")
    with pytest.raises(Refusal):
        live_guard.parse_stop_time("not-a-time")
    instant = live_guard.parse_stop_time("2026-11-03T12:00:00+01:00")
    assert instant == _at("2026-11-03", "12:00:00")
    assert live_guard.parse_stop_time(None) is None


def test_live_variable_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IKIGAI_R3_LIVE", raising=False)
    line = live_guard.live_disabled("IKIGAI_R3_LIVE")
    assert line is not None and "disabled" in line
    monkeypatch.setenv("IKIGAI_R3_LIVE", "1")
    assert live_guard.live_disabled("IKIGAI_R3_LIVE") is None


def test_shared_args_defaults() -> None:
    parser = argparse.ArgumentParser()
    live_guard.add_shared_args(parser, "/tmp/results")
    args = parser.parse_args([])
    assert args.concurrency == 4
    assert args.quiet_before_minutes == 25
    assert args.quiet_after_minutes == 5
    assert args.drain_minutes == 10
    assert args.stop_time is None
    assert args.limit is None
    assert args.results_dir == "/tmp/results"
    assert args.no_quiet_guard is False
