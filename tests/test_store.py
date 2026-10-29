"""Ticket 4: append-only event store tests (synthetic subject-1/subject-2 only)."""

import json
import sqlite3
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from framework.schemas import Event
from framework.store import ConflictingEvent, EventStore, resolve_db_path

PLUS1 = timezone(timedelta(hours=1))
DAY = date(2026, 10, 29)
T10 = datetime(2026, 10, 29, 10, 0, tzinfo=PLUS1)
T11 = datetime(2026, 10, 29, 11, 0, tzinfo=PLUS1)
T12 = datetime(2026, 10, 29, 12, 0, tzinfo=PLUS1)

PUSH_DATA: dict[str, Any] = {
    "type": "github.push",
    "repo": "synthetic/repo",
    "counts": {"commits": 2},
}
HEALTH_DATA: dict[str, Any] = {
    "type": "health.daily",
    "sleep_h": 7.5,
    "steps": 8000,
    "mood_valence": 0.2,
}


def make_event(
    *,
    event_id: str = "evt_test_1",
    subject_id: str = "subject-1",
    source: str = "fixture",
    source_id: str = "fixture_test_1",
    event_type: str = "github.push",
    time: datetime = T10,
    data: dict[str, Any] | None = None,
    tier: str = "public",
    collected_at: datetime = T11,
    collector_version: str = "fixture@0.1.0",
) -> Event:
    payload = dict(data if data is not None else PUSH_DATA)
    payload["type"] = event_type
    return Event.model_validate(
        {
            "id": event_id,
            "subject_id": subject_id,
            "source": source,
            "type": event_type,
            "time": time,
            "source_id": source_id,
            "data": payload,
            "tier": tier,
            "collected_at": collected_at,
            "collector_version": collector_version,
        }
    )


@pytest.fixture
def store(tmp_path: Path) -> Generator[EventStore, None, None]:
    owned = EventStore(tmp_path / "events.db")
    yield owned
    owned.close()


def test_round_trip_private_and_sensitive_readback(store: EventStore) -> None:
    push = make_event()
    health = make_event(
        event_id="evt_test_2",
        source_id="fixture_test_2",
        event_type="health.daily",
        time=T12,
        data=dict(HEALTH_DATA),
        tier="sensitive",
    )
    assert store.append_event(push) is True
    assert store.append_event(health) is True
    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
    assert store.events_between("subject-1", start, end) == [push, health]


def test_identity_redelivery_with_new_delivery_fields_is_noop(
    store: EventStore,
) -> None:
    first = make_event()
    assert store.append_event(first) is True
    redelivery = make_event(
        event_id="evt_test_1_redelivered",
        collected_at=datetime(2026, 10, 29, 15, 0, tzinfo=PLUS1),
        collector_version="fixture@0.2.0",
    )
    assert store.append_event(redelivery) is False
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
    (kept,) = store.events_between("subject-1", start, end)
    assert kept.id == "evt_test_1"
    assert kept.collector_version == "fixture@0.1.0"
    assert kept.collected_at == first.collected_at


def test_conflict_on_changed_data_keeps_stored_row(store: EventStore) -> None:
    stored = make_event()
    assert store.append_event(stored) is True
    changed = make_event(
        event_id="evt_test_1_changed",
        data={
            "type": "github.push",
            "repo": "synthetic/repo",
            "counts": {"commits": 9},
        },
    )
    with pytest.raises(ConflictingEvent) as excinfo:
        store.append_event(changed)
    assert excinfo.value.source == "fixture"
    assert excinfo.value.source_id == "fixture_test_1"
    assert json.loads(excinfo.value.stored_json)["data"]["counts"] == {"commits": 2}
    assert json.loads(excinfo.value.incoming_json)["data"]["counts"] == {"commits": 9}
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_conflict_on_changed_time_and_tier(store: EventStore) -> None:
    assert store.append_event(make_event()) is True
    with pytest.raises(ConflictingEvent):
        store.append_event(make_event(event_id="evt_other", time=T12))
    with pytest.raises(ConflictingEvent):
        store.append_event(make_event(event_id="evt_other", tier="private"))
    with pytest.raises(ConflictingEvent):
        store.append_event(make_event(event_id="evt_other", subject_id="subject-2"))
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_conflict_on_reused_id_under_new_key(store: EventStore) -> None:
    assert store.append_event(make_event()) is True
    with pytest.raises(ConflictingEvent):
        store.append_event(make_event(source_id="fixture_test_other"))
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_conflict_rolls_back_whole_batch(store: EventStore) -> None:
    first = make_event()
    assert store.append_events([first]) == 1
    with pytest.raises(ConflictingEvent):
        store.append_events(
            [
                make_event(event_id="evt_batch_2", source_id="fixture_batch_2"),
                make_event(event_id="evt_batch_3", time=T12),
            ]
        )
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_update_blocked_by_trigger(store: EventStore) -> None:
    assert store.append_event(make_event()) is True
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        store._conn.execute(
            "UPDATE events SET tier = 'private' WHERE id = 'evt_test_1'"
        )
    row = store._conn.execute(
        "SELECT tier FROM events WHERE id = 'evt_test_1'"
    ).fetchone()
    assert row[0] == "public"


