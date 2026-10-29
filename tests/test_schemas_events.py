"""Ticket 3: Event envelope round-trips and rejections (synthetic subject-1)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from framework.schemas import Event

NOW = datetime(2026, 10, 29, 18, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 29, 19, 0, tzinfo=UTC)

CAL = {
    "start": NOW,
    "end": LATER,
    "busy": True,
    "category": "synthetic-category",
    "tags": ["synthetic"],
    "is_new": True,
}

CASES: list[tuple[str, str, dict[str, object]]] = [
    ("calendar.event.created", "private", {"type": "calendar.event.created", **CAL}),
    ("calendar.event.updated", "private", {"type": "calendar.event.updated", **CAL}),
    (
        "calendar.event.cancelled",
        "private",
        {"type": "calendar.event.cancelled", **CAL},
    ),
    (
        "github.push",
        "public",
        {"type": "github.push", "repo": "synthetic/repo", "counts": {"commits": 2}},
    ),
    (
        "github.pr",
        "public",
        {"type": "github.pr", "repo": "synthetic/repo", "counts": {"opened": 1}},
    ),
    (
        "github.issue",
        "public",
        {"type": "github.issue", "repo": "synthetic/repo", "counts": {"closed": 1}},
    ),
    (
        "github.release",
        "public",
        {
            "type": "github.release",
            "repo": "synthetic/repo",
            "counts": {"published": 1},
        },
    ),
    (
        "feed.item",
        "public",
        {
            "type": "feed.item",
            "title": "Synthetic item",
            "url": "https://example.invalid/item",
            "source": "synthetic-feed",
            "score": 1.5,
        },
    ),
    (
        "music.play",
        "private",
        {
            "type": "music.play",
            "track": "Synthetic Track",
            "artist": "Synthetic Artist",
            "played_at": NOW,
        },
    ),
    (
        "health.daily",
        "sensitive",
        {
            "type": "health.daily",
            "sleep_h": 7.0,
            "resting_hr": 60.0,
            "hrv_ms": 40.0,
            "steps": 8000,
            "exercise_min": 30.0,
            "mindful_min": 5.0,
            "mood_valence": 0.5,
        },
    ),
    (
        "screen.hour",
        "private",
        {"type": "screen.hour", "device": "mac", "minutes_by_category": {"code": 45.0}},
    ),
    (
        "editor.hour",
        "private",
        {
            "type": "editor.hour",
            "project": "synthetic-project",
            "language": "python",
            "minutes": 30.0,
        },
    ),
    (
        "jobs.snapshot",
        "private",
        {
            "type": "jobs.snapshot",
            "counts": {"applied": 3, "screen": 1, "interview": 0, "offer": 0},
        },
    ),
    (
        "app.view",
        "private",
        {"type": "app.view", "block_id": "checklist#synthetic", "screen": None},
    ),
    (
        "app.tap",
        "private",
        {
            "type": "app.tap",
            "block_id": "checklist#synthetic",
            "target": "synthetic-target",
        },
    ),
    (
        "app.thumb",
        "private",
        {"type": "app.thumb", "block_id": "insight#synthetic", "value": 1},
    ),
    ("app.rating", "private", {"type": "app.rating", "block_id": None, "value": 4.0}),
    (
        "app.approve",
        "private",
        {"type": "app.approve", "manifest_version": "synthetic-v1", "card_id": None},
    ),
    (
        "app.reject",
        "private",
        {"type": "app.reject", "manifest_version": "synthetic-v1", "card_id": "card-1"},
    ),
    ("app.checkin", "private", {"type": "app.checkin", "energy": 3}),
    (
        "app.journal",
        "sensitive",
        {"type": "app.journal", "text": "Synthetic journal text."},
    ),
]


def envelope(event_type: str, tier: str, data: dict[str, object]) -> dict[str, object]:
    return {
        "id": "evt_synthetic_1",
        "subject_id": "subject-1",
        "source": "synthetic",
        "type": event_type,
        "time": NOW,
        "source_id": "synthetic-1",
        "data": data,
        "tier": tier,
        "collected_at": NOW,
        "collector_version": "synthetic@0.1.0",
    }


@pytest.mark.parametrize(("event_type", "tier", "data"), CASES)
def test_event_round_trip(event_type: str, tier: str, data: dict[str, object]) -> None:
    event = Event.model_validate(envelope(event_type, tier, data))
    assert event.type == event_type
    assert Event.model_validate(event.model_dump()) == event
    assert Event.model_validate_json(event.model_dump_json()) == event


def test_health_daily_all_metrics_none_round_trip() -> None:
    data: dict[str, object] = {
        "type": "health.daily",
        "sleep_h": None,
        "resting_hr": None,
        "hrv_ms": None,
        "steps": None,
        "exercise_min": None,
        "mindful_min": None,
        "mood_valence": None,
    }
    event = Event.model_validate(envelope("health.daily", "sensitive", data))
    assert Event.model_validate_json(event.model_dump_json()) == event


def test_event_is_frozen() -> None:
    event = Event.model_validate(envelope(*CASES[0]))
    with pytest.raises(ValidationError):
        event.tier = "public"  # type: ignore[misc]


def test_reject_extra_field() -> None:
    raw = envelope(*CASES[0])
    raw["unexpected"] = "nope"
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_reject_unknown_type() -> None:
    raw = envelope(
        "calendar.event.moved", "private", {"type": "calendar.event.moved", **CAL}
    )
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_reject_type_mismatch() -> None:
    raw = envelope(
        "github.push",
        "public",
        {"type": "github.pr", "repo": "synthetic/repo", "counts": {}},
    )
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_reject_calendar_title() -> None:
    raw = envelope(
        "calendar.event.created",
        "private",
        {"type": "calendar.event.created", **CAL, "title": "Secret title"},
    )
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_calendar_models_have_no_title_field() -> None:
    from framework.schemas import (
        CalendarEventCancelledData,
        CalendarEventCreatedData,
        CalendarEventUpdatedData,
    )

    for model in (
        CalendarEventCreatedData,
        CalendarEventUpdatedData,
        CalendarEventCancelledData,
    ):
        assert "title" not in model.model_fields
        assert "title" not in model.model_json_schema()["properties"]


def test_reject_health_not_sensitive() -> None:
    event_type, _, data = CASES[9]
    with pytest.raises(ValidationError):
        Event.model_validate(envelope(event_type, "private", data))


def test_reject_journal_not_sensitive() -> None:
    event_type, _, data = CASES[-1]
    with pytest.raises(ValidationError):
        Event.model_validate(envelope(event_type, "private", data))


@pytest.mark.parametrize("energy", [0, 6])
def test_reject_checkin_energy_out_of_range(energy: int) -> None:
    with pytest.raises(ValidationError):
        Event.model_validate(
            envelope(
                "app.checkin", "private", {"type": "app.checkin", "energy": energy}
            )
        )


def test_reject_naive_datetime() -> None:
    raw = envelope(*CASES[0])
    raw["time"] = datetime(2026, 10, 29, 18, 0)
    with pytest.raises(ValidationError):
        Event.model_validate(raw)


def test_reject_mood_valence_out_of_range() -> None:
    data: dict[str, object] = {"type": "health.daily", "mood_valence": 2.0}
    with pytest.raises(ValidationError):
        Event.model_validate(envelope("health.daily", "sensitive", data))
