"""Public-by-construction fetching from three pinned endpoints."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from source_audit.export import LOGIN_RE
from source_audit.recount import fmt_utc, parse_opt_instant
from source_audit.snapshot import validate_snapshot

HOST = "api.github.com"
AGENT = "ikigai-loop-source-audit"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": AGENT}
EVENT_PAGES, PULL_PAGES, ACTIVITY_PAGES = 10, 10, 50


class FetchError(Exception):
    """A fetch failure carrying its closed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NetworkFailure(Exception):
    """A transport failure that is not an HTTP response."""


def _at(item: Any, *path: str) -> Any:
    """Walk nested dicts, returning None on any miss."""
    for key in path:
        if not isinstance(item, dict):
            return None
        item = item.get(key)
    return item


def _as_int(value: Any) -> int | None:
    """Keep an int, else None."""
    return value if isinstance(value, int) else None


COMMON = [
    ("id", ("id",), str),
    ("type", ("type",), None),
    ("repo", ("repo", "name"), None),
    ("actor", ("actor", "login"), None),
    ("created_at", ("created_at",), None),
]
PAYLOAD = {
    "PullRequestEvent": [
        ("action", ("action",), None),
        ("pr_number", ("number",), _as_int),
    ],
    "PushEvent": [
        ("push_id", ("push_id",), _as_int),
        ("head", ("head",), None),
        ("before", ("before",), None),
    ],
}
PROJECTION = {
    "pulls": [
        ("number", ("number",), None),
        ("created_at", ("created_at",), None),
        ("author", ("user", "login"), None),
    ],
    "activity": [
        ("id", ("id",), str),
        ("timestamp", ("timestamp",), None),
        ("activity_type", ("activity_type",), None),
        ("before", ("before",), None),
        ("after", ("after",), None),
        ("actor", ("actor", "login"), None),
    ],
}
BLANKS = {key: None for table in PAYLOAD.values() for key, _, _ in table}


def _row(item: dict, table: list) -> dict:
    """Project one raw row through a field table."""
    row = {}
    for key, path, fn in table:
        value = _at(item, *path)
        row[key] = fn(value) if fn else value
    return row


def _project(kind: str, item: dict[str, Any]) -> dict[str, Any] | None:
    """Project one raw row onto the allowlisted shape, or None to drop it."""
    if kind == "events":
        return _project_event(item)
    row = _row(item, PROJECTION[kind])
    bad_number = kind == "pulls" and not isinstance(row["number"], int)
    if bad_number or (kind == "activity" and "id" not in item):
        return None
    stamp = row["created_at"] if kind == "pulls" else row["timestamp"]
    if parse_opt_instant(stamp) is None:
        return None
    return row


def _project_event(item: dict[str, Any]) -> dict[str, Any] | None:
    """Project one raw feed row, dropping rows outside the allowlisted shape."""
    if not isinstance(_at(item, "repo", "name"), str):
        return None
    if parse_opt_instant(item.get("created_at")) is None:
        return None
    payload, ptype = item.get("payload") or {}, item.get("type")
    row = {
        **_row(item, COMMON),
        **BLANKS,
        **_row(payload, PAYLOAD.get(ptype, []) if isinstance(ptype, str) else []),
    }
    return row


