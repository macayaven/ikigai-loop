"""CLI: run one collector against the store, printing only counts (ticket 5)."""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from framework.collectors.build_feed import BuildFeedCollector
from framework.collectors.calendar_ics import CalendarIcsCollector
from framework.collectors.common import CollectorError, HttpGet, urllib_http_get
from framework.collectors.github_events import GitHubEventsCollector
from framework.store import EventStore, run_collector
from framework.store.collector import Collector

NAMES = ("calendar", "github", "feed")


def build_collector(
    name: str,
    http_get: HttpGet = urllib_http_get,
    now_fn: Callable[[], datetime] | None = None,
) -> Collector:
    """Build one wave-1 collector by CLI name."""
    if name not in NAMES:
        raise ValueError(f"unknown collector: {name}")
    makers = {
        "calendar": CalendarIcsCollector,
        "github": GitHubEventsCollector,
        "feed": BuildFeedCollector,
    }
    cls = makers[name]
    if now_fn is None:
        return cls(http_get=http_get)
    return cls(http_get=http_get, now_fn=now_fn)


def main(
    argv: list[str] | None = None,
    *,
    http_get: HttpGet = urllib_http_get,
    now_fn: Callable[[], datetime] | None = None,
    db_path: Path | None = None,
) -> int:
    """Run one collector via run_collector; print only the counts line."""
    parser = argparse.ArgumentParser(
        prog="framework.collectors",
        description="Run one wave-1 collector against the event store.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Poll once and record the result.")
    run_parser.add_argument("name", choices=list(NAMES))
    args = parser.parse_args(argv)
    collector = build_collector(args.name, http_get, now_fn)
    try:
        with EventStore(db_path) as store:
            inserted, conflicts = run_collector(store, collector)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"inserted={inserted} conflicts={conflicts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
