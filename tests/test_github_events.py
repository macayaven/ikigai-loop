"""Ticket 5: GitHub events collector tests on synthetic fixtures only."""

import json
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from framework.collectors import GitHubEventsCollector
from framework.collectors.common import CollectorError, HttpResponse
from framework.glimmer.metrics import build_metric_snapshot
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
    assert set(by_id) == {
        "1001",
        "1002",
        "1003",
        "1004",
        "1005",
        "1006",
        "1007",
        "2001",
        "2002",
    }
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


def test_unknown_types_excluded_while_ikigai_loop_included(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, _ = poll_once(monkeypatch, make_http_get(ENTRIES))
    repos = [e.data.repo for e in events]  # type: ignore[attr-defined]
    assert "someone/ikigai-loop" in repos
    assert "ikigai-loop" in repos
    assert all(e.type != "WatchEvent" for e in events)
    assert len(events) == 9


def test_etag_second_poll_returns_no_events(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    first = GitHubEventsCollector(
        http_get=make_http_get(ENTRIES, seen=seen), now_fn=lambda: NOW
    )
    assert run_collector(store, first) == (9, 0)
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


PAGE1_URL = f"https://api.github.com/users/{GITHUB_USER}/events?per_page=100"
PAGE2_URL = PAGE1_URL + "&page=2"
PAGE3_URL = PAGE1_URL + "&page=3"


def link_next(url: str) -> str:
    return f'<{url}>; rel="next"'


def json_response(
    entries: Any,
    *,
    etag: str | None = None,
    link: str | None = None,
    status: int = 200,
) -> HttpResponse:
    headers: dict[str, str] = {}
    if etag is not None:
        headers["etag"] = etag
    if link is not None:
        headers["link"] = link
    body = entries if isinstance(entries, bytes) else json.dumps(entries).encode()
    return HttpResponse(status=status, headers=headers, body=body)


def make_paged_http_get(
    routes: dict[str, HttpResponse], seen: dict[str, Any] | None = None
) -> Any:
    def fake(url: str, headers: dict[str, str]) -> HttpResponse:
        if seen is not None:
            seen.setdefault("urls", []).append(url)
            seen.setdefault("headers", []).append(dict(headers))
        assert url in routes, f"unexpected request, nothing is sent there: {url}"
        return routes[url]

    return fake


def poll_paged(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[str, HttpResponse],
    seen: dict[str, Any],
    cursor: Any = None,
) -> tuple[list[Event], Any]:
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = GitHubEventsCollector(
        http_get=make_paged_http_get(routes, seen), now_fn=lambda: NOW
    )
    return collector.poll(cursor)


def test_github_follows_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page1 = [
        entry("9001", "PushEvent", "synthetic/push-repo", {}),
        entry("9002", "PushEvent", "synthetic/push-repo", {"size": 1}),
    ]
    page2 = [
        entry("9002", "PushEvent", "synthetic/push-repo", {"size": 1}),
        entry(
            "9003",
            "PullRequestEvent",
            "synthetic/pr-repo",
            {"action": "opened", "pull_request": {"merged": False}},
        ),
    ]
    page3 = [
        entry("9004", "IssuesEvent", "synthetic/issue-repo", {"action": "opened"}),
    ]
    routes = {
        PAGE1_URL: json_response(
            page1,
            etag='"page1-etag"',
            link=f'{link_next(PAGE2_URL)}, <{PAGE3_URL}>; rel="last"',
        ),
        PAGE2_URL: json_response(
            page2, etag='"page2-etag-ignored"', link=link_next(PAGE3_URL)
        ),
        PAGE3_URL: json_response(page3, etag='"page3-etag-ignored"'),
    }
    seen: dict[str, Any] = {}
    events, cursor = poll_paged(monkeypatch, routes, seen, {"etag": '"old-etag"'})
    assert [e.source_id for e in events] == ["9001", "9002", "9003", "9004"]
    assert seen["urls"] == [PAGE1_URL, PAGE2_URL, PAGE3_URL]
    assert seen["headers"][0].get("If-None-Match") == '"old-etag"'
    assert "If-None-Match" not in seen["headers"][1]
    assert "If-None-Match" not in seen["headers"][2]
    for request_headers in seen["headers"]:
        assert request_headers["Authorization"] == f"Bearer {TOKEN}"
    assert cursor == {"etag": '"page1-etag"'}
    by_id = {e.source_id: e for e in events}
    assert by_id["9001"].data.counts == {"commits": 0}  # type: ignore[attr-defined]
    snapshot = build_metric_snapshot(
        datetime.fromisoformat("2026-10-30T12:00:00+00:00"), [by_id["9001"]]
    )
    assert snapshot.values["github.push.count"] == 1.0


def test_github_pager_stops_when_no_link_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {
        PAGE1_URL: json_response(
            [entry("9101", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"e1"',
        )
    }
    seen: dict[str, Any] = {}
    events, cursor = poll_paged(monkeypatch, routes, seen)
    assert [e.source_id for e in events] == ["9101"]
    assert seen["urls"] == [PAGE1_URL]
    assert cursor == {"etag": '"e1"'}


def test_github_pager_stops_when_link_has_no_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {
        PAGE1_URL: json_response(
            [entry("9102", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"e1"',
            link=f'<{PAGE2_URL}>; rel="last"',
        )
    }
    seen: dict[str, Any] = {}
    events, cursor = poll_paged(monkeypatch, routes, seen)
    assert [e.source_id for e in events] == ["9102"]
    assert seen["urls"] == [PAGE1_URL]
    assert cursor == {"etag": '"e1"'}


def test_github_pager_stops_after_three_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {
        PAGE1_URL: json_response(
            [entry("9201", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"page1-etag"',
            link=link_next(PAGE2_URL),
        ),
        PAGE2_URL: json_response(
            [entry("9202", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"page2-etag-ignored"',
            link=link_next(PAGE3_URL),
        ),
        PAGE3_URL: json_response(
            [entry("9203", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"page3-etag-ignored"',
            link=link_next(PAGE3_URL + "&page=4"),
        ),
    }
    seen: dict[str, Any] = {}
    events, cursor = poll_paged(monkeypatch, routes, seen)
    assert [e.source_id for e in events] == ["9201", "9202", "9203"]
    assert seen["urls"] == [PAGE1_URL, PAGE2_URL, PAGE3_URL]
    assert cursor == {"etag": '"page1-etag"'}


@pytest.mark.parametrize(
    "page2",
    [
        json_response(
            [entry("9302", "PushEvent", "synthetic/x", {"size": 1})], status=500
        ),
        HttpResponse(status=200, headers={}, body=b"\xff\xfe{{{not json"),
        HttpResponse(status=200, headers={}, body=b'{"events": []}'),
    ],
    ids=["non-200", "undecodable", "not-a-list"],
)
def test_github_pager_later_page_failure_leaves_cursor(
    monkeypatch: pytest.MonkeyPatch, store: EventStore, page2: HttpResponse
) -> None:
    routes = {
        PAGE1_URL: json_response(
            [entry("9301", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"e1"',
            link=link_next(PAGE2_URL),
        ),
        PAGE2_URL: page2,
    }
    seen: dict[str, Any] = {}
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = GitHubEventsCollector(
        http_get=make_paged_http_get(routes, seen), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError):
        run_collector(store, collector)
    assert store.get_cursor("github") is None
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_github_pager_off_origin_next_raises(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    evil = "https://evil.example.com/users/synthetic-user/events?page=2"
    routes = {
        PAGE1_URL: json_response(
            [entry("9401", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"e1"',
            link=link_next(evil),
        ),
    }
    seen: dict[str, Any] = {}
    monkeypatch.setenv("GITHUB_USER", GITHUB_USER)
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = GitHubEventsCollector(
        http_get=make_paged_http_get(routes, seen), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError):
        run_collector(store, collector)
    assert seen["urls"] == [PAGE1_URL]
    assert store.get_cursor("github") is None
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_github_pager_http_next_same_host_is_off_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = "http://api.github.com/users/synthetic-user/events?per_page=100&page=2"
    routes = {
        PAGE1_URL: json_response(
            [entry("9501", "PushEvent", "synthetic/push-repo", {"size": 1})],
            etag='"e1"',
            link=link_next(plain),
        ),
    }
    seen: dict[str, Any] = {}
    with pytest.raises(CollectorError):
        poll_paged(monkeypatch, routes, seen)
    assert seen["urls"] == [PAGE1_URL]


def test_github_pager_304_first_page_returns_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes = {PAGE1_URL: HttpResponse(status=304, headers={}, body=b"")}
    seen: dict[str, Any] = {}
    events, cursor = poll_paged(monkeypatch, routes, seen, {"etag": '"old-etag"'})
    assert events == []
    assert cursor == {"etag": '"old-etag"'}
    assert seen["urls"] == [PAGE1_URL]
    assert seen["headers"][0].get("If-None-Match") == '"old-etag"'
