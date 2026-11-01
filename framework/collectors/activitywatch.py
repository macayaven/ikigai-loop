"""ActivityWatch push source: per-category screen hours from the Mac (ticket 7).

Consumers take the latest ``collected_at`` per ``(device, hour)``: an
identical re-push re-derives the same ``source_id`` (a server-side no-op),
while late data mints a new ``source_id`` for the same hour that supersedes
by ``collected_at`` instead of conflicting.

Only per-category minutes leave this module. Window titles, URLs, and raw
app strings beyond the category mapping below never reach a pushed or stored
event, a log line, or an exception message.
"""

import hashlib
import json
import os
import urllib.error
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from framework.collectors.common import (
    CollectorError,
    HttpGet,
    HttpPost,
    HttpResponse,
    as_dict,
    as_list,
    event_id,
    subject_id_from_env,
    urllib_http_get,
    urllib_http_post,
)
from framework.schemas import Event, ScreenHourData

DEFAULT_BASE_URL = "http://127.0.0.1:5600"
WINDOW_HOURS = 48

SKIP_SUBSTRINGS = (
    "sleeplockscreen",
    "springboard",
    "control-center",
    "loginwindow",
    "screensaver",
)

CATEGORY_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "code",
        (
            "code",
            "cursor",
            "pycharm",
            "xcode",
            "iterm",
            "terminal",
            "ghostty",
            "warp",
            "vim",
            "emacs",
        ),
    ),
    (
        "ai",
        (
            "chatgpt",
            "com.openai",
            "claude",
            "com.anthropic",
            "perplexity",
            "gemini",
            "copilot",
        ),
    ),
    (
        "comms",
        (
            "slack",
            "discord",
            "zoom",
            "teams",
            "mail",
            "messages",
            "mobilesms",
            "mobilephone",
            "facetime",
            "incallservice",
            "whatsapp",
            "telegra",
        ),
    ),
    (
        "feed",
        ("tweetie2", "twitter", "reddit", "instagram", "tiktok", "linkedin"),
    ),
    (
        "browse",
        ("safari", "chrome", "firefox", "microsoft edge", "browser"),
    ),
    (
        "media",
        ("spotify", "music", "youtube", "vlc", "quicktime", "podcast", "netflix"),
    ),
    (
        "system",
        (
            "com.apple.",
            "finder",
            "system settings",
            "usernotificationcenter",
            "shortcuts",
            "screen sharing",
            "authenticator",
            "1password",
            "superwhisper",
        ),
    ),
)


def _classify(app: str) -> str | None:
    """Map a lower-cased app string to a category; None means skipped."""
    lowered = app.lower()
    for skipped in SKIP_SUBSTRINGS:
        if skipped in lowered:
            return None
    for category, needles in CATEGORY_TABLE:
        for needle in needles:
            if needle in lowered:
                return category
    return "other"


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed.astimezone(UTC)


