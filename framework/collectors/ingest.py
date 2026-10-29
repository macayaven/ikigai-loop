"""Validated ingest server for health and screen.hour pushes (ticket 7).

Health consumers take the latest ``collected_at`` per ``(subject_id, date)``:
an identical re-post re-derives the same content-hash ``source_id`` (a
store no-op), while a corrected re-post mints a new ``source_id`` for the
same date that supersedes by ``collected_at`` instead of conflicting.

Screen.hour consumers take the latest ``collected_at`` per
``(device, hour)`` for the same reason: a changed hour is a new event for
that hour, never an update and never a conflict.
"""

import hashlib
import hmac
import json
import os
from collections.abc import Callable
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from framework.collectors.common import (
    CollectorError,
    as_dict,
    as_list,
    event_id,
    subject_id_from_env,
)
from framework.schemas import Event, HealthDailyData
from framework.store import EventStore
from framework.store.store import ConflictingEvent, canonical_json

MADRID = ZoneInfo("Europe/Madrid")

HEALTH_SOURCE = "health"
HEALTH_VERSION = "health@0.1.0"

MAX_BODY_BYTES = 1_000_000


class _BodyTooLarge(Exception):
    """A request body over MAX_BODY_BYTES; the handler answers 413."""


def _decode_object(body: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CollectorError(f"{label}: invalid response") from None
    obj = as_dict(payload)
    if obj is None:
        raise CollectorError(f"{label}: invalid response") from None
    return obj


def parse_health_event(body: bytes, *, subject_id: str, now: datetime) -> Event:
    """Validate one Shortcut payload and build its health.daily event."""
    obj = _decode_object(body, "health")
    raw_date = obj.get("date")
    if not isinstance(raw_date, str):
        raise CollectorError("health: invalid response") from None
    try:
        day = date.fromisoformat(raw_date)
    except ValueError:
        raise CollectorError("health: invalid response") from None
    try:
        data = HealthDailyData.model_validate(
            {k: v for k, v in obj.items() if k != "date"}
        )
    except ValidationError:
        raise CollectorError("health: invalid response") from None
    digest = hashlib.sha256(
        canonical_json(data.model_dump(mode="json")).encode()
    ).hexdigest()[:12]
    source_id = f"health:{day.isoformat()}:{digest}"
    return Event(
        id=event_id(HEALTH_SOURCE, source_id),
        subject_id=subject_id,
        source=HEALTH_SOURCE,
        type="health.daily",
        time=datetime(day.year, day.month, day.day, tzinfo=MADRID),
        source_id=source_id,
        data=data,
        tier="sensitive",
        collected_at=now,
        collector_version=HEALTH_VERSION,
    )


def ingest_health(
    store: EventStore, body: bytes, *, subject_id: str, now: datetime
) -> bool:
    """Store one Shortcut payload; False on identical re-delivery."""
    return store.append_event(parse_health_event(body, subject_id=subject_id, now=now))


def parse_screen_hour_events(body: bytes, *, now: datetime) -> list[Event]:
    """Validate a whole screen.hour batch; any invalid item fails the batch."""
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CollectorError("activitywatch: invalid response") from None
    items = as_list(payload)
    if items is None:
        raise CollectorError("activitywatch: invalid response") from None
    events: list[Event] = []
    for raw in items:
        try:
            event = Event.model_validate(raw)
        except ValidationError:
            raise CollectorError("activitywatch: invalid response") from None
        if (
            event.type != "screen.hour"
            or event.source != "activitywatch"
            or event.tier != "private"
        ):
            raise CollectorError("activitywatch: invalid response") from None
        events.append(event)
    return events


def ingest_screen_hours(
    store: EventStore, body: bytes, *, now: datetime
) -> tuple[int, int]:
    """Store a validated batch; return (inserted, identical no-ops)."""
    events = parse_screen_hour_events(body, now=now)
    inserted = store.append_events(events)
    return (inserted, len(events) - inserted)


def _counts_body(inserted: int, total: int) -> bytes:
    return json.dumps({"inserted": inserted, "total": total}).encode()


def make_ingest_handler(
    store: EventStore,
    *,
    subject_id: str,
    now_fn: Callable[[], datetime],
    token: str,
) -> type[BaseHTTPRequestHandler]:
    """Build the two-route ingest handler bound to one store and token."""

    class IngestHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            presented = self.headers.get("Authorization") or ""
            if not hmac.compare_digest(presented, f"Bearer {token}"):
                self._reply(401, b"")
                return
            if self.path == "/health/daily":
                self._handle_health()
            elif self.path == "/events/screen-hour":
                self._handle_screen_hour()
            else:
                self._reply(404, b"")

        def _handle_health(self) -> None:
            try:
                body = self._read_body()
            except _BodyTooLarge:
                self._reply(413, b"")
                return
            if body is None:
                self._reply(400, _counts_body(0, 0))
                return
            try:
                inserted_flag = ingest_health(
                    store, body, subject_id=subject_id, now=now_fn()
                )
            except (CollectorError, ConflictingEvent):
                self._reply(400, _counts_body(0, 0))
                return
            if inserted_flag:
                self._reply(201, _counts_body(1, 1))
            else:
                self._reply(200, _counts_body(0, 1))

        def _handle_screen_hour(self) -> None:
            try:
                body = self._read_body()
            except _BodyTooLarge:
                self._reply(413, b"")
                return
            if body is None:
                self._reply(400, _counts_body(0, 0))
                return
            try:
                inserted, noop = ingest_screen_hours(store, body, now=now_fn())
            except (CollectorError, ConflictingEvent):
                self._reply(400, _counts_body(0, 0))
                return
            total = inserted + noop
            if inserted:
                self._reply(201, _counts_body(inserted, total))
            else:
                self._reply(200, _counts_body(inserted, total))

        def _read_body(self) -> bytes | None:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                return None
            if length < 0:
                return None
            if length > MAX_BODY_BYTES:
                raise _BodyTooLarge
            try:
                return self.rfile.read(length)
            except (OSError, ValueError):
                return None

        def _reply(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return None

    return IngestHandler


def serve_ingest(host: str, port: int, db_path: Path | None) -> None:
    """Serve both ingest routes; refuse to start without INGEST_TOKEN."""
    token = os.environ.get("INGEST_TOKEN")
    if not token:
        raise CollectorError("ingest: INGEST_TOKEN is not set")
    with EventStore(db_path) as store:
        handler = make_ingest_handler(
            store,
            subject_id=subject_id_from_env(),
            now_fn=lambda: datetime.now(UTC),
            token=token,
        )
        server = HTTPServer((host, port), handler)
        server.serve_forever()
