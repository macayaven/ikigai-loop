"""Append-only SQLite event store (ticket 4)."""

import hashlib
import json
import os
import sqlite3
from collections.abc import Collection, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Self
from zoneinfo import ZoneInfo

from framework.schemas import Event

MADRID = ZoneInfo("Europe/Madrid")

DDL = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT NOT NULL UNIQUE,
    subject_id TEXT NOT NULL,
    source TEXT NOT NULL,
    type TEXT NOT NULL,
    time TEXT NOT NULL,
    source_id TEXT NOT NULL,
    data TEXT NOT NULL,
    tier TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    collector_version TEXT NOT NULL,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_events_subject_time ON events (subject_id, time, id);
CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only');
END;
CREATE TABLE IF NOT EXISTS cursors (
    name TEXT PRIMARY KEY,
    cursor TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS batch_hashes (
    day TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (day, subject_id)
);
CREATE TABLE IF NOT EXISTS conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    stored_json TEXT NOT NULL,
    incoming_json TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, subject_id, source, type, time, source_id, data, tier, collected_at,"
    " collector_version"
)


class ConflictingEvent(Exception):
    """An append with a taken (source, source_id) or id carrying different content."""

    def __init__(
        self, source: str, source_id: str, stored_json: str, incoming_json: str
    ) -> None:
        super().__init__(
            f"conflicting event for ({source}, {source_id}): stored row wins"
        )
        self.source = source
        self.source_id = source_id
        self.stored_json = stored_json
        self.incoming_json = incoming_json