def _parse_duration(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def _split_hours(start: datetime, end: datetime) -> dict[datetime, float]:
    """Split one counted span into UTC-hour buckets holding seconds."""
    out: dict[datetime, float] = {}
    cursor = start
    while cursor < end:
        hour = cursor.replace(minute=0, second=0, microsecond=0)
        chunk_end = min(hour + timedelta(hours=1), end)
        out[hour] = out.get(hour, 0.0) + (chunk_end - cursor).total_seconds()
        cursor = chunk_end
    return out


class ActivityWatchCollector:
    """Collect the last 48 complete UTC hours of per-category screen time."""

    def __init__(
        self,
        http_get: HttpGet = urllib_http_get,
        http_post: HttpPost = urllib_http_post,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._http_get = http_get
        self._http_post = http_post
        self._now_fn = now_fn
        self.name = "activitywatch"
        self.version = "activitywatch@0.2.0"

    def collect(self, now: datetime | None = None) -> list[Event]:
        """Build screen.hour events for the stateless 48 h window ending now."""
        at = now if now is not None else self._now_fn()
        base = os.environ.get("AW_BASE_URL") or DEFAULT_BASE_URL
        subject_id = subject_id_from_env()
        window_end = at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        window_start = window_end - timedelta(hours=WINDOW_HOURS)

        buckets = self._list_buckets(base)
        window_ids = sorted(b for b in buckets if b.startswith("aw-watcher-window"))
        if not window_ids:
            raise CollectorError("activitywatch: fetch failed (status 404)") from None
        afk_ids = sorted(b for b in buckets if b.startswith("aw-watcher-afk"))
        phone_ids = sorted(
            b
            for b in buckets
            if "screentime" in b.lower()
            or "screen-time" in b.lower()
            or "iphone" in b.lower()
        )

        start_iso = window_start.isoformat()
        end_iso = window_end.isoformat()
        not_afk: list[tuple[datetime, datetime]] = []
        for bucket_id in afk_ids:
            for raw in self._bucket_events(base, bucket_id, start_iso, end_iso):
                span = self._afk_span(raw)
                if span is not None:
                    not_afk.append(span)
        awake = _merge_intervals(not_afk)

        totals: dict[tuple[str, datetime, str], float] = {}
        for bucket_id in window_ids:
            self._accumulate(
                totals,
                "mac",
                self._bucket_events(base, bucket_id, start_iso, end_iso),
                awake,
                window_start,
                window_end,
                clip=True,
            )
        for bucket_id in phone_ids:
            self._accumulate(
                totals,
                "iphone",
                self._bucket_events(base, bucket_id, start_iso, end_iso),
                awake,
                window_start,
                window_end,
                clip=False,
            )

        per_hour: dict[tuple[str, datetime], dict[str, float]] = {}
        for (device, hour, category), minutes in totals.items():
            if minutes <= 0:
                continue
            per_hour.setdefault((device, hour), {})[category] = minutes

        events: list[Event] = []
        for (device, hour), minutes in per_hour.items():
            if not minutes:
                continue
            minutes_json = json.dumps(minutes, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(minutes_json.encode()).hexdigest()[:12]
            source_id = f"{device}:{hour.isoformat()}:{digest}"
            typed_device: Literal["mac", "iphone"] = (
                "mac" if device == "mac" else "iphone"
            )
            events.append(
                Event(
                    id=event_id("activitywatch", source_id),
                    subject_id=subject_id,
                    source="activitywatch",
                    type="screen.hour",
                    time=hour,
                    source_id=source_id,
                    data=ScreenHourData(
                        device=typed_device,
                        minutes_by_category=minutes,
                    ),
                    tier="private",
                    collected_at=at,
                    collector_version=self.version,
                )
            )
        events.sort(key=lambda e: (e.time, e.data.device))  # type: ignore[union-attr]
        return events

    def _get(self, url: str, headers: dict[str, str]) -> HttpResponse:
        try:
            return self._http_get(url, headers)
        except CollectorError:
            raise CollectorError("activitywatch: network error") from None
        except (urllib.error.URLError, OSError, TimeoutError):
            raise CollectorError("activitywatch: network error") from None

    def _list_buckets(self, base: str) -> dict[str, Any]:
        response = self._get(f"{base}/api/0/buckets/", {})
        if response.status != 200:
            raise CollectorError(
                f"activitywatch: fetch failed (status {response.status})"
            ) from None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("activitywatch: invalid response") from None
        buckets = as_dict(payload)
        if buckets is None:
            raise CollectorError("activitywatch: invalid response") from None
        return buckets

    def _bucket_events(
        self, base: str, bucket_id: str, start_iso: str, end_iso: str
    ) -> list[Any]:
        query = urllib.parse.urlencode(
            {"start": start_iso, "end": end_iso, "limit": -1}
        )
        segment = urllib.parse.quote(bucket_id, safe="")
        url = f"{base}/api/0/buckets/{segment}/events?{query}"
        response = self._get(url, {})
        if response.status != 200:
            raise CollectorError(
                f"activitywatch: fetch failed (status {response.status})"
            ) from None
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise CollectorError("activitywatch: invalid response") from None
        items = as_list(payload)
        if items is None:
            raise CollectorError("activitywatch: invalid response") from None
        return items

    def _afk_span(self, raw: Any) -> tuple[datetime, datetime] | None:
        item = as_dict(raw)
        if item is None:
            return None
        timestamp = _parse_ts(item.get("timestamp"))
        duration = _parse_duration(item.get("duration"))
        data = as_dict(item.get("data"))
        status = data.get("status") if data is not None else None
        if timestamp is None or duration is None or status != "not-afk":
            return None
        return (timestamp, timestamp + timedelta(seconds=duration))

    def _accumulate(
        self,
        totals: dict[tuple[str, datetime, str], float],
        device: str,
        items: list[Any],
        awake: list[tuple[datetime, datetime]],
        window_start: datetime,
        window_end: datetime,
        clip: bool,
    ) -> None:
        for raw in items:
            item = as_dict(raw)
            if item is None:
                continue
            timestamp = _parse_ts(item.get("timestamp"))
            duration = _parse_duration(item.get("duration"))
            data = as_dict(item.get("data"))
            app = data.get("app") if data is not None else None
            if timestamp is None or duration is None:
                continue
            if not isinstance(app, str) or not app:
                continue
            category = _classify(app)
            if category is None:
                continue
            span = (
                max(timestamp, window_start),
                min(timestamp + timedelta(seconds=duration), window_end),
            )
            if span[0] >= span[1]:
                continue
            segments = [(span[0], span[1])]
            if clip:
                segments = [
                    (max(span[0], awake_start), min(span[1], awake_end))
                    for awake_start, awake_end in awake
                    if max(span[0], awake_start) < min(span[1], awake_end)
                ]
            for seg_start, seg_end in segments:
                for hour, seconds in _split_hours(seg_start, seg_end).items():
                    key = (device, hour, category)
                    totals[key] = totals.get(key, 0.0) + seconds / 60


def push_events(
    events: list[Event],
    *,
    ingest_url: str,
    token: str,
    http_post: HttpPost,
) -> tuple[int, int]:
    """POST one screen.hour batch; return (inserted, server-side no-ops)."""
    body = json.dumps([e.model_dump(mode="json") for e in events]).encode()
    url = f"{ingest_url.rstrip('/')}/events/screen-hour"
    try:
        response = http_post(
            url,
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            body,
        )
    except CollectorError:
        raise CollectorError("activitywatch: network error") from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise CollectorError("activitywatch: network error") from None
    if response.status < 200 or response.status >= 300:
        raise CollectorError(
            f"activitywatch: fetch failed (status {response.status})"
        ) from None
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CollectorError("activitywatch: invalid response") from None
    counts = as_dict(payload)
    if counts is None:
        raise CollectorError("activitywatch: invalid response") from None
    inserted = counts.get("inserted")
    total = counts.get("total")
    if (
        isinstance(inserted, bool)
        or not isinstance(inserted, int)
        or isinstance(total, bool)
        or not isinstance(total, int)
        or inserted < 0
        or total < inserted
    ):
        raise CollectorError("activitywatch: invalid response") from None
    return (inserted, total - inserted)
