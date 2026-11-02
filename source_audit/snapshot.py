"""Strict snapshot reading driven by one field-shape table."""

from __future__ import annotations

import json
from typing import Any

from source_audit.export import EVENT_RE, LOGIN_RE, REPO_RE, SHA_RE
from source_audit.recount import parse_instant

SNAPSHOT_KEYS = {
    "fetched_at",
    "user",
    "repo",
    "events",
    "pulls",
    "activity",
    "coverage",
}
COVER_KEYS = {"events", "pulls", "activity"}
BLOCK_KEYS = {"rows", "oldest", "newest", "stop"}
STOPS = {"last_page", "empty_page", "github_pagination_refusal", "page_cap"}

FIELDS = {
    "events": {
        "id": "event",
        "type": "text",
        "repo": "repo",
        "actor": "?login",
        "created_at": "instant",
        "action": "?str",
        "pr_number": "?uint",
        "push_id": "?uint",
        "head": "?sha",
        "before": "?sha",
    },
    "pulls": {"number": "uint", "created_at": "instant", "author": "?login"},
    "activity": {
        "id": "text",
        "timestamp": "instant",
        "activity_type": "text",
        "before": "?sha",
        "after": "?sha",
        "actor": "?login",
    },
}


class SnapshotError(Exception):
    """A snapshot I cannot trust; the CLI prints SNAPSHOT_INVALID."""

    def __init__(self) -> None:
        super().__init__("SNAPSHOT_INVALID")
        self.code = "SNAPSHOT_INVALID"


def _is_instant(value: Any) -> bool:
    """Check an instant parses as aware."""
    try:
        parse_instant(value)
    except (ValueError, TypeError):
        return False
    return True


def _ok(shape: str, value: Any) -> bool:
    """Check one field against its shape; ?-shapes allow null."""
    if value is None:
        return shape.startswith("?")
    core = shape.removeprefix("?")
    if core == "event":
        return isinstance(value, str) and EVENT_RE.fullmatch(value) is not None
    if core == "text":
        return isinstance(value, str) and bool(value)
    if core == "str":
        return isinstance(value, str)
    if core == "repo":
        return isinstance(value, str) and REPO_RE.fullmatch(value) is not None
    if core == "login":
        return isinstance(value, str) and LOGIN_RE.fullmatch(value) is not None
    if core == "instant":
        return _is_instant(value)
    if core == "uint":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0
    if core == "sha":
        return isinstance(value, str) and SHA_RE.fullmatch(value) is not None
    return False


def _check_row(kind: str, row: Any) -> None:
    """Check one row against its field-shape table."""
    want = FIELDS[kind]
    if not isinstance(row, dict) or set(row) != set(want):
        raise SnapshotError
    if any(not _ok(shape, row[field]) for field, shape in want.items()):
        raise SnapshotError


def _check_coverage(coverage: Any) -> None:
    """Check the coverage block against the allowlist shape."""
    if not isinstance(coverage, dict) or set(coverage) != COVER_KEYS:
        raise SnapshotError
    for block in coverage.values():
        if not isinstance(block, dict) or set(block) != BLOCK_KEYS:
            raise SnapshotError
        if not _ok("uint", block["rows"]) or block["stop"] not in STOPS:
            raise SnapshotError
        if (block["oldest"] is not None or block["newest"] is not None) and (
            not _is_instant(block["oldest"]) or not _is_instant(block["newest"])
        ):
            raise SnapshotError


def load_snapshot(path: Any) -> dict[str, Any]:
    """Read and strictly validate a snapshot file."""
    try:
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        raise SnapshotError from None
    return validate_snapshot(raw)


def validate_snapshot(raw: Any) -> dict[str, Any]:
    """Strictly validate a decoded snapshot object."""
    if not isinstance(raw, dict) or set(raw) != SNAPSHOT_KEYS:
        raise SnapshotError
    if not _ok("login", raw["user"]) or not _ok("repo", raw["repo"]):
        raise SnapshotError
    if not _is_instant(raw["fetched_at"]):
        raise SnapshotError
    for kind in ("events", "pulls", "activity"):
        if not isinstance(raw[kind], list):
            raise SnapshotError
        for row in raw[kind]:
            _check_row(kind, row)
    _check_coverage(raw["coverage"])
    return raw
