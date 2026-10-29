"""Ticket 7: ingest server tests (health dating/hash, screen.hour batch, auth)."""

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.collectors.common import CollectorError
from framework.collectors.ingest import (
    ingest_health,
    ingest_screen_hours,
    make_ingest_handler,
    parse_health_event,
    parse_screen_hour_events,
)
from framework.schemas import Event, HealthDailyData, ScreenHourData
from framework.store.store import EventStore, canonical_json

MADRID = ZoneInfo("Europe/Madrid")
NOW = datetime(2026, 10, 30, 8, 0, tzinfo=MADRID)
DATE = "2026-10-29"

TOKEN = "synthetic-ingest-token"

FULL_PAYLOAD: dict[str, Any] = {
    "date": DATE,
    "sleep_h": 7.25,
    "resting_hr": 58.0,
    "hrv_ms": 42.5,
    "steps": 8234,
    "exercise_min": 31.0,
    "mindful_min": 10.0,
    "daylight_min": 95.0,
    "mood_valence": 0.4,
}


def expected_source_id(payload: dict[str, Any]) -> str:
    data = HealthDailyData.model_validate(
        {k: v for k, v in payload.items() if k != "date"}
    )
    digest = hashlib.sha256(
        canonical_json(data.model_dump(mode="json")).encode()
    ).hexdigest()[:12]
    return f"health:{payload['date']}:{digest}"


def screen_event(
    device: str, hour: str, minutes: dict[str, float], collected_at: str
) -> dict[str, Any]:
    from framework.collectors.common import event_id

    source_id = f"{device}:{hour}:synthetic-{device}-{hour}"
    return {
        "id": event_id("activitywatch", source_id),
        "subject_id": "subject-1",
        "source": "activitywatch",
        "type": "screen.hour",
        "time": hour,
        "source_id": source_id,
        "data": {
            "type": "screen.hour",
            "device": device,
            "minutes_by_category": minutes,
        },
        "tier": "private",
        "collected_at": collected_at,
        "collector_version": "activitywatch@0.1.0",
    }


def test_health_full_payload_with_daylight(tmp_path: Path) -> None:
    body = json.dumps(FULL_PAYLOAD).encode()
    event = parse_health_event(body, subject_id="subject-1", now=NOW)
    assert event.type == "health.daily"
    assert event.tier == "sensitive"
    assert event.source == "health"
    assert event.collector_version == "health@0.1.0"
    assert event.source_id == expected_source_id(FULL_PAYLOAD)
    assert event.time == datetime(2026, 10, 29, 0, 0, tzinfo=MADRID)
    assert event.collected_at == NOW
    assert isinstance(event.data, HealthDailyData)
    assert event.data.daylight_min == 95.0
    assert event.data.steps == 8234


def test_health_daylight_omitted_validates_none() -> None:
    payload = {k: v for k, v in FULL_PAYLOAD.items() if k != "daylight_min"}
    event = parse_health_event(
        json.dumps(payload).encode(), subject_id="subject-1", now=NOW
    )
    assert isinstance(event.data, HealthDailyData)
    assert event.data.daylight_min is None


def test_health_all_metrics_omitted_validates() -> None:
    event = parse_health_event(
        json.dumps({"date": DATE}).encode(), subject_id="subject-1", now=NOW
    )
    assert isinstance(event.data, HealthDailyData)
    assert event.data.sleep_h is None
    assert event.data.daylight_min is None


def test_health_repost_identical_is_noop(tmp_path: Path) -> None:
    body = json.dumps(FULL_PAYLOAD).encode()
    with EventStore(tmp_path / "health.db") as store:
        assert ingest_health(store, body, subject_id="subject-1", now=NOW) is True
        assert ingest_health(store, body, subject_id="subject-1", now=NOW) is False
        stored = store.events_between(
            "subject-1",
            datetime(2026, 10, 28, tzinfo=UTC),
            datetime(2026, 10, 30, tzinfo=UTC),
        )
        assert len(stored) == 1


def test_health_corrected_repost_supersedes(tmp_path: Path) -> None:
    first = json.dumps(FULL_PAYLOAD).encode()
    corrected = dict(FULL_PAYLOAD)
    corrected["steps"] = 9100
    second = json.dumps(corrected).encode()
    later = datetime(2026, 10, 30, 9, 0, tzinfo=MADRID)
    with EventStore(tmp_path / "health.db") as store:
        assert ingest_health(store, first, subject_id="subject-1", now=NOW) is True
        assert ingest_health(store, second, subject_id="subject-1", now=later) is True
        stored = store.events_between(
            "subject-1",
            datetime(2026, 10, 28, tzinfo=UTC),
            datetime(2026, 10, 30, tzinfo=UTC),
        )
        assert len(stored) == 2
        assert stored[0].source_id != stored[1].source_id
        latest = max(stored, key=lambda e: e.collected_at)
        assert isinstance(latest.data, HealthDailyData)
        assert latest.data.steps == 9100


