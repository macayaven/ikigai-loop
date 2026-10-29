"""Collectors wave 1 + wave 2: Calendar, GitHub, feed, Spotify, ActivityWatch (ticket 7)."""

from framework.collectors.activitywatch import ActivityWatchCollector
from framework.collectors.build_feed import BuildFeedCollector
from framework.collectors.calendar_ics import CalendarIcsCollector
from framework.collectors.common import (
    CollectorError,
    HttpPost,
    HttpResponse,
)
from framework.collectors.github_events import GitHubEventsCollector
from framework.collectors.ingest import (
    ingest_health,
    ingest_screen_hours,
    parse_health_event,
    parse_screen_hour_events,
)
from framework.collectors.spotify import SpotifyCollector

__all__ = [
    "ActivityWatchCollector",
    "BuildFeedCollector",
    "CalendarIcsCollector",
    "CollectorError",
    "GitHubEventsCollector",
    "HttpPost",
    "HttpResponse",
    "SpotifyCollector",
    "ingest_health",
    "ingest_screen_hours",
    "parse_health_event",
    "parse_screen_hour_events",
]
