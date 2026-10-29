"""Ticket 5: Calendar (iCal) collector tests on a synthetic fixture only."""

import json
import logging
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from framework.collectors import CalendarIcsCollector
from framework.collectors.common import CollectorError, HttpResponse
from framework.schemas import Event
from framework.store import EventStore, run_collector

FIXTURE_PATH = Path("tests/fixtures/calendar_synthetic.ics")
ICAL_URL = "https://example.invalid/secret-calendar-token.ics"

# Frozen clock: 2026-10-30T12:00:00+01:00, so the poll window is
# [2026-10-28T12:00:00+01:00, 2026-11-13T12:00:00+01:00).
NOW = datetime.fromisoformat("2026-10-30T12:00:00+01:00")

SUMMARIES = [
    "Synthetic weekly iki-focus block",
    "new: iki-partner synthetic intro call",
    "Quarterly planning session",
]


def make_http_get(
    body: bytes, *, status: int = 200, seen: dict[str, Any] | None = None
) -> Any:
    def fake(url: str, headers: dict[str, str]) -> HttpResponse:
        assert url == ICAL_URL, f"unexpected URL: {url}"
        assert headers == {}, f"unexpected headers: {headers}"
        if seen is not None:
            seen["calls"] = int(seen.get("calls", 0)) + 1
        return HttpResponse(status=status, headers={}, body=body)

    return fake


@pytest.fixture
def store(tmp_path: Path) -> Generator[EventStore, None, None]:
    owned = EventStore(tmp_path / "events.db")
    yield owned
    owned.close()


@pytest.fixture
def ics_body() -> bytes:
    return FIXTURE_PATH.read_bytes()


def poll_once(
    monkeypatch: pytest.MonkeyPatch, http_get: Any, cursor: Any = None
) -> tuple[list[Event], Any]:
    monkeypatch.setenv("ICAL_URL", ICAL_URL)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = CalendarIcsCollector(http_get=http_get, now_fn=lambda: NOW)
    return collector.poll(cursor)


def test_recurring_expands_to_window_occurrences_only(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes
) -> None:
    events, _ = poll_once(monkeypatch, make_http_get(ics_body))
    weekly = [e for e in events if e.source_id.startswith("synthetic-weekly-1@")]
    assert len(weekly) == 2
    assert {e.source_id for e in weekly} == {
        "synthetic-weekly-1@2026-11-02T09:00:00+00:00@2026-10-20T08:00:00+00:00",
        "synthetic-weekly-1@2026-11-09T09:00:00+00:00@2026-10-20T08:00:00+00:00",
    }
    assert all(e.type == "calendar.event.created" for e in weekly)
    assert all(e.data.category == "personal" for e in weekly)  # type: ignore[attr-defined]
    assert all(e.tier == "private" for e in weekly)
    assert all(e.source == "calendar" for e in weekly)
    assert all(e.collector_version == "calendar@0.1.0" for e in weekly)


def test_new_prefix_tags_and_busy(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes
) -> None:
    events, _ = poll_once(monkeypatch, make_http_get(ics_body))
    partner = next(e for e in events if e.source_id.startswith("synthetic-partner-1@"))
    assert partner.data.is_new is True  # type: ignore[attr-defined]
    assert partner.data.tags == ["iki-partner"]  # type: ignore[attr-defined]
    assert partner.data.busy is False  # type: ignore[attr-defined]

    weekly = next(e for e in events if e.source_id.startswith("synthetic-weekly-1@"))
    assert weekly.data.is_new is False  # type: ignore[attr-defined]
    assert weekly.data.tags == ["iki-focus"]  # type: ignore[attr-defined]
    assert weekly.data.busy is True  # type: ignore[attr-defined]

    plain = next(e for e in events if e.source_id.startswith("synthetic-roundtable-1@"))
    assert plain.data.is_new is False  # type: ignore[attr-defined]
    assert plain.data.tags == []  # type: ignore[attr-defined]
    assert plain.data.busy is True  # type: ignore[attr-defined]


def test_disappearance_emits_one_cancelled_and_bumped_emits_updated(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes
) -> None:
    events1, cursor1 = poll_once(monkeypatch, make_http_get(ics_body))
    assert len(events1) == 4
    partner_before = next(
        e for e in events1 if e.source_id.startswith("synthetic-partner-1@")
    )

    # Rebuild fixture B: full text minus the partner block, with roundtable bumped.
    head, _, tail = ics_body.decode("utf-8").partition(
        "BEGIN:VEVENT\nUID:synthetic-partner-1"
    )
    _, _, partner_tail = tail.partition("END:VEVENT\n")
    text_b = head + partner_tail.replace(
        "LAST-MODIFIED:20261026T100000Z", "LAST-MODIFIED:20261027T100000Z"
    )
    assert "synthetic-partner-1" not in text_b

    events2, cursor2 = poll_once(monkeypatch, make_http_get(text_b.encode()), cursor1)
    assert len(events2) == 2
    cancelled = next(e for e in events2 if e.type == "calendar.event.cancelled")
    updated = next(e for e in events2 if e.type == "calendar.event.updated")
    assert cancelled.source_id == partner_before.source_id + "#cancelled"
    assert cancelled.time == partner_before.time
    assert cancelled.data.model_dump() == {
        **partner_before.data.model_dump(),
        "type": "calendar.event.cancelled",
    }
    assert updated.source_id.startswith("synthetic-roundtable-1@")
    assert updated.source_id.endswith("@2026-10-27T10:00:00+00:00")

    events3, _ = poll_once(monkeypatch, make_http_get(text_b.encode("utf-8")), cursor2)
    assert events3 == []


