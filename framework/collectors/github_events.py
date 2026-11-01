"""GitHub collector over a user's public event stream (ticket 5)."""

import json
import os
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from framework.collectors.common import (
    CollectorError,
    HttpGet,
    as_dict,
    as_list,
    event_id,
    subject_id_from_env,
    urllib_http_get,
)
from framework.schemas import (
    Event,
    EventType,
    GitHubIssueData,
    GitHubPrData,
    GitHubPushData,
    GitHubReleaseData,
)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


class GitHubEventsCollector:
    """Poll GET /users/{user}/events; ETag in the cursor."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http_get = http_get
        self._now_fn = now_fn
        self.name = "github"
        self.version = "github@0.1.0"

    def poll(self, cursor: Any) -> tuple[list[Event], Any]:
        now = self._now_fn()
        user = os.environ.get("GITHUB_USER")
        if not user:
            raise CollectorError("github: GITHUB_USER is not set")
        token = os.environ.get("GITHUB_TOKEN")
        subject_id = subject_id_from_env()
        url = f"https://api.github.com/users/{user}/events?per_page=100"
        previous_etag: str | None = None
        cursor_dict = as_dict(cursor)
        if cursor_dict is not None:
            raw_etag = cursor_dict.get("etag")
            if isinstance(raw_etag, str):
                previous_etag = raw_etag
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ikigai-loop",
        }
        if previous_etag is not None:
            headers["If-None-Match"] = previous_etag
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._http_get(url, headers)
        except CollectorError:
            raise CollectorError("github: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError("github: network error") from None
        if response.status == 304:
            return [], cursor
        if response.status != 200:
            raise CollectorError(f"github: fetch failed (status {response.status})")
        try:
            body = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("github: invalid response") from None
        entries = as_list(body)
        if entries is None:
            raise CollectorError("github: invalid response") from None
        new_etag = response.headers.get("etag", previous_etag)

        events: list[Event] = []
        for raw_item in entries:
            event = self._map_entry(raw_item, subject_id, now)
            if event is not None:
                events.append(event)
        return events, {"etag": new_etag}

    def _map_entry(self, item: Any, subject_id: str, now: datetime) -> Event | None:
        entry = as_dict(item)
        if entry is None:
            return None
        raw_id = entry.get("id")
        repo = as_dict(entry.get("repo"))
        if raw_id is None or repo is None:
            return None
        repo_name = repo.get("name")
        if not isinstance(repo_name, str) or not repo_name:
            return None
        kind = entry.get("type")
        payload = as_dict(entry.get("payload"))
        if payload is None:
            payload = {}
        action = str(payload.get("action") or "unknown")
        moment = _parse_time(entry.get("created_at"))
        if moment is None:
            return None
        data: GitHubPushData | GitHubPrData | GitHubIssueData | GitHubReleaseData
        event_type: EventType
        if kind == "PushEvent":
            size = payload.get("size")
            commits = (
                size if isinstance(size, int) else len(payload.get("commits") or [])
            )
            data = GitHubPushData(repo=repo_name, counts={"commits": commits})
            event_type = "github.push"
        elif kind == "PullRequestEvent":
            pull_request = as_dict(payload.get("pull_request"))
            merged = pull_request is not None and pull_request.get("merged") is True
            if action == "closed" and merged:
                counts = {"merged": 1}
            else:
                counts = {action: 1}
            data = GitHubPrData(repo=repo_name, counts=counts)
            event_type = "github.pr"
        elif kind == "IssuesEvent":
            data = GitHubIssueData(repo=repo_name, counts={action: 1})
            event_type = "github.issue"
        elif kind == "ReleaseEvent":
            data = GitHubReleaseData(repo=repo_name, counts={action: 1})
            event_type = "github.release"
        else:
            return None
        source_id = str(raw_id)
        return Event(
            id=event_id("github", source_id),
            subject_id=subject_id,
            source="github",
            type=event_type,
            time=moment,
            source_id=source_id,
            data=data,
            tier="public",
            collected_at=now,
            collector_version=self.version,
        )
