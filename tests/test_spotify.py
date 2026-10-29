"""Ticket 7: Spotify collector tests (refresh flow, mapping, cursor)."""

import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from framework.collectors.common import CollectorError, HttpResponse
from framework.collectors.spotify import SpotifyCollector
from framework.store import EventStore, run_collector

NOW = datetime.fromisoformat("2026-10-30T12:00:00+01:00")

TOKEN_URL = "https://accounts.spotify.com/api/token"
RECENT_BASE = "https://api.spotify.com/v1/me/player/recently-played?limit=50"

CLIENT_ID = "synthetic-client-id"
CLIENT_SECRET = "synthetic-client-secret"
REFRESH_TOKEN = "synthetic-refresh-token"
ACCESS_TOKEN = "synthetic-access-token"

PLAYS = [
    ("synthetic-track-1", "Synthetic Track One", "2026-10-30T10:00:00Z"),
    ("synthetic-track-2", "Synthetic Track Two", "2026-10-30T09:00:00Z"),
    ("synthetic-track-3", "Synthetic Track Three", "2026-10-30T08:00:00Z"),
]


def play_item(track_id: str, name: str, played_at: str) -> dict[str, Any]:
    return {
        "track": {
            "id": track_id,
            "name": name,
            "artists": [{"name": "Synthetic Artist"}],
        },
        "played_at": played_at,
    }


def recent_body(items: list[dict[str, Any]]) -> bytes:
    return json.dumps({"items": items}).encode("utf-8")


class FakeTokenPost:
    """Fake token endpoint; asserts URL, headers shape, and form keys."""

    def __init__(
        self,
        status: int = 200,
        body: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.body = (
            body
            if body is not None
            else {
                "access_token": ACCESS_TOKEN,
                "token_type": "Bearer",
                "expires_in": 3600,
            }
        )
        self.calls: list[tuple[str, dict[str, str], bytes]] = []

    def __call__(self, url: str, headers: dict[str, str], body: bytes) -> HttpResponse:
        self.calls.append((url, headers, body))
        assert url == TOKEN_URL, f"unexpected token URL: {url}"
        assert headers.get("Content-Type") == "application/x-www-form-urlencoded"
        return HttpResponse(
            status=self.status, headers={}, body=json.dumps(self.body).encode()
        )


def check_token_call(call: tuple[str, dict[str, str], bytes]) -> None:
    _, headers, body = call
    basic = headers.get("Authorization", "")
    assert basic.startswith("Basic ")
    decoded = base64.b64decode(basic[len("Basic ") :]).decode()
    assert decoded == f"{CLIENT_ID}:{CLIENT_SECRET}"
    form = parse_qs(body.decode())
    assert set(form) == {"grant_type", "refresh_token"}
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == [REFRESH_TOKEN]


class FakeRecentGet:
    """Fake recently-played endpoint; asserts the Bearer [REDACTED] filters by after."""

    def __init__(self, items: list[dict[str, Any]], status: int = 200) -> None:
        self.items = items
        self.status = status
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpResponse:
        self.calls.append((url, headers))
        assert headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"
        assert url.startswith(RECENT_BASE), f"unexpected URL: {url}"
        query = parse_qs(urlparse(url).query)
        after = query.get("after", [None])[0]
        items = self.items
        if after is not None:
            items = [
                item
                for item in items
                if int(
                    datetime.fromisoformat(str(item["played_at"])).timestamp() * 1000
                )
                > int(after)
            ]
        return HttpResponse(status=self.status, headers={}, body=recent_body(items))


def set_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", REFRESH_TOKEN)


def collector(http_get: Any, http_post: Any) -> SpotifyCollector:
    return SpotifyCollector(http_get=http_get, http_post=http_post, now_fn=lambda: NOW)


def test_refresh_posts_token_endpoint_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    get = FakeRecentGet([play_item(t, n, p) for t, n, p in PLAYS])
    events, cursor = collector(get, post).poll(None)
    assert len(post.calls) == 1
    check_token_call(post.calls[0])
    assert len(get.calls) == 1
    assert len(events) == 3
    assert cursor["after_ms"] == int(
        datetime(2026, 10, 30, 10, 0, tzinfo=UTC).timestamp() * 1000
    )


def test_token_endpoint_rotated_refresh_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost(
        body={
            "access_token": ACCESS_TOKEN,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "synthetic-rotated-token",
        }
    )
    get = FakeRecentGet([play_item(t, n, p) for t, n, p in PLAYS])
    first = collector(get, post)
    first.poll(None)
    second = collector(get, post)
    second.poll(None)
    assert len(post.calls) == 2
    for call in post.calls:
        check_token_call(call)
        assert b"synthetic-rotated-token" not in call[2]


def test_no_credential_or_token_in_events_cursor_or_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    get = FakeRecentGet([play_item(t, n, p) for t, n, p in PLAYS])
    with caplog.at_level("INFO"):
        events, cursor = collector(get, post).poll(None)
    blob = json.dumps(
        {
            "events": [e.model_dump(mode="json") for e in events],
            "cursor": cursor,
        }
    )
    for secret in (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN):
        assert secret not in blob
    for record in caplog.records:
        for secret in (CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN, ACCESS_TOKEN):
            assert secret not in record.getMessage()


def test_refresh_failed_status_raises_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost(status=401, body={})
    get = FakeRecentGet([])
    with EventStore(tmp_path / "spotify.db") as store:
        with pytest.raises(
            CollectorError, match=r"spotify: refresh failed \(status 401\)"
        ):
            run_collector(store, collector(get, post))
        assert store.get_cursor("spotify") is None
        assert get.calls == []
        assert (
            store.events_between(
                "subject-1",
                datetime(2026, 10, 29, tzinfo=UTC),
                datetime(2026, 10, 31, tzinfo=UTC),
            )
            == []
        )


def test_missing_credential_names_only_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post = FakeTokenPost()
    get = FakeRecentGet([])
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("SPOTIFY_REFRESH_TOKEN", REFRESH_TOKEN)
    with pytest.raises(CollectorError, match=r"spotify: SPOTIFY_CLIENT_ID is not set"):
        collector(get, post).poll(None)
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", CLIENT_ID)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    with pytest.raises(
        CollectorError, match=r"spotify: SPOTIFY_CLIENT_SECRET is not set"
    ):
        collector(get, post).poll(None)
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.delenv("SPOTIFY_REFRESH_TOKEN", raising=False)
    with pytest.raises(
        CollectorError, match=r"spotify: SPOTIFY_REFRESH_TOKEN is not set"
    ):
        collector(get, post).poll(None)
    assert post.calls == []
    assert get.calls == []


