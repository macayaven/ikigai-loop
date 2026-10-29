"""Ticket 5: public build feed collector tests on synthetic fixtures only."""

import json
import urllib.parse
from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.collectors import BuildFeedCollector
from framework.collectors.common import CollectorError, HttpResponse
from framework.schemas import Event
from framework.store import EventStore, run_collector

NOW = datetime.fromisoformat("2026-10-30T12:00:00+01:00")

HF_URL = "https://huggingface.co/api/daily_papers"
HN_LIST_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"


def hn_item_url(item_id: int) -> str:
    return f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def github_search_url(since: str) -> str:
    query = urllib.parse.urlencode(
        {
            "q": f"created:>={since}",
            "sort": "stars",
            "order": "desc",
            "per_page": "30",
        }
    )
    return f"https://api.github.com/search/repositories?{query}"


def hf_entries(n: int = 2, upvotes: int = 42) -> list[dict[str, Any]]:
    return [
        {
            "paper": {
                "id": f"2610.{10000 + i:05d}",
                "title": f"Synthetic paper {i}",
                "upvotes": upvotes,
            }
        }
        for i in range(n)
    ]


def hn_item(item_id: int, score: int = 7) -> dict[str, Any]:
    return {"id": item_id, "title": f"Synthetic HN story {item_id}", "score": score}


def gh_repo(repo_id: int, stars: int = 11) -> dict[str, Any]:
    return {
        "id": repo_id,
        "full_name": f"synthetic-owner/synthetic-repo-{repo_id}",
        "html_url": f"https://example.invalid/synthetic-repo-{repo_id}",
        "stargazers_count": stars,
    }


def make_http_get(
    *,
    hf: list[dict[str, Any]] | None = None,
    hn_ids: list[int] | None = None,
    hn_items: dict[int, dict[str, Any]] | None = None,
    gh_items: list[dict[str, Any]] | None = None,
    fail_url: str | None = None,
    since: str = "2026-10-23",
    seen: dict[str, Any] | None = None,
) -> Any:
    hf = hf if hf is not None else hf_entries()
    hn_ids = hn_ids if hn_ids is not None else [9000, 9001]
    hn_items = hn_items if hn_items is not None else {i: hn_item(i) for i in hn_ids}
    gh_items = gh_items if gh_items is not None else [gh_repo(5000), gh_repo(5001)]
    mapping: dict[str, HttpResponse] = {
        HF_URL: HttpResponse(
            status=200, headers={}, body=json.dumps(hf).encode("utf-8")
        ),
        HN_LIST_URL: HttpResponse(
            status=200, headers={}, body=json.dumps(hn_ids).encode("utf-8")
        ),
        github_search_url(since): HttpResponse(
            status=200,
            headers={},
            body=json.dumps({"items": gh_items}).encode("utf-8"),
        ),
    }
    for item_id, item in hn_items.items():
        mapping[hn_item_url(item_id)] = HttpResponse(
            status=200, headers={}, body=json.dumps(item).encode("utf-8")
        )

    def fake(url: str, headers: dict[str, str]) -> HttpResponse:
        if seen is not None:
            seen.setdefault("urls", []).append(url)
        if url == fail_url:
            return HttpResponse(status=500, headers={}, body=b"{}")
        assert url in mapping, f"unexpected URL: {url}"
        return mapping[url]

    return fake


def poll_once(
    monkeypatch: pytest.MonkeyPatch,
    http_get: Any,
    cursor: Any = None,
    *,
    now: datetime = NOW,
) -> tuple[list[Event], Any]:
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = BuildFeedCollector(http_get=http_get, now_fn=lambda: now)
    return collector.poll(cursor)


@pytest.fixture
def store(tmp_path: Path) -> Generator[EventStore, None, None]:
    owned = EventStore(tmp_path / "events.db")
    yield owned
    owned.close()