def test_instance_that_ages_out_of_window_emits_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline = (
        b"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//ikigai-loop//synthetic//EN\n"
        b"BEGIN:VEVENT\nUID:synthetic-oneoff-1\nDTSTAMP:20261025T080000Z\n"
        b"DTSTART:20261102T150000Z\nDTEND:20261102T160000Z\n"
        b"LAST-MODIFIED:20261025T090000Z\nSUMMARY:One-off synthetic session\nEND:VEVENT\n"
        b"END:VCALENDAR\n"
    )
    events1, cursor1 = poll_once(monkeypatch, make_http_get(inline))
    assert len(events1) == 1

    later = NOW + timedelta(days=7)
    monkeypatch.setenv("ICAL_URL", ICAL_URL)
    collector = CalendarIcsCollector(
        http_get=make_http_get(inline), now_fn=lambda: later
    )
    events2, cursor2 = collector.poll(cursor1)
    assert events2 == []
    assert cursor2 == {"instances": {}}


def test_dtstamp_only_change_emits_nothing(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes
) -> None:
    _, cursor1 = poll_once(monkeypatch, make_http_get(ics_body))
    changed = ics_body.replace(b"DTSTAMP:", b"DTSTAMP:9")
    events2, cursor2 = poll_once(monkeypatch, make_http_get(changed), cursor1)
    assert events2 == []
    assert cursor2 == cursor1


def test_title_absent_from_stored_events(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes, store: EventStore
) -> None:
    monkeypatch.setenv("ICAL_URL", ICAL_URL)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = CalendarIcsCollector(
        http_get=make_http_get(ics_body), now_fn=lambda: NOW
    )
    inserted, conflicts = run_collector(store, collector)
    assert (inserted, conflicts) == (4, 0)
    stored = store.events_between(
        "subject-1",
        datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        datetime.fromisoformat("2027-01-01T00:00:00+00:00"),
    )
    assert len(stored) == 4
    for event in stored:
        assert not hasattr(event.data, "title")
        payload = event.model_dump_json()
        for summary in SUMMARIES:
            assert summary not in payload


def test_ical_url_secret_never_leaks(
    monkeypatch: pytest.MonkeyPatch,
    ics_body: bytes,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("ICAL_URL", ICAL_URL)
    collector = CalendarIcsCollector(
        http_get=make_http_get(ics_body, status=500), now_fn=lambda: NOW
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(CollectorError) as excinfo:
        collector.poll(None)
    assert "secret-calendar-token" not in str(excinfo.value)
    assert ICAL_URL not in str(excinfo.value)
    assert all("secret-calendar-token" not in r.getMessage() for r in caplog.records)

    def network_error(url: str, headers: dict[str, str]) -> HttpResponse:
        raise OSError("synthetic network failure")

    collector = CalendarIcsCollector(http_get=network_error, now_fn=lambda: NOW)
    with caplog.at_level(logging.DEBUG), pytest.raises(CollectorError) as excinfo2:
        collector.poll(None)
    assert "secret-calendar-token" not in str(excinfo2.value)
    assert ICAL_URL not in str(excinfo2.value)

    events, cursor = poll_once(monkeypatch, make_http_get(ics_body))
    assert "secret-calendar-token" not in json.dumps(cursor)
    for event in events:
        assert "secret-calendar-token" not in event.model_dump_json()

    monkeypatch.delenv("ICAL_URL", raising=False)
    collector = CalendarIcsCollector(
        http_get=make_http_get(ics_body), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError, match="ICAL_URL is not set"):
        collector.poll(None)


def test_fetch_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    monkeypatch.setenv("ICAL_URL", ICAL_URL)
    collector = CalendarIcsCollector(
        http_get=make_http_get(b"", status=500), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError):
        run_collector(store, collector)
    garbage = CalendarIcsCollector(
        http_get=make_http_get(b"this is not an ics body"), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError, match="invalid response"):
        run_collector(store, garbage)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("calendar") is None


def test_window_bounds_exclude_edges(
    monkeypatch: pytest.MonkeyPatch, ics_body: bytes
) -> None:
    events, _ = poll_once(monkeypatch, make_http_get(ics_body))
    window_start = NOW - timedelta(days=2)
    window_end = NOW + timedelta(days=14)
    assert len(events) == 4
    for event in events:
        assert window_start <= event.time < window_end