def test_health_invalid_inputs_raise_and_write_nothing(tmp_path: Path) -> None:
    bad_bodies = [
        b"{not json",
        json.dumps({"sleep_h": 7.0}).encode(),
        json.dumps({"date": "29-10-2026", "sleep_h": 7.0}).encode(),
        json.dumps({**FULL_PAYLOAD, "mystery_metric": 1.0}).encode(),
        json.dumps({**FULL_PAYLOAD, "steps": -5}).encode(),
    ]
    with EventStore(tmp_path / "health.db") as store:
        for body in bad_bodies:
            with pytest.raises(CollectorError, match="health: invalid response"):
                ingest_health(store, body, subject_id="subject-1", now=NOW)
        assert (
            store.events_between(
                "subject-1",
                datetime(2026, 10, 28, tzinfo=UTC),
                datetime(2026, 10, 30, tzinfo=UTC),
            )
            == []
        )


def test_health_error_message_contains_no_metric_value() -> None:
    body = json.dumps({**FULL_PAYLOAD, "steps": -5}).encode()
    with pytest.raises(CollectorError) as excinfo:
        parse_health_event(body, subject_id="subject-1", now=NOW)
    assert "9100" not in str(excinfo.value)
    assert "-5" not in str(excinfo.value)


def valid_batch() -> list[dict[str, Any]]:
    return [
        screen_event(
            "mac",
            "2026-10-30T11:00:00+00:00",
            {"code": 30.0, "browse": 15.0},
            "2026-10-30T12:30:00+00:00",
        ),
        screen_event(
            "iphone",
            "2026-10-30T11:00:00+00:00",
            {"media": 20.0},
            "2026-10-30T12:30:00+00:00",
        ),
    ]


def test_screen_hour_batch_inserts_and_repush_is_noop(tmp_path: Path) -> None:
    body = json.dumps(valid_batch()).encode()
    with EventStore(tmp_path / "screen.db") as store:
        assert ingest_screen_hours(store, body, now=NOW) == (2, 0)
        assert ingest_screen_hours(store, body, now=NOW) == (0, 2)


def test_screen_hour_batch_with_invalid_item_writes_nothing(
    tmp_path: Path,
) -> None:
    good = valid_batch()
    variants: list[list[dict[str, Any]]] = []
    wrong_type = [dict(good[0], type="music.play")]
    variants.append(wrong_type)
    wrong_source = [dict(good[0], source="other-app")]
    variants.append(wrong_source)
    wrong_tier = [dict(good[0], tier="public")]
    variants.append(wrong_tier)
    malformed = [{"not": "an-event"}]
    variants.append(malformed)
    not_a_list = {"type": "screen.hour"}
    with EventStore(tmp_path / "screen.db") as store:
        with pytest.raises(CollectorError):
            parse_screen_hour_events(json.dumps(not_a_list).encode(), now=NOW)
        for batch in variants:
            with pytest.raises(CollectorError):
                ingest_screen_hours(store, json.dumps(batch).encode(), now=NOW)
        assert (
            store.events_between(
                "subject-1",
                datetime(2026, 10, 30, 10, tzinfo=UTC),
                datetime(2026, 10, 30, 13, tzinfo=UTC),
            )
            == []
        )


def test_screen_hour_counts_only_responses(tmp_path: Path) -> None:
    body = json.dumps(valid_batch()).encode()
    with EventStore(tmp_path / "screen.db") as store:
        inserted, noop = ingest_screen_hours(store, body, now=NOW)
        assert (inserted, noop) == (2, 0)
        events = parse_screen_hour_events(body, now=NOW)
        assert all(isinstance(e, Event) for e in events)
        assert all(e.type == "screen.hour" for e in events)