def test_feed_item_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events, cursor = poll_once(monkeypatch, make_http_get())
    assert len(events) == 6
    hf_event = events[0]
    assert hf_event.type == "feed.item"
    assert hf_event.source == "feed"
    assert hf_event.tier == "public"
    assert hf_event.time == NOW
    assert hf_event.source_id == "hf:2610.10000@2026-10-30"
    assert hf_event.data.title == "Synthetic paper 0"  # type: ignore[attr-defined]
    assert hf_event.data.url == "https://huggingface.co/papers/2610.10000"  # type: ignore[attr-defined]
    assert hf_event.data.source == "hf"  # type: ignore[attr-defined]
    assert hf_event.data.score == 42.0  # type: ignore[attr-defined]

    hn_event = events[2]
    assert hn_event.source_id == "hn:9000@2026-10-30"
    assert hn_event.data.source == "hn"  # type: ignore[attr-defined]
    assert hn_event.data.title == "Synthetic HN story 9000"  # type: ignore[attr-defined]
    assert hn_event.data.url == "https://news.ycombinator.com/item?id=9000"  # type: ignore[attr-defined]

    gh_event = events[4]
    assert gh_event.source_id == "github:5000@2026-10-30"
    assert gh_event.data.source == "github"  # type: ignore[attr-defined]
    assert gh_event.data.title == "synthetic-owner/synthetic-repo-5000"  # type: ignore[attr-defined]
    assert gh_event.collector_version == "feed@0.1.0"
    assert cursor["day"] == "2026-10-30"
    assert len(cursor["emitted"]) == 6


def test_hn_and_github_search_capped_at_30(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hn_ids = list(range(9000, 9035))
    gh_items = [gh_repo(i) for i in range(5000, 5035)]
    events, _ = poll_once(
        monkeypatch,
        make_http_get(
            hn_ids=hn_ids, hn_items={i: hn_item(i) for i in hn_ids}, gh_items=gh_items
        ),
    )
    hn_events = [e for e in events if e.source_id.startswith("hn:")]
    gh_events = [e for e in events if e.source_id.startswith("github:")]
    assert len(hn_events) == 30
    assert len(gh_events) == 30
    assert hn_events[-1].source_id == "hn:9029@2026-10-30"
    assert gh_events[-1].source_id == "github:5029@2026-10-30"


def test_same_day_repoll_emits_nothing_next_day_reemits(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    first = BuildFeedCollector(http_get=make_http_get(), now_fn=lambda: NOW)
    assert run_collector(store, first) == (6, 0)

    rescored = BuildFeedCollector(
        http_get=make_http_get(hf=hf_entries(upvotes=99)),
        now_fn=lambda: NOW,
    )
    assert run_collector(store, rescored) == (0, 0)
    assert store._conn.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0] == 0

    next_day = NOW + timedelta(days=1)
    madrid_next = next_day.astimezone(ZoneInfo("Europe/Madrid")).date()
    assert madrid_next.isoformat() == "2026-10-31"
    since_next = (madrid_next - timedelta(days=7)).isoformat()
    third = BuildFeedCollector(
        http_get=make_http_get(since=since_next), now_fn=lambda: next_day
    )
    inserted, conflicts = run_collector(store, third)
    assert (inserted, conflicts) == (6, 0)
    stored = store.events_between(
        "subject-1",
        datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        datetime.fromisoformat("2027-01-01T00:00:00+00:00"),
    )
    assert len(stored) == 12
    assert all(e.source_id.endswith("@2026-10-31") for e in stored[6:])


def test_feed_subsource_failure_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, store: EventStore
) -> None:
    monkeypatch.delenv("IKIGAI_SUBJECT_ID", raising=False)
    collector = BuildFeedCollector(
        http_get=make_http_get(fail_url=HF_URL), now_fn=lambda: NOW
    )
    with pytest.raises(CollectorError):
        run_collector(store, collector)
    assert store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert store.get_cursor("feed") is None
