"""Ticket 5: GitHub events collector tests on synthetic fixtures only."""

import json
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from framework.collectors import GitHubEventsCollector
from framework.collectors.common import CollectorError, HttpResponse
from framework.schemas import Event
from framework.store import EventStore, run_collector

NOW = datetime.fromisoformat("2026-10-30T12:00:00+01:00")
GITHUB_USER = "synthetic-user"
TOKEN = "synthetic-token-abc"


def entry(
    event_id: str,
    kind: str,
    repo: str,
    payload: dict[str, Any],
    created_at: str = "2026-10-29T10:00:00Z",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": kind,
        "repo": {"name": repo},
        "payload": payload,
        "created_at": created_at,
    }


ENTRIES = [
    entry("1001", "PushEvent", "synthetic/push-repo", {"size": 3}),
    entry("1002", "PushEvent", "synthetic/push-repo", {"commits": [{}, {}]}),
    entry(
        "1003",
        "PullRequestEvent",
        "synthetic/pr-repo",
        {"action": "closed", "pull_request": {"merged": True}},
    ),
    entry(
        "1004",
        "PullRequestEvent",
        "synthetic/pr-repo",
        {"action": "closed", "pull_request": {"merged": False}},
    ),
    entry(
        "1005",
        "PullRequestEvent",
        "synthetic/pr-repo",
        {"action": "opened", "pull_request": {"merged": False}},
    ),
    entry("1006", "IssuesEvent", "synthetic/issue-repo", {"action": "opened"}),
    entry("1007", "ReleaseEvent", "synthetic/release-repo", {"action": "published"}),
    entry("2001", "PushEvent", "someone/ikigai-loop", {"size": 1}),
    entry("2002", "IssuesEvent", "ikigai-loop", {"action": "opened"}),
    entry("2003", "WatchEvent", "synthetic/other-repo", {"action": "started"}),
]


def make_http_get(
    entries: list[dict[str, Any]],
    *,
    status: int = 200,
    etag: str | None = '"synthetic-etag-1"',
    seen: dict[str, Any] | None = None,
    answer_304: bool = False,
) -> Any:
    def fake(url: str, headers: dict[str, str]) -> HttpResponse:
        assert url == (
            f"https://api.github.com/users/{GITHUB_USER}/events?per_page=100"
        ), f"unexpected URL: {url}"
        if seen is not None:
            seen.setdefault("headers", []).append(dict(headers))
        if answer_304:
            return HttpResponse(status=304, headers={}, body=b"")
        response_headers = {"etag": etag} if etag is not None else {}
        return HttpResponse(
            status=status,
            headers=response_headers,
            body=json.dumps(entries).encode("utf-8"),
        )

    return fake


def poll_once(
    monkeypatch: pytest.MonkeyPatch,
    http_get: Any,
    cursor: Any = None,
    *,
    token: str | None = None,
) -> tuple[list[Event], Any]:
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    if token is None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    else:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = GitHubEventsCollector(http_get=http_get, now_fn=lambda: NOW)
    return collector.poll(cursor)


@pytest.fixture
def store(tmp_path: Path) -> Generator[EventStore, None, None]:
    owned = EventStore(tmp_path / "events.db")
    yield owned
    owned.close()


def test_push_pr_issue_release_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, cursor = poll_once(monkeypatch, make_http_get(ENTRIES))
    by_id = {e.source_id: e for e in events}
    assert set(by_id) == {"1001", "1002", "1003", "1004", "1005", "1006", "1007"}
    assert by_id["1001"].type == "github.push"
    assert by_id["1001"].data.counts == {"commits": 3}  # type: ignore[attr-defined]
    assert by_id["1001"].data.repo == "synthetic/push-repo"  # type: ignore[attr-defined]
    assert by_id["1002"].data.counts == {"commits": 2}  # type: ignore[attr-defined]
    assert by_id["1003"].type == "github.pr"
    assert by_id["1003"].data.counts == {"merged": 1}  # type: ignore[attr-defined]
    assert by_id["1004"].data.counts == {"closed": 1}  # type: ignore[attr-defined]
    assert by_id["1005"].data.counts == {"opened": 1}  # type: ignore[attr-defined]
    assert by_id["1006"].type == "github.issue"
    assert by_id["1006"].data.counts == {"opened": 1}  # type: ignore[attr-defined]
    assert by_id["1007"].type == "github.release"
    assert by_id["1007"].data.counts == {"published": 1}  # type: ignore[attr-defined]
    for event in events:
        assert event.tier == "public"
        assert event.source == "github"
        assert event.collector_version == "github@0.1.0"
        assert event.time == datetime.fromisoformat("2026-10-29T10:00:00+00:00")
    assert cursor == {"etag": '"synthetic-etag-1"'}


def test_ikigai_loop_and_unknown_types_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, _ = poll_once(monkeypatch, make_http_get(ENTRIES))
    repos = [e.data.repo for e in events]  # type: ignore[attr-defined]
    assert not any(r.rsplit("/", 1)[-1] == "ikigai-loop" for r in repos)
    assert all(e.type != "WatchEvent" for e in events)
    assert len(events) == 7


def test_etag_second_poll_returns_no_events(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    first = GitHubEventsCollector(
        http_get=make_http_get(ENTRIES, seen=seen), now_fn=lambda: NOW
    )
    assert run_collector(store, first) == (7, 0)
    cursor = store.get_cursor("github")
    assert cursor == {"etag": '"synthetic-etag-1"'}

    second = GitHubEventsCollector(
        http_get=make_http_get(ENTRIES, seen=seen, answer_304=True),
        now_fn=lambda: NOW,
    )
    assert run_collector(store, second) == (0, 0)
    assert store.get_cursor("github") == cursor
    assert seen["headers"][1].get("If-None-Match") == '"synthetic-etag-1"'


def test_auth_header_only_when_token_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    poll_once(monkeypatch, make_http_get(ENTRIES, seen=seen))
    assert "Authorization" not in seen["headers"][0]

    seen2: dict[str, Any] = {}
    poll_once(monkeypatch, make_http_get(ENTRIES, seen=seen2), token=TOKEN)
    assert seen2["headers"][0]["Authorization"] == f"Bearer {TOKEN}"


def test_missing_user_and_fetch_failure(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    monkeypatch.delenv("GITHUB_USER", raising=False)
    collector = GitHubEventsCollector(
        http_get=make_http_get(ENTRIES), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError, match="GITHUB_USER is not set"):
        collector.poll(None)

    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    failing = GitHubEventsCollector(
        http_get=make_http_get([], status=500), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError, match="status 500"):
        run_collector(store, failing)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("github") is None


def test_github_poll_writes_nothing_on_network_error(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    def broken(url: str, headers: dict[str, str]) -> HttpResponse:
        raise OSError("synthetic network failure")

    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    collector = GitHubEventsCollector(http_get=broken, now_fn=lambda: NOW)
    with pytest.raises(CollectorError):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("github") is None
