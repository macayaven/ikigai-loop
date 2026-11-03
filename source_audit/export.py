"""Allowlisted export shapes, the whole-export walk, and the atomic writer."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from source_audit.recount import parse_opt_instant

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]+(\[bot\])?$")
EVENT_RE = re.compile(r"^[0-9]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
CODE_RE = re.compile(r"^[A-Z0-9_]+$")
KEY_RE = re.compile(r"^[a-z][a-z0-9_.]*$")
STATUS_RE = re.compile(r"^(match|mismatch|unavailable)$")
METRIC_RE = re.compile(r"^(prs|pushes|pushes_plus_prs)$")
VERDICT_RE = re.compile(r"^(PASS|FAIL|INCOMPLETE)$")
EXPORT_KEYS = frozenset(
    {
        "metric",
        "stage",
        "status",
        "earlier",
        "prior",
        "last",
        "total",
        "codes",
        "verdict",
        "window_start",
        "window_end",
        "fetched_at",
        "feed_settled",
        "delivery_proven",
        "deltas_not_audited",
        "card_window",
        "per_repo",
        "open_hour",
        "coverage",
        "stages",
        "verdicts",
        "rows",
        "limits",
        "source",
        "oldest",
        "newest",
        "stop",
        "start",
        "end",
        "count",
        "activity_type",
        "pushes",
        "prs",
        "since_line",
        "stated",
        "recounted",
        "snapshot_diverges",
        "rows_counted",
        "rows_late",
        "rows_not_in_snapshot",
        "items_not_stored",
        "rows_unreadable",
        "activity_unmatched",
        "identifiers",
        "statements",
        "delta_codes",
        "item",
        "card",
        "actor",
        "event",
        "repo",
        "disagree",
        "duplicate",
        "item_not_stored",
        "other_repos_feed_only",
    }
)
COUNT_KEYS = frozenset(
    {
        "earlier",
        "prior",
        "last",
        "total",
        "rows_unreadable",
        "rows_counted",
        "rows_late",
        "rows_not_in_snapshot",
        "items_not_stored",
        "other_repos_feed_only",
        "activity_unmatched",
        "count",
        "stated",
        "recounted",
    }
)
NULLABLE = frozenset(
    {
        "window_start",
        "window_end",
        "fetched_at",
        "card_window",
        "oldest",
        "newest",
        "earlier",
        "prior",
        "last",
        "total",
        "rows_unreadable",
        "rows_counted",
        "rows_late",
        "rows_not_in_snapshot",
        "items_not_stored",
        "other_repos_feed_only",
        "activity_unmatched",
        "count",
        "stated",
        "recounted",
    }
)
_SHAPES = {
    "metric": METRIC_RE,
    "status": STATUS_RE,
    "verdict": VERDICT_RE,
    "actor": LOGIN_RE,
    "author": LOGIN_RE,
    "user": LOGIN_RE,
    "login": LOGIN_RE,
    "event": EVENT_RE,
    "event_id": EVENT_RE,
    "id": EVENT_RE,
    "sha": SHA_RE,
    "head": SHA_RE,
    "before": SHA_RE,
    "after": SHA_RE,
    "source": KEY_RE,
    "activity_type": KEY_RE,
}
_INSTANTS = (
    "fetched_at",
    "window_start",
    "window_end",
    "card_window",
    "oldest",
    "newest",
    "start",
    "end",
)


class ExportRefused(Exception):
    """The allowlist pass rejected the export; nothing was written."""

    def __init__(self) -> None:
        super().__init__("EXPORT_REFUSED")
        self.code = "EXPORT_REFUSED"


def _shape_ok(key: str, value: str) -> bool:
    """Check one export string against its shape."""
    if not value or any(ch.isspace() for ch in value):
        return False
    if key in _SHAPES:
        return _SHAPES[key].fullmatch(value) is not None
    if key == "stage":
        return value in ("1", "2", "3", "4")
    if key == "repo":
        return REPO_RE.fullmatch(value) is not None
    if key == "item":
        return _shape_ok("event", value) or _shape_ok("sha", value)
    if key in _INSTANTS:
        return parse_opt_instant(value) is not None and value.endswith("Z")
    return CODE_RE.fullmatch(value) is not None or KEY_RE.fullmatch(value) is not None


def _diverges(value: Any) -> bool:
    """Check a snapshot-diverges entry: a code or a non-empty list of keys."""
    if isinstance(value, str):
        return KEY_RE.fullmatch(value) is not None
    if isinstance(value, list):
        ok = [isinstance(i, str) and KEY_RE.fullmatch(i) for i in value]
        return bool(ok) and all(ok)
    return _walk(value)


def _pair(key: str, value: Any) -> bool:
    """Check one export entry; False on any unknown shape."""
    if not isinstance(key, str) or key not in EXPORT_KEYS:
        return False
    if key == "card":
        return isinstance(value, int) and not isinstance(value, bool)
    if key in ("feed_settled", "delivery_proven"):
        return isinstance(value, bool)
    if value is None:
        return key in NULLABLE
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return key != "activity_unmatched"
    if isinstance(value, str):
        return key not in COUNT_KEYS and _shape_ok(key, value)
    if key == "activity_unmatched":
        return isinstance(value, list) and _walk(value)
    if key == "snapshot_diverges":
        return _diverges(value)
    return key not in COUNT_KEYS and _walk(value)


def _item(item: Any) -> bool:
    """Check one export list item; False on any unknown shape."""
    if isinstance(item, bool):
        return False
    if isinstance(item, (dict, list)):
        return _walk(item)
    return isinstance(item, int) or (isinstance(item, str) and _shape_ok("code", item))


def _walk(node: Any) -> bool:
    """Allowlist-walk the whole export; False on any unknown shape."""
    if isinstance(node, dict):
        return all(_pair(k, v) for k, v in node.items())
    if isinstance(node, list):
        return all(_item(i) for i in node)
    return False


def check_export(payload: dict[str, Any]) -> None:
    """Allowlist-check the export, raising ExportRefused on any unknown shape."""
    if not isinstance(payload, dict) or not _walk(payload):
        raise ExportRefused


def write_export(path: Any, payload: dict[str, Any]) -> None:
    """Allowlist-check the export, then write it atomically."""
    check_export(payload)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    target, tmp = str(path), str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, target)