class FakeSocketRequest:
    """Minimal socket stand-in for BaseHTTPRequestHandler without binding."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self.sent = bytearray()

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        return io.BytesIO(self._raw)

    def sendall(self, data: bytes) -> None:
        self.sent += data


def drive_handler(
    store: EventStore,
    token: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: bytes,
    subject_id: str = "subject-1",
) -> tuple[int, bytes]:
    handler_cls = make_ingest_handler(
        store, subject_id=subject_id, now_fn=lambda: NOW, token=token
    )
    lines = [f"{method} {path} HTTP/1.1", "Host: synthetic.invalid"]
    for key, value in headers.items():
        lines.append(f"{key}: {value}")
    lines.append(f"Content-Length: {len(body)}")
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
    request = FakeSocketRequest(raw)
    handler_cls(request, ("127.0.0.1", 1), None)  # type: ignore[arg-type]
    raw_response = bytes(request.sent)
    status = int(raw_response.split(b" ", 2)[1])
    _, _, response_body = raw_response.partition(b"\r\n\r\n")
    return status, response_body


def test_ingest_handler_auth_rejects_and_writes_nothing(tmp_path: Path) -> None:
    body = json.dumps(FULL_PAYLOAD).encode()
    with EventStore(tmp_path / "ingest.db") as store:
        for path, payload in (
            ("/health/daily", body),
            ("/events/screen-hour", json.dumps(valid_batch()).encode()),
        ):
            status, _ = drive_handler(
                store,
                TOKEN,
                "POST",
                path,
                {"Authorization": "Bearer wrong-token"},
                payload,
            )
            assert status == 401
            status, _ = drive_handler(store, TOKEN, "POST", path, {}, payload)
            assert status == 401
        assert (
            store.events_between(
                "subject-1",
                datetime(2026, 10, 28, tzinfo=UTC),
                datetime(2026, 10, 31, tzinfo=UTC),
            )
            == []
        )


def test_ingest_handler_health_round_trip_counts_only(tmp_path: Path) -> None:
    body = json.dumps(FULL_PAYLOAD).encode()
    with EventStore(tmp_path / "ingest.db") as store:
        status, response = drive_handler(
            store,
            TOKEN,
            "POST",
            "/health/daily",
            {"Authorization": f"Bearer {TOKEN}"},
            body,
        )
        assert status == 201
        assert json.loads(response) == {"inserted": 1, "total": 1}
        assert b"8234" not in response
        status, response = drive_handler(
            store,
            TOKEN,
            "POST",
            "/health/daily",
            {"Authorization": f"Bearer {TOKEN}"},
            body,
        )
        assert status == 200
        assert json.loads(response) == {"inserted": 0, "total": 1}


def test_ingest_handler_unknown_path_is_404(tmp_path: Path) -> None:
    with EventStore(tmp_path / "ingest.db") as store:
        status, response = drive_handler(
            store,
            TOKEN,
            "POST",
            "/nope",
            {"Authorization": f"Bearer {TOKEN}"},
            b"{}",
        )
        assert status == 404
        assert response == b""


def test_ingest_handler_conflict_maps_to_400(tmp_path: Path) -> None:
    body = json.dumps(FULL_PAYLOAD).encode()
    with EventStore(tmp_path / "ingest.db") as store:
        first = parse_health_event(body, subject_id="subject-9", now=NOW)
        payload_no_date = {k: v for k, v in FULL_PAYLOAD.items() if k != "date"}
        altered = first.model_copy(
            update={
                "data": HealthDailyData.model_validate({**payload_no_date, "steps": 1})
            }
        )
        assert store.append_event(altered) is True
        status, _ = drive_handler(
            store,
            TOKEN,
            "POST",
            "/health/daily",
            {"Authorization": f"Bearer {TOKEN}"},
            body,
            subject_id="subject-9",
        )
        assert status == 400


def test_ingest_handler_screen_hour_counts_only(tmp_path: Path) -> None:
    body = json.dumps(valid_batch()).encode()
    with EventStore(tmp_path / "ingest.db") as store:
        status, response = drive_handler(
            store,
            TOKEN,
            "POST",
            "/events/screen-hour",
            {"Authorization": f"Bearer {TOKEN}"},
            body,
        )
        assert status == 201
        assert json.loads(response) == {"inserted": 2, "total": 2}
        status, response = drive_handler(
            store,
            TOKEN,
            "POST",
            "/events/screen-hour",
            {"Authorization": f"Bearer {TOKEN}"},
            body,
        )
        assert status == 200
        assert json.loads(response) == {"inserted": 0, "total": 2}
        bad = json.dumps([dict(valid_batch()[0], tier="public")]).encode()
        status, _ = drive_handler(
            store,
            TOKEN,
            "POST",
            "/events/screen-hour",
            {"Authorization": f"Bearer {TOKEN}"},
            bad,
        )
        assert status == 400
        stored = store.events_between(
            "subject-1",
            datetime(2026, 10, 30, 10, tzinfo=UTC),
            datetime(2026, 10, 30, 13, tzinfo=UTC),
        )
        assert len(stored) == 2
        assert ScreenHourData in [type(e.data) for e in stored]
