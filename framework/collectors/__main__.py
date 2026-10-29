"""CLI: run one collector, push ActivityWatch, or serve ingest (ticket 7)."""

import argparse
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from framework.collectors.activitywatch import (
    ActivityWatchCollector,
    push_events,
)
from framework.collectors.build_feed import BuildFeedCollector
from framework.collectors.calendar_ics import CalendarIcsCollector
from framework.collectors.common import (
    CollectorError,
    HttpGet,
    HttpPost,
    subject_id_from_env,
    urllib_http_get,
    urllib_http_post,
)
from framework.collectors.github_events import GitHubEventsCollector
from framework.collectors.ingest import ingest_health, serve_ingest
from framework.collectors.spotify import SpotifyCollector
from framework.store import EventStore, run_collector
from framework.store.collector import Collector

NAMES = ("calendar", "github", "feed", "spotify")


def build_collector(
    name: str,
    http_get: HttpGet = urllib_http_get,
    http_post: HttpPost = urllib_http_post,
    now_fn: Callable[[], datetime] | None = None,
    label: str = "personal",
) -> Collector:
    """Build one collector by CLI name (label applies to calendar only)."""
    if name == "calendar":
        if now_fn is None:
            return CalendarIcsCollector(http_get=http_get, label=label)
        return CalendarIcsCollector(http_get=http_get, now_fn=now_fn, label=label)
    if name == "spotify":
        if now_fn is None:
            return SpotifyCollector(http_get=http_get, http_post=http_post)
        return SpotifyCollector(http_get=http_get, http_post=http_post, now_fn=now_fn)
    if name not in ("github", "feed"):
        raise ValueError(f"unknown collector: {name}")
    cls = GitHubEventsCollector if name == "github" else BuildFeedCollector
    if now_fn is None:
        return cls(http_get=http_get)
    return cls(http_get=http_get, now_fn=now_fn)


def _run_one(
    name: str,
    http_get: HttpGet,
    http_post: HttpPost,
    now_fn: Callable[[], datetime] | None,
    label: str,
    db_path: Path | None,
) -> int:
    collector = build_collector(name, http_get, http_post, now_fn, label)
    try:
        with EventStore(db_path) as store:
            inserted, conflicts = run_collector(store, collector)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"inserted={inserted} conflicts={conflicts}")
    return 0


def _push_activitywatch(
    http_get: HttpGet,
    http_post: HttpPost,
    now_fn: Callable[[], datetime] | None,
) -> int:
    try:
        collector = ActivityWatchCollector(http_get=http_get, http_post=http_post)
        at = now_fn() if now_fn is not None else datetime.now(UTC)
        events = collector.collect(at)
        ingest_url = os.environ.get("INGEST_URL")
        if not ingest_url:
            raise CollectorError("activitywatch: INGEST_URL is not set")
        token = os.environ.get("INGEST_TOKEN")
        if not token:
            raise CollectorError("activitywatch: INGEST_TOKEN is not set")
        inserted, noop = push_events(
            events, ingest_url=ingest_url, token=token, http_post=http_post
        )
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"inserted={inserted} conflicts={noop}")
    return 0


def _ingest_health(
    path: str | None,
    now_fn: Callable[[], datetime] | None,
    db_path: Path | None,
) -> int:
    if path is not None:
        body = Path(path).read_bytes()
    else:
        body = sys.stdin.read().encode("utf-8")
    at = now_fn() if now_fn is not None else datetime.now(UTC)
    try:
        with EventStore(db_path) as store:
            inserted_flag = ingest_health(
                store, body, subject_id=subject_id_from_env(), now=at
            )
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if inserted_flag:
        print("inserted=1 conflicts=0")
    else:
        print("inserted=0 conflicts=0")
    return 0


def _serve_ingest(host: str, port: int, db_path: Path | None) -> int:
    try:
        serve_ingest(host, port, db_path)
    except CollectorError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def main(
    argv: list[str] | None = None,
    *,
    http_get: HttpGet = urllib_http_get,
    http_post: HttpPost = urllib_http_post,
    now_fn: Callable[[], datetime] | None = None,
    db_path: Path | None = None,
) -> int:
    """Run, push, ingest, or serve; print only counts or an error line."""
    parser = argparse.ArgumentParser(
        prog="framework.collectors",
        description="Run collectors and the ingest server.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="Poll once and record the result.")
    run_parser.add_argument("name", choices=list(NAMES))
    run_parser.add_argument(
        "--label", default=None, help="Calendar label (only with calendar)."
    )
    push_parser = sub.add_parser("push", help="Push local data to ingest.")
    push_parser.add_argument("name", choices=["activitywatch"])
    ingest_parser = sub.add_parser(
        "ingest-health", help="Store one Shortcut payload locally."
    )
    ingest_parser.add_argument("path", nargs="?", default=None)
    serve_parser = sub.add_parser("serve-ingest", help="Serve the ingest endpoints.")
    serve_parser.add_argument("--host", required=True)
    serve_parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.name != "calendar" and args.label is not None:
            parser.error("--label only applies to calendar")
        return _run_one(
            args.name, http_get, http_post, now_fn, args.label or "personal", db_path
        )
    if args.command == "push":
        return _push_activitywatch(http_get, http_post, now_fn)
    if args.command == "ingest-health":
        return _ingest_health(args.path, now_fn, db_path)
    return _serve_ingest(args.host, args.port, db_path)


if __name__ == "__main__":
    raise SystemExit(main())