def canonical_json(value: Any) -> str:
    """One canonical JSON recipe used for data columns, hashes, and cursors."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def resolve_db_path(db_path: Path | None = None) -> Path:
    """Resolve the store path: explicit argument wins, else IKIGAI_DATA_DIR/ikigai.db.

    A relative IKIGAI_DATA_DIR value is relative to the process cwd (never the repo).
    """
    if db_path is not None:
        return db_path
    return Path(os.environ.get("IKIGAI_DATA_DIR", "./data")) / "ikigai.db"


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{label} must be an aware datetime")


def _row_to_event(row: Sequence[Any]) -> Event:
    return Event.model_validate(
        {
            "id": row[0],
            "subject_id": row[1],
            "source": row[2],
            "type": row[3],
            "time": row[4],
            "source_id": row[5],
            "data": json.loads(row[6]),
            "tier": row[7],
            "collected_at": row[8],
            "collector_version": row[9],
        }
    )


def _envelope_json(event: Event) -> str:
    return canonical_json(event.model_dump(mode="json"))


def _identity_key(event: Event) -> tuple[str, str, str, str, str, str, str]:
    return (
        event.subject_id,
        event.source,
        event.source_id,
        event.type,
        _utc_text(event.time),
        event.tier,
        canonical_json(event.data.model_dump(mode="json")),
    )


class EventStore:
    """Append-only SQLite store: events plus per-collector cursors and batch hashes."""

    def __init__(self, db_path: Path | None = None) -> None:
        resolved = resolve_db_path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._conn = sqlite3.connect(resolved, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(DDL)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _append_one(self, conn: sqlite3.Connection, event: Event) -> bool:
        row = conn.execute(
            f"SELECT {_COLUMNS} FROM events WHERE source = ? AND source_id = ?",
            (event.source, event.source_id),
        ).fetchone()
        if row is not None:
            stored_key = (row[1], row[2], row[5], row[3], row[4], row[7], row[6])
            if stored_key == _identity_key(event):
                return False
            raise ConflictingEvent(
                event.source,
                event.source_id,
                _envelope_json(_row_to_event(row)),
                _envelope_json(event),
            )
        try:
            conn.execute(
                "INSERT INTO events ("
                + _COLUMNS
                + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.subject_id,
                    event.source,
                    event.type,
                    _utc_text(event.time),
                    event.source_id,
                    canonical_json(event.data.model_dump(mode="json")),
                    event.tier,
                    _utc_text(event.collected_at),
                    event.collector_version,
                ),
            )
        except sqlite3.IntegrityError as exc:
            if "events.id" not in str(exc):
                raise
            taken = conn.execute(
                f"SELECT {_COLUMNS} FROM events WHERE id = ?", (event.id,)
            ).fetchone()
            stored_json = (
                _envelope_json(_row_to_event(taken)) if taken is not None else ""
            )
            raise ConflictingEvent(
                event.source, event.source_id, stored_json, _envelope_json(event)
            ) from exc
        return True

    def append_event(self, event: Event) -> bool:
        """Insert one event; True when inserted, False on identical re-delivery."""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            inserted = self._append_one(conn, event)
            conn.execute("COMMIT")
            return inserted
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def append_events(self, events: Sequence[Event]) -> int:
        """Insert a batch in one transaction; a conflict rolls back the whole batch."""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            inserted = 0
            for event in events:
                if self._append_one(conn, event):
                    inserted += 1
            conn.execute("COMMIT")
            return inserted
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def get_cursor(self, name: str) -> Any:
        """Return the stored opaque cursor for a collector, or None."""
        row = self._conn.execute(
            "SELECT cursor FROM cursors WHERE name = ?", (name,)
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return json.loads(row[0])

    def poll_transaction(
        self, name: str, events: Sequence[Event], new_cursor: Any
    ) -> tuple[int, int]:
        """Apply one poll (events plus cursor advance) in a single transaction."""
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            inserted = 0
            conflicts = 0
            for event in events:
                try:
                    if self._append_one(conn, event):
                        inserted += 1
                except ConflictingEvent as exc:
                    conn.execute(
                        "INSERT INTO conflicts (detected_at, source, source_id,"
                        " stored_json, incoming_json) VALUES (?, ?, ?, ?, ?)",
                        (
                            datetime.now(UTC).isoformat(),
                            exc.source,
                            exc.source_id,
                            exc.stored_json,
                            exc.incoming_json,
                        ),
                    )
                    conflicts += 1
            conn.execute(
                "INSERT INTO cursors (name, cursor, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET cursor = excluded.cursor,"
                " updated_at = excluded.updated_at",
                (name, canonical_json(new_cursor), datetime.now(UTC).isoformat()),
            )
            conn.execute("COMMIT")
            return (inserted, conflicts)
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def events_between(
        self,
        subject_id: str,
        start: datetime,
        end: datetime,
        types: Collection[str] | None = None,
    ) -> list[Event]:
        """Return one subject's events in [start, end), ordered by (time, id)."""
        _require_aware(start, "start")
        _require_aware(end, "end")
        if start > end:
            raise ValueError("start must not be after end")
        if start == end:
            return []
        query = (
            f"SELECT {_COLUMNS} FROM events WHERE subject_id = ?"
            " AND time >= ? AND time < ?"
        )
        args: list[str] = [subject_id, _utc_text(start), _utc_text(end)]
        if types is not None:
            placeholders = ", ".join("?" for _ in types)
            query += f" AND type IN ({placeholders})"
            args.extend(types)
        query += " ORDER BY time, id"
        rows = self._conn.execute(query, args).fetchall()
        return [_row_to_event(row) for row in rows]

    def daily_batch_hash(self, day: date, subject_id: str) -> str:
        """Hash one Europe/Madrid calendar day's events and record it in batch_hashes."""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM events WHERE subject_id = ? ORDER BY id",
            (subject_id,),
        ).fetchall()
        day_events = [
            event
            for row in rows
            if (event := _row_to_event(row)).time.astimezone(MADRID).date() == day
        ]
        digest = hashlib.sha256(
            canonical_json(
                [event.model_dump(mode="json") for event in day_events]
            ).encode("utf-8")
        ).hexdigest()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO batch_hashes (day, subject_id, hash, event_count,"
                " computed_at) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(day, subject_id) DO UPDATE SET hash = excluded.hash,"
                " event_count = excluded.event_count,"
                " computed_at = excluded.computed_at",
                (
                    day.isoformat(),
                    subject_id,
                    digest,
                    len(day_events),
                    datetime.now(UTC).isoformat(),
                ),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return digest

    def purge_before(self, cutoff: datetime) -> int:
        """Delete only events with time < cutoff; return the deleted row count."""
        _require_aware(cutoff, "cutoff")
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                "DELETE FROM events WHERE time < ?", (_utc_text(cutoff),)
            )
            deleted = cursor.rowcount
            conn.execute("COMMIT")
            return deleted
        except BaseException:
            conn.execute("ROLLBACK")
            raise