def _get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    """Send one GET with a timeout; an HTTP error returns its response."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return (response.status, dict(response.headers), response.read())
    except urllib.error.HTTPError as exc:
        return (exc.code, dict(exc.headers or {}), exc.read())
    except Exception as exc:
        raise NetworkFailure(str(exc)) from exc


def _next_url(headers: dict[str, str]) -> str | None:
    """Return the rel=next URL from a Link header, if any."""
    link = next((v for k, v in headers.items() if k.lower() == "link"), "")
    for part in link.split(","):
        target, _, params = part.partition(";")
        target = target.strip()
        if not params or not (target.startswith("<") and target.endswith(">")):
            continue
        for name, _, value in (p.partition("=") for p in params.split(";")):
            if name.strip().lower() == "rel" and "next" in value.lower():
                return target[1:-1].strip() or None
    return None


def _walk(first: str, get: Callable, limit: int) -> tuple[list[Any], str]:
    """Follow one endpoint's next links; return rows and the stop reason."""
    rows, url, pages = [], first, 0
    while url is not None:
        try:
            status, headers, body = get(url, HEADERS)
        except FetchError:
            raise
        except Exception as exc:
            if pages == 0:
                raise FetchError("FETCH_FIRST_PAGE_FAILED") from exc
            return rows, "github_pagination_refusal"
        if status in (403, 429) and pages == 0:
            raise FetchError("FETCH_RATE_LIMITED")
        if status != 200 and pages == 0:
            raise FetchError("FETCH_FIRST_PAGE_FAILED")
        if status != 200:
            return rows, "github_pagination_refusal"
        try:
            page = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            page = None
        if not isinstance(page, list):
            if pages == 0:
                raise FetchError("FETCH_INVALID_RESPONSE")
            return rows, "github_pagination_refusal"
        pages += 1
        rows.extend(page)
        if (nxt := _next_url(headers)) is None:
            return rows, "last_page"
        try:
            target = urllib.parse.urlparse(nxt)
        except ValueError:
            return rows, "github_pagination_refusal"
        if target.scheme != "https" or target.hostname != HOST:
            return rows, "github_pagination_refusal"
        if not page:
            return rows, "empty_page"
        if pages >= limit:
            return rows, "page_cap"
        url = nxt
    return rows, "last_page"


def _cover(rows: list[Any], key: str, stop: str) -> dict[str, Any]:
    """Build one coverage block over every row the endpoint returned."""
    stamps = [
        r[key] for r in rows if isinstance(r, dict) and isinstance(r.get(key), str)
    ]
    out: dict[str, Any] = {"rows": len(rows)}
    out["oldest"] = min(stamps) if stamps else None
    out["newest"] = max(stamps) if stamps else None
    out["stop"] = stop
    return out


def run_fetch(
    user: str, repo: str, out: Any, http_get: Callable | None = None
) -> dict[str, Any]:
    """Fetch the three endpoints and atomically write the snapshot."""
    if not re.fullmatch(r"^[^/]+/[^/]+$", repo):
        raise FetchError("USAGE_BAD_REPO")
    if not isinstance(user, str) or not LOGIN_RE.fullmatch(user):
        raise FetchError("USAGE_BAD_USER")
    get = http_get if http_get is not None else _get
    fetched_at = fmt_utc(datetime.now(UTC))
    urls = (
        f"https://{HOST}/users/{user}/events/public?per_page=100",
        (
            f"https://{HOST}/repos/{repo}/pulls"
            "?state=all&sort=created&direction=desc&per_page=100"
        ),
        f"https://{HOST}/repos/{repo}/activity?per_page=100",
    )
    kinds = (
        ("events", "created_at", EVENT_PAGES),
        ("pulls", "created_at", PULL_PAGES),
        ("activity", "timestamp", ACTIVITY_PAGES),
    )
    rows, coverage = [], {}
    for url, (kind, stamp, limit) in zip(urls, kinds):
        raw, stop = _walk(url, get, limit)
        kept = [_project(kind, i) for i in raw if isinstance(i, dict)]
        rows.append([r for r in kept if r is not None])
        coverage[kind] = _cover(raw, stamp, stop)
    snapshot: dict[str, Any] = {
        "fetched_at": fetched_at,
        "user": user,
        "repo": repo,
        "events": rows[0],
        "pulls": rows[1],
        "activity": rows[2],
        "coverage": coverage,
    }
    validate_snapshot(snapshot)
    text = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    target, tmp = str(out), str(out) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, target)
    return snapshot
