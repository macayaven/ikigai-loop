"""Ticket 7: ActivityWatch collector tests (buckets, AFK, categories, push)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import pytest

from framework.collectors.activitywatch import (
    ActivityWatchCollector,
    _classify,
    push_events,
)
from framework.collectors.common import CollectorError, HttpResponse
from framework.store import EventStore

NOW = datetime(2026, 10, 30, 12, 30, tzinfo=UTC)
WINDOW_START = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
WINDOW_END = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)

BASE = "http://127.0.0.1:5600"
BUCKETS_URL = f"{BASE}/api/0/buckets/"

TITLE_DECOY = "Synthetic secret window title"
URL_DECOY = "https://example.invalid/secret-page"

INGEST_URL = "https://example.invalid/ingest"
INGEST_TOKEN = "synthetic-ingest-token"


def window_event(
    app: str, timestamp: str, duration: float, title: str = TITLE_DECOY
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "duration": duration,
        "data": {"app": app, "title": title, "url": URL_DECOY},
    }


def afk_event(status: str, timestamp: str, duration: float) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "duration": duration,
        "data": {"status": status},
    }


class FakeAw:
    """Fake ActivityWatch keyed by exact URL; asserts the trailing-slash buckets URL."""

    def __init__(
        self,
        buckets: dict[str, Any],
        events: dict[str, list[dict[str, Any]]],
        status: int = 200,
    ) -> None:
        self.buckets = buckets
        self.events = events
        self.status = status
        self.calls: list[str] = []

    def events_url(self, bucket_id: str) -> str:
        query = urlencode(
            {
                "start": WINDOW_START.isoformat(),
                "end": WINDOW_END.isoformat(),
                "limit": -1,
            }
        )
        return f"{BASE}/api/0/buckets/{quote(bucket_id, safe='')}/events?{query}"

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append(url)
        if url == BUCKETS_URL:
            assert url.endswith("/api/0/buckets/"), f"missing slash: {url}"
            return HttpResponse(
                status=self.status, headers={}, body=json.dumps(self.buckets).encode()
            )
        for bucket_id, items in self.events.items():
            if url == self.events_url(bucket_id):
                return HttpResponse(
                    status=self.status,
                    headers={},
                    body=json.dumps(items).encode(),
                )
        raise AssertionError(f"unexpected AW URL: {url}")


def buckets_with(
    *,
    window: bool = True,
    afk: bool = True,
    screentime: bool = True,
) -> dict[str, Any]:
    buckets: dict[str, Any] = {}
    if window:
        buckets["aw-watcher-window-synthetic"] = {"id": "aw-watcher-window-synthetic"}
    if afk:
        buckets["aw-watcher-afk-synthetic"] = {"id": "aw-watcher-afk-synthetic"}
    if screentime:
        buckets["screentime-import-synthetic"] = {"id": "screentime-import-synthetic"}
    return buckets


def collect_with(fake: FakeAw, now: datetime = NOW) -> list[Any]:
    collector = ActivityWatchCollector(http_get=fake, now_fn=lambda: now)
    return collector.collect(now)


def test_buckets_url_has_trailing_slash() -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [],
            "aw-watcher-afk-synthetic": [],
            "screentime-import-synthetic": [],
        },
    )
    assert collect_with(fake) == []
    assert fake.calls[0] == BUCKETS_URL
    assert fake.calls[0].endswith("/api/0/buckets/")


def test_afk_clip_partial_overlap_counts_only_overlap() -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:15:00+00:00", 1800.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 1800.0),
                afk_event("afk", "2026-10-30T11:30:00+00:00", 1800.0),
            ],
            "screentime-import-synthetic": [],
        },
    )
    events = collect_with(fake)
    assert len(events) == 1
    assert events[0].time == datetime(2026, 10, 30, 11, 0, tzinfo=UTC)
    assert events[0].data.minutes_by_category == {"code": 15.0}  # type: ignore[union-attr]


def test_afk_time_counts_zero() -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:35:00+00:00", 600.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 1800.0),
                afk_event("afk", "2026-10-30T11:30:00+00:00", 1800.0),
            ],
            "screentime-import-synthetic": [],
        },
    )
    assert collect_with(fake) == []


def test_split_event_across_hour_boundary_inside_not_afk() -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Slack", "2026-10-30T10:30:00+00:00", 3600.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T10:00:00+00:00", 7200.0)
            ],
            "screentime-import-synthetic": [],
        },
    )
    events = collect_with(fake)
    assert len(events) == 2
    by_hour = {e.time: e.data.minutes_by_category for e in events}  # type: ignore[union-attr]
    assert by_hour[datetime(2026, 10, 30, 10, 0, tzinfo=UTC)] == {"comms": 30.0}
    assert by_hour[datetime(2026, 10, 30, 11, 0, tzinfo=UTC)] == {"comms": 30.0}


def test_iphone_as_is_without_afk_bucket() -> None:
    fake = FakeAw(
        buckets_with(afk=False),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "screentime-import-synthetic": [
                window_event("Safari", "2026-10-30T11:00:00+00:00", 900.0)
            ],
        },
    )
    events = collect_with(fake)
    assert len(events) == 1
    assert events[0].data.device == "iphone"  # type: ignore[union-attr]
    assert events[0].data.minutes_by_category == {"browse": 15.0}  # type: ignore[union-attr]


def test_missing_afk_bucket_yields_zero_mac_minutes() -> None:
    fake = FakeAw(
        buckets_with(afk=False),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "screentime-import-synthetic": [],
        },
    )
    assert collect_with(fake) == []


def test_aggregate_minutes_by_category_per_device_hour() -> None:
    fake = FakeAw(
        buckets_with(screentime=False),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0),
                window_event("Slack", "2026-10-30T11:00:00+00:00", 1800.0),
                window_event("Safari", "2026-10-30T11:00:00+00:00", 900.0),
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
        },
    )
    events = collect_with(fake)
    assert len(events) == 1
    event = events[0]
    assert event.source == "activitywatch"
    assert event.type == "screen.hour"
    assert event.tier == "private"
    assert event.data.minutes_by_category == {  # type: ignore[union-attr]
        "code": 60.0,
        "comms": 30.0,
        "browse": 15.0,
    }
    assert event.time == datetime(2026, 10, 30, 11, 0, tzinfo=UTC)
    assert event.source_id.startswith("mac:2026-10-30T11:00:00+00:00:")


def test_category_table_order_skip_and_bundle_ids() -> None:
    fake = FakeAw(
        buckets_with(screentime=False),
        {
            "aw-watcher-window-synthetic": [
                window_event("loginwindow", "2026-10-30T11:00:00+00:00", 3600.0),
                window_event("Reddit", "2026-10-30T11:00:00+00:00", 900.0),
                window_event("Spotify", "2026-10-30T11:00:00+00:00", 900.0),
                window_event(
                    "Synthetic Unknown App", "2026-10-30T11:00:00+00:00", 900.0
                ),
                window_event("com.apple.MobileSMS", "2026-10-30T11:00:00+00:00", 900.0),
                window_event("com.tweetie2", "2026-10-30T11:00:00+00:00", 900.0),
                window_event("CodeMusic", "2026-10-30T11:00:00+00:00", 900.0),
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
        },
    )
    events = collect_with(fake)
    assert len(events) == 1
    assert events[0].data.minutes_by_category == {  # type: ignore[union-attr]
        "code": 15.0,
        "comms": 15.0,
        "feed": 30.0,
        "media": 15.0,
        "other": 15.0,
    }


def test_title_absent_from_pushed_and_stored_payloads(tmp_path: Path) -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "screentime-import-synthetic": [],
        },
    )
    events = collect_with(fake)
    pushed = json.dumps([e.model_dump(mode="json") for e in events])
    assert TITLE_DECOY not in pushed
    with EventStore(tmp_path / "aw.db") as store:
        store.append_events(events)
        stored = store.events_between(
            "subject-1", WINDOW_START, WINDOW_END + timedelta(hours=1)
        )
    stored_json = json.dumps([e.model_dump(mode="json") for e in stored])
    assert TITLE_DECOY not in stored_json
    assert not hasattr(events[0].data, "title")


def test_url_absent_from_pushed_and_stored_payloads(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Safari", "2026-10-30T11:00:00+00:00", 900.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "screentime-import-synthetic": [],
        },
    )
    with caplog.at_level("INFO"):
        events = collect_with(fake)
    pushed = json.dumps([e.model_dump(mode="json") for e in events])
    assert URL_DECOY not in pushed
    assert not hasattr(events[0].data, "url")
    for record in caplog.records:
        assert URL_DECOY not in record.getMessage()
        assert TITLE_DECOY not in record.getMessage()


def test_stateless_window_rederives_identical_source_ids() -> None:
    fixture = {
        "aw-watcher-window-synthetic": [
            window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0)
        ],
        "aw-watcher-afk-synthetic": [
            afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
        ],
        "screentime-import-synthetic": [],
    }
    first = collect_with(FakeAw(buckets_with(), fixture))
    second = collect_with(FakeAw(buckets_with(), fixture))
    assert [e.source_id for e in first] == [e.source_id for e in second]
    assert not hasattr(ActivityWatchCollector, "poll")


def test_late_data_mints_new_source_id_for_same_hour() -> None:
    base_events = {
        "aw-watcher-window-synthetic": [
            window_event("Code", "2026-10-30T11:00:00+00:00", 1800.0)
        ],
        "aw-watcher-afk-synthetic": [
            afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
        ],
        "screentime-import-synthetic": [],
    }
    late_events = {
        "aw-watcher-window-synthetic": [
            window_event("Code", "2026-10-30T11:00:00+00:00", 1800.0),
            window_event("Slack", "2026-10-30T11:30:00+00:00", 900.0),
        ],
        "aw-watcher-afk-synthetic": [
            afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
        ],
        "screentime-import-synthetic": [],
    }
    first = collect_with(FakeAw(buckets_with(), base_events))
    second = collect_with(FakeAw(buckets_with(), late_events))
    assert len(first) == len(second) == 1
    assert first[0].time == second[0].time
    assert first[0].source_id != second[0].source_id


def test_no_window_bucket_raises() -> None:
    fake = FakeAw(buckets_with(window=False), {})
    with pytest.raises(CollectorError, match="activitywatch: fetch failed"):
        collect_with(fake)


def test_no_screentime_bucket_succeeds_without_iphone() -> None:
    fake = FakeAw(
        buckets_with(screentime=False),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 900.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
        },
    )
    events = collect_with(fake)
    assert len(events) == 1
    assert events[0].data.device == "mac"  # type: ignore[union-attr]


def test_non_200_buckets_response_raises_before_build() -> None:
    fake = FakeAw(buckets_with(), {}, status=500)
    with pytest.raises(
        CollectorError, match=r"activitywatch: fetch failed \(status 500\)"
    ):
        collect_with(fake)
    assert fake.calls == [BUCKETS_URL]


def test_push_events_posts_list_with_bearer() -> None:
    from framework.schemas import Event, ScreenHourData

    event = Event(
        id="evt_synthetic_1",
        subject_id="subject-1",
        source="activitywatch",
        type="screen.hour",
        time=datetime(2026, 10, 30, 11, 0, tzinfo=UTC),
        source_id="mac:2026-10-30T11:00:00+00:00:deadbeef1234",
        data=ScreenHourData(device="mac", minutes_by_category={"code": 15.0}),
        tier="private",
        collected_at=NOW,
        collector_version="activitywatch@0.1.0",
    )
    seen: list[tuple[str, dict[str, str], bytes]] = []

    def fake_post(url: str, headers: dict[str, str], body: bytes) -> HttpResponse:
        seen.append((url, headers, body))
        assert url == f"{INGEST_URL}/events/screen-hour"
        assert headers["Authorization"] == f"Bearer {INGEST_TOKEN}"
        return HttpResponse(
            status=201,
            headers={},
            body=json.dumps({"inserted": 1, "total": 1}).encode(),
        )

    assert push_events(
        [event], ingest_url=INGEST_URL, token=INGEST_TOKEN, http_post=fake_post
    ) == (1, 0)
    sent = json.loads(seen[0][2])
    assert TITLE_DECOY not in seen[0][2].decode()
    assert len(sent) == 1


def test_push_events_non_2xx_raises_without_url_or_token() -> None:
    from framework.schemas import Event, ScreenHourData

    event = Event(
        id="evt_synthetic_1",
        subject_id="subject-1",
        source="activitywatch",
        type="screen.hour",
        time=datetime(2026, 10, 30, 11, 0, tzinfo=UTC),
        source_id="mac:2026-10-30T11:00:00+00:00:deadbeef1234",
        data=ScreenHourData(device="mac", minutes_by_category={"code": 15.0}),
        tier="private",
        collected_at=NOW,
        collector_version="activitywatch@0.1.0",
    )

    def failing_post(url: str, headers: dict[str, str], body: bytes) -> HttpResponse:
        return HttpResponse(status=500, headers={}, body=b"{}")

    with pytest.raises(
        CollectorError, match=r"activitywatch: fetch failed \(status 500\)"
    ) as excinfo:
        push_events(
            [event],
            ingest_url=INGEST_URL,
            token=INGEST_TOKEN,
            http_post=failing_post,
        )
    assert INGEST_URL not in str(excinfo.value)
    assert INGEST_TOKEN not in str(excinfo.value)


APP_CATEGORY_CASES: list[tuple[str, str]] = [
    # Ticket 7b: every added needle, plus the ordering pins.
    ("ChatGPT", "ai"),
    ("com.openai.chat", "ai"),
    ("Claude", "ai"),
    ("com.anthropic.claude", "ai"),
    ("Perplexity", "ai"),
    ("Gemini", "ai"),
    ("Copilot", "ai"),
    # A code editor whose name holds an ai needle still wins (ai is after code).
    ("Copilot.vim", "code"),
    ("Telegram", "comms"),
    ("ph.telegra.telegraph", "comms"),
    ("com.apple.systempreferences", "system"),
    ("Finder", "system"),
    ("System Settings", "system"),
    ("UserNotificationCenter", "system"),
    ("Shortcuts", "system"),
    ("Screen Sharing", "system"),
    ("Authenticator", "system"),
    ("1Password", "system"),
    ("SuperWhisper", "system"),
    # System is last, so these keep their earlier categories.
    ("com.apple.mobilesafari", "browse"),
    ("com.apple.mobilesms", "comms"),
    ("com.apple.music", "media"),
]


@pytest.mark.parametrize(("app", "category"), APP_CATEGORY_CASES)
def test_app_category_table(app: str, category: str) -> None:
    assert _classify(app) == category


def test_telegra_matches_nothing_else_in_table_cases() -> None:
    hits = [app for app, _ in APP_CATEGORY_CASES if "telegra" in app.lower()]
    assert hits == ["Telegram", "ph.telegra.telegraph"]


def _fresh_gate_case(
    text: str, refs: list[tuple[str, float]]
) -> tuple[dict[str, Any], Any]:
    import copy

    from evals.briefing_cases import base_case
    from framework.briefing.context import MetricSnapshot

    case = base_case("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = next(s for s in briefing["sections"] if s["type"] == "working")["claims"][0]
    claim["text"] = text
    claim["metric_refs"] = [
        {"metric_id": metric_id, "value": value} for metric_id, value in refs
    ]
    values = dict(case.context.metrics.values)
    for metric_id, value in refs:
        values[metric_id] = value
    context = case.context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    return briefing, context


@pytest.mark.parametrize(
    ("metric_id", "period", "labels"),
    [
        ("screen_hours.ai", None, frozenset({"ai"})),
        ("screen_hours.system", None, frozenset({"system"})),
        ("period.last.screen_hours.ai", "last", frozenset({"ai"})),
        ("period.last.screen_hours.system", "last", frozenset({"system"})),
    ],
)
def test_new_categories_bind_labels(
    metric_id: str, period: str | None, labels: frozenset[str]
) -> None:
    from framework.briefing.labels import metric_label_binding

    binding = metric_label_binding(metric_id)
    assert binding is not None, metric_id
    assert binding.labels == labels, metric_id
    assert binding.period == period, metric_id
    assert binding.family == metric_id.removeprefix("period.last."), metric_id
    assert binding.requires_cancel is False, metric_id


def test_ai_sentence_passes_gate() -> None:
    from framework.briefing.gate import evaluate_briefing

    briefing, context = _fresh_gate_case(
        "AI screen hours rose from 1 in prior to 2 in last.",
        [
            ("period.prior.screen_hours.ai", 1.0),
            ("period.last.screen_hours.ai", 2.0),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_system_sentence_passes_gate() -> None:
    from framework.briefing.gate import evaluate_briefing

    briefing, context = _fresh_gate_case(
        "System screen hours fell from 2 in prior to 1 in last.",
        [
            ("period.prior.screen_hours.system", 2.0),
            ("period.last.screen_hours.system", 1.0),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True


def test_no_uuid_shaped_string_in_source_ids() -> None:
    import re

    fake = FakeAw(
        buckets_with(),
        {
            "aw-watcher-window-synthetic": [
                window_event("Code", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "aw-watcher-afk-synthetic": [
                afk_event("not-afk", "2026-10-30T11:00:00+00:00", 3600.0)
            ],
            "screentime-import-synthetic": [
                window_event("Safari", "2026-10-30T11:00:00+00:00", 900.0)
            ],
        },
    )
    events = collect_with(fake)
    pattern = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}")
    for event in events:
        assert pattern.search(event.source_id) is None