def test_subject_isolation_types_filter_and_half_open_bounds(store: EventStore) -> None:
    mine = make_event(time=T10)
    other_person = make_event(
        event_id="evt_other_1",
        subject_id="subject-2",
        source_id="fixture_other_1",
        time=T11,
    )
    music = make_event(
        event_id="evt_test_music",
        source_id="fixture_test_music",
        event_type="music.play",
        time=T11,
        data={
            "type": "music.play",
            "track": "Synthetic Track",
            "artist": "Synthetic Artist",
            "played_at": T11,
        },
        tier="private",
    )
    store.append_events([mine, other_person, music])
    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
    assert store.events_between("subject-1", start, end) == [mine, music]
    assert store.events_between("subject-2", start, end) == [other_person]
    assert store.events_between("subject-1", start, end, types=["github.push"]) == [
        mine
    ]
    assert store.events_between("subject-1", T10, T11) == [mine]
    assert store.events_between("subject-1", T11, T11) == []
    with pytest.raises(ValueError):
        store.events_between("subject-1", T11, T10)
    with pytest.raises(ValueError):
        store.events_between("subject-1", datetime(2026, 10, 29, 9, 0), end)


def test_hash_deterministic_and_recorded(store: EventStore) -> None:
    store.append_events(
        [make_event(), make_event(event_id="evt_b", source_id="fixture_b")]
    )
    first = store.daily_batch_hash(DAY, "subject-1")
    assert first == store.daily_batch_hash(DAY, "subject-1")
    row = store._conn.execute(
        "SELECT day, subject_id, hash, event_count FROM batch_hashes"
    ).fetchone()
    assert (row[0], row[1], row[2], row[3]) == (DAY.isoformat(), "subject-1", first, 2)


def test_hash_changes_when_one_event_differs(tmp_path: Path) -> None:
    first_store = EventStore(tmp_path / "a.db")
    second_store = EventStore(tmp_path / "b.db")
    try:
        first_store.append_events(
            [make_event(), make_event(event_id="evt_b", source_id="fixture_b")]
        )
        second_store.append_events(
            [
                make_event(),
                make_event(
                    event_id="evt_b",
                    source_id="fixture_b",
                    data={
                        "type": "github.push",
                        "repo": "synthetic/repo",
                        "counts": {"commits": 5},
                    },
                ),
            ]
        )
        assert first_store.daily_batch_hash(
            DAY, "subject-1"
        ) != second_store.daily_batch_hash(DAY, "subject-1")
    finally:
        first_store.close()
        second_store.close()


def test_hash_uses_madrid_day_and_ignores_others(store: EventStore) -> None:
    late_utc = make_event(
        time=datetime(2026, 10, 29, 23, 30, tzinfo=UTC),
    )
    other_day = make_event(
        event_id="evt_prev",
        source_id="fixture_prev",
        time=datetime(2026, 10, 28, 10, 0, tzinfo=PLUS1),
    )
    store.append_events([late_utc, other_day])
    assert store.daily_batch_hash(
        date(2026, 10, 30), "subject-1"
    ) != store.daily_batch_hash(DAY, "subject-1")
    assert store.daily_batch_hash(
        date(2026, 10, 30), "subject-9"
    ) != store.daily_batch_hash(date(2026, 10, 30), "subject-1")
    empty = store.daily_batch_hash(date(2026, 11, 1), "subject-1")
    assert empty == store.daily_batch_hash(date(2026, 11, 1), "subject-1")
    count = store._conn.execute(
        "SELECT event_count FROM batch_hashes WHERE day = '2026-11-01'"
    ).fetchone()
    assert count[0] == 0


def test_purge_before_removes_only_older_events(store: EventStore) -> None:
    old = make_event(time=T10)
    at_cutoff = make_event(event_id="evt_cut", source_id="fixture_cut", time=T11)
    store.append_events([old, at_cutoff])
    store._conn.execute(
        "INSERT INTO cursors (name, cursor, updated_at) VALUES ('c', '1', 'x')"
    )
    store._conn.execute(
        "INSERT INTO batch_hashes (day, subject_id, hash, event_count, computed_at)"
        " VALUES ('2026-10-29', 'subject-1', 'h', 2, 'x')"
    )
    store._conn.execute(
        "INSERT INTO conflicts (detected_at, source, source_id, stored_json, incoming_json)"
        " VALUES ('x', 's', 'sid', '{}', '{}')"
    )
    assert store.purge_before(T11) == 1
    start = datetime(2026, 10, 29, 0, 0, tzinfo=UTC)
    end = datetime(2026, 10, 30, 0, 0, tzinfo=UTC)
    assert store.events_between("subject-1", start, end) == [at_cutoff]
    assert store._conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM batch_hashes").fetchone()[0] == 1
    assert store._conn.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 1
    with pytest.raises(ValueError):
        store.purge_before(datetime(2026, 10, 29, 9, 0))


def test_resolve_db_path_prefers_env_on_tmp_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IKIGAI_DATA_DIR", str(tmp_path / "envdata"))
    assert resolve_db_path() == tmp_path / "envdata" / "ikigai.db"
    owned = EventStore()
    try:
        assert owned.db_path == tmp_path / "envdata" / "ikigai.db"
        assert owned.db_path.exists()
    finally:
        owned.close()
    assert resolve_db_path(Path("/tmp/explicit.db")) == Path("/tmp/explicit.db")
