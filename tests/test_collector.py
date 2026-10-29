"""Ticket 4: collector framework tests (synthetic subject-1 only)."""

import json
import shutil
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from framework.schemas import Event
from framework.store import EventStore, FixtureCollector, run_collector

PLUS1 = timezone(timedelta(hours=1))
T10 = datetime(2026, 10, 29, 10, 0, tzinfo=PLUS1)
T11 = datetime(2026, 10, 29, 11, 0, tzinfo=PLUS1)
FIXTURE_PATH = Path("tests/fixtures/fixture_events.jsonl")


class StubCollector:
    """In-memory Collector for conflict and rollback cases."""

    def __init__(
        self, events: list[Event], new_cursor: Any, name: str = "stub"
    ) -> None:
        self._events = events
        self._new_cursor = new_cursor
        self.name = name
        self.version = "stub@0.1.0"

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        return list(self._events), self._new_cursor


def make_push(
    *,
    event_id: str = "evt_stub_1",
    source_id: str = "stub_1",
    commits: int = 2,
) -> Event:
    return Event.model_validate(
        {
            "id": event_id,
            "subject_id": "subject-1",
            "source": "stub",
            "type": "github.push",
            "time": T10,
            "source_id": source_id,
            "data": {
                "type": "github.push",
                "repo": "synthetic/repo",
                "counts": {"commits": commits},
            },
            "tier": "public",
            "collected_at": T11,
            "collector_version": "stub@0.1.0",
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Generator[EventStore, None, None]:
    owned = EventStore(tmp_path / "events.db")
    yield owned
    owned.close()


def test_fixture_repoll_is_idempotent(store: EventStore) -> None:
    collector = FixtureCollector(FIXTURE_PATH)
    assert store.get_cursor("fixture") is None
    assert run_collector(store, collector) == (3, 0)
    cursor = store.get_cursor("fixture")
    assert cursor == 3
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
    assert run_collector(store, collector) == (0, 0)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 3
    assert store.get_cursor("fixture") == cursor


def test_conflict_recorded_and_cursor_advances(store: EventStore) -> None:
    stored = make_push()
    assert store.append_event(stored) is True
    conflicting = make_push(event_id="evt_stub_1_changed", commits=9)
    new_a = make_push(event_id="evt_new_a", source_id="stub_new_a")
    new_b = make_push(event_id="evt_new_b", source_id="stub_new_b")
    collector = StubCollector([new_a, conflicting, new_b], "cursor-2")
    assert run_collector(store, collector) == (2, 1)
    start = datetime(2026, 10, 29, 0, 0, tzinfo=PLUS1)
    end = datetime(2026, 10, 30, 0, 0, tzinfo=PLUS1)
    kept = {
        event.source_id: event
        for event in store.events_between("subject-1", start, end)
    }
    assert set(kept) == {"stub_1", "stub_new_a", "stub_new_b"}
    assert kept["stub_1"].id == "evt_stub_1"
    rows = store._conn.execute(
        "SELECT source, source_id, stored_json, incoming_json FROM conflicts"
    ).fetchall()
    assert len(rows) == 1
    assert (rows[0][0], rows[0][1]) == ("stub", "stub_1")
    assert json.loads(rows[0][2])["id"] == "evt_stub_1"
    assert json.loads(rows[0][3])["id"] == "evt_stub_1_changed"
    assert store.get_cursor("stub") == "cursor-2"


def test_atomic_rollback_on_cursor_failure(store: EventStore) -> None:
    before_cursor = store.get_cursor("stub")
    collector = StubCollector([make_push()], object())
    with pytest.raises(TypeError):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 0
    assert store.get_cursor("stub") == before_cursor


def test_failing_poll_writes_nothing(store: EventStore) -> None:
    collector = StubCollector([make_push()], "cursor-1")

    def _boom(cursor: Any) -> tuple[list[Event], Any]:
        raise RuntimeError("synthetic poll failure")

    collector.poll = _boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="synthetic poll failure"):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("stub") is None


def test_fixture_append_then_repoll_returns_only_new_lines(
    store: EventStore, tmp_path: Path
) -> None:
    local = tmp_path / "fixture_events.jsonl"
    shutil.copyfile(FIXTURE_PATH, local)
    collector = FixtureCollector(local)
    assert run_collector(store, collector) == (3, 0)
    with local.open("a", encoding="utf-8") as handle:
        handle.write("\n")
        handle.write(
            make_push(event_id="evt_stub_9", source_id="stub_9").model_dump_json()
        )
        handle.write("\n")
    assert run_collector(store, collector) == (1, 0)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4


def test_missing_fixture_file_writes_nothing(store: EventStore, tmp_path: Path) -> None:
    collector = FixtureCollector(tmp_path / "missing.jsonl", name="absent")
    with pytest.raises(FileNotFoundError):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("absent") is None


def test_malformed_fixture_line_writes_nothing(
    store: EventStore, tmp_path: Path
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not valid json}\n", encoding="utf-8")
    collector = FixtureCollector(bad, name="broken")
    with pytest.raises(ValidationError):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("broken") is None
