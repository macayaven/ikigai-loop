"""Public build feed collector: HF papers, HN stories, new repos (ticket 5)."""

import json
import os
import urllib.error
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from framework.collectors.common import (
    CollectorError,
    HttpGet,
    as_dict,
    as_list,
    event_id,
    subject_id_from_env,
    urllib_http_get,
)
from framework.schemas import Event, FeedItemData

MADRID = ZoneInfo("Europe/Madrid")
HF_URL = "https://huggingface.co/api/daily_papers"
HN_LIST_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "ikigai-loop",
}


class BuildFeedCollector:
    """One poll over three public feeds; each item emitted once per Madrid day."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http_get = http_get
        self._now_fn = now_fn
        self.name = "feed"
        self.version = "feed@0.1.0"

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        now = self._now_fn()
        today = now.astimezone(MADRID).date().isoformat()
        subject_id = subject_id_from_env()
        token = os.environ.get("GITHUB_TOKEN")

        candidates = [
            *self._fetch_hf(),
            *self._fetch_hn(),
            *self._fetch_github_search(today, token),
        ]

        emitted_today: set[str] = set()
        cursor_dict = as_dict(cursor)
        if cursor_dict is not None and cursor_dict.get("day") == today:
            raw_emitted = as_list(cursor_dict.get("emitted"))
            if raw_emitted is not None:
                emitted_today = {str(k) for k in raw_emitted}

        events: list[Event] = []
        new_keys: set[str] = set()
        for data_source, item_id, title, url, score in candidates:
            key = f"{data_source}:{item_id}"
            if key in emitted_today or key in new_keys:
                continue
            new_keys.add(key)
            payload = FeedItemData(
                title=title, url=url, source=data_source, score=score
            )
            source_id = f"{key}@{today}"
            events.append(
                Event(
                    id=event_id("feed", source_id),
                    subject_id=subject_id,
                    source="feed",
                    type="feed.item",
                    time=now,
                    source_id=source_id,
                    data=payload,
                    tier="public",
                    collected_at=now,
                    collector_version=self.version,
                )
            )
        return events, {"day": today, "emitted": sorted(emitted_today | new_keys)}

    def _get(self, url: str, headers: dict[str, str]) -> Any:
        try:
            response = self._http_get(url, headers)
        except CollectorError:
            raise CollectorError("feed: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError("feed: network error") from None
        if response.status != 200:
            raise CollectorError(f"feed: fetch failed (status {response.status})")
        try:
            return json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("feed: invalid response") from None

    def _fetch_hf(self) -> list[tuple[str, str, str, str, float]]:
        body = as_list(self._get(HF_URL, {}))
        if body is None:
            raise CollectorError("feed: invalid response") from None
        items: list[tuple[str, str, str, str, float]] = []
        for raw_item in body:
            item = as_dict(raw_item)
            if item is None:
                continue
            paper = as_dict(item.get("paper"))
            if paper is None:
                continue
            paper_id = paper.get("id")
            title = paper.get("title")
            if paper_id is None or title is None:
                continue
            try:
                score = float(paper.get("upvotes") or 0)
            except (TypeError, ValueError):
                continue
            items.append(
                (
                    "hf",
                    str(paper_id),
                    str(title),
                    f"https://huggingface.co/papers/{paper_id}",
                    score,
                )
            )
        return items

    def _fetch_hn(self) -> list[tuple[str, str, str, str, float]]:
        body = as_list(self._get(HN_LIST_URL, {}))
        if body is None:
            raise CollectorError("feed: invalid response") from None
        items: list[tuple[str, str, str, str, float]] = []
        for raw_id in body[:30]:
            story = as_dict(self._get(HN_ITEM_URL.format(item_id=raw_id), {}))
            if story is None:
                continue
            if story.get("deleted") is True or story.get("dead") is True:
                continue
            title = story.get("title")
            if title is None:
                continue
            try:
                score = float(story.get("score") or 0)
            except (TypeError, ValueError):
                continue
            raw_url = story.get("url")
            url = (
                str(raw_url)
                if raw_url
                else f"https://news.ycombinator.com/item?id={raw_id}"
            )
            items.append(("hn", str(raw_id), str(title), url, score))
        return items

    def _fetch_github_search(
        self, today: str, token: str | None
    ) -> list[tuple[str, str, str, str, float]]:
        since = (datetime.fromisoformat(today).date() - timedelta(days=7)).isoformat()
        query = urllib.parse.urlencode(
            {
                "q": f"created:>={since}",
                "sort": "stars",
                "order": "desc",
                "per_page": "30",
            }
        )
        headers = dict(GITHUB_HEADERS)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        body = as_dict(self._get(f"{GITHUB_SEARCH_URL}?{query}", headers))
        if body is None:
            raise CollectorError("feed: invalid response") from None
        raw_items = as_list(body.get("items") or [])
        if raw_items is None:
            raise CollectorError("feed: invalid response") from None
        items: list[tuple[str, str, str, str, float]] = []
        for raw_repo in raw_items[:30]:
            repo = as_dict(raw_repo)
            if repo is None:
                continue
            repo_id = repo.get("id")
            full_name = repo.get("full_name")
            html_url = repo.get("html_url")
            if repo_id is None or full_name is None or html_url is None:
                continue
            try:
                score = float(repo.get("stargazers_count") or 0)
            except (TypeError, ValueError):
                continue
            items.append(("github", str(repo_id), str(full_name), str(html_url), score))
        return items