def test_mapping_returns_ascending_music_play_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    get = FakeRecentGet([play_item(t, n, p) for t, n, p in PLAYS])
    events, _ = collector(get, post).poll(None)
    assert [e.data.track for e in events] == [  # type: ignore[union-attr]
        "Synthetic Track Three",
        "Synthetic Track Two",
        "Synthetic Track One",
    ]
    first = events[0]
    assert first.source == "spotify"
    assert first.type == "music.play"
    assert first.tier == "private"
    assert first.collector_version == "spotify@0.1.0"
    assert first.source_id == "synthetic-track-3@2026-10-30T08:00:00+00:00"
    assert first.time == datetime(2026, 10, 30, 8, 0, tzinfo=UTC)
    assert first.collected_at == NOW


def test_cursor_emits_only_newer_plays_and_never_moves_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    items = [play_item(t, n, p) for t, n, p in PLAYS]
    get = FakeRecentGet(items)
    first_collector = collector(get, post)
    events, cursor = first_collector.poll(None)
    assert len(events) == 3
    after_ms = cursor["after_ms"]
    extended = [
        play_item("synthetic-track-4", "Synthetic Track Four", "2026-10-30T11:00:00Z"),
        *items,
    ]
    get2 = FakeRecentGet(extended)
    events2, cursor2 = collector(get2, post).poll(cursor)
    assert [e.source_id.split("@")[0] for e in events2] == ["synthetic-track-4"]
    assert cursor2["after_ms"] == int(
        datetime(2026, 10, 30, 11, 0, tzinfo=UTC).timestamp() * 1000
    )
    assert cursor2["after_ms"] > after_ms
    get3 = FakeRecentGet(extended)
    events3, cursor3 = collector(get3, post).poll(cursor2)
    assert events3 == []
    assert cursor3["after_ms"] == cursor2["after_ms"]
    assert f"after={cursor['after_ms']}" in get2.calls[0][0]


def test_skip_entries_without_artist_or_parseable_played_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    items = [
        play_item("synthetic-track-1", "Synthetic Track One", "2026-10-30T10:00:00Z"),
        {
            "track": {"id": "synthetic-track-x", "name": "No Artist Track"},
            "played_at": "2026-10-30T09:30:00Z",
        },
        {
            "track": {
                "id": "synthetic-track-y",
                "name": "Bad Time Track",
                "artists": [{"name": "Synthetic Artist"}],
            },
            "played_at": "not-a-time",
        },
        "not-a-dict",
        {"track": {"id": "synthetic-track-z"}, "played_at": "2026-10-30T09:00:00Z"},
    ]
    get = FakeRecentGet(items)
    events, _ = collector(get, post).poll(None)
    assert [e.source_id.split("@")[0] for e in events] == ["synthetic-track-1"]


def test_fetch_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    set_creds(monkeypatch)
    post = FakeTokenPost()
    get = FakeRecentGet([], status=500)
    with EventStore(tmp_path / "spotify.db") as store:
        with pytest.raises(
            CollectorError, match=r"spotify: fetch failed \(status 500\)"
        ):
            run_collector(store, collector(get, post))
        assert store.get_cursor("spotify") is None
