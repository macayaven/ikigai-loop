"""Shared HTTP, env, clock, and id helpers for collectors (ticket 5)."""

import hashlib
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class HttpResponse:
    """One HTTP result with lower-cased header keys."""

    status: int
    headers: dict[str, str]
    body: bytes


HttpGet = Callable[[str, dict[str, str]], HttpResponse]


def as_dict(value: Any) -> dict[str, Any] | None:
    """Narrow an opaque JSON value to a str-keyed dict, else None."""
    if isinstance(value, dict):
        return cast("dict[str, Any]", value)
    return None


def as_list(value: Any) -> list[Any] | None:
    """Narrow an opaque JSON value to a list, else None."""
    if isinstance(value, list):
        return cast("list[Any]", value)
    return None


class CollectorError(Exception):
    """A poll failure. Messages never contain a URL, a header value, or a body."""


def urllib_http_get(url: str, headers: dict[str, str]) -> HttpResponse:
    """Fetch with stdlib urllib; HTTPError becomes a response, the rest a CollectorError."""
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15.0) as response:
            raw_headers = response.headers
            return HttpResponse(
                status=int(response.status),
                headers={k.lower(): v for k, v in raw_headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        raw = exc.headers or {}
        return HttpResponse(
            status=int(exc.code),
            headers={k.lower(): v for k, v in raw.items()},
            body=exc.read(),
        )
    except (urllib.error.URLError, OSError, TimeoutError):
        raise CollectorError("network error") from None


def subject_id_from_env() -> str:
    """Return IKIGAI_SUBJECT_ID, defaulting to the published placeholder."""
    return os.environ.get("IKIGAI_SUBJECT_ID") or "subject-1"


def event_id(source: str, source_id: str) -> str:
    """Deterministic opaque id so collectors stay replayable."""
    digest = hashlib.sha256(f"{source}\x00{source_id}".encode()).hexdigest()
    return "evt_" + digest[:32]
