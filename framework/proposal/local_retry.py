"""Retry local start failures inside the propose deadline.

A ``muse exec`` call that dies in under two seconds never ran a model
request: the binary was missing, the box was busy, or the harness fell
over first. Those failures are retried after 5 s and again after 20 s,
while a real model failure, a timeout, or any slow run keeps today's
behaviour exactly. Every retried failure is recorded masked, so the
ledger keeps it in the denominators of the pre-registered R1.
"""

from __future__ import annotations

import os
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from framework.proposal.core import WonderClient, WonderRequest, WonderResponse
from framework.proposal.muse_client import LocalStartFailure

FIRST_RETRY_DELAY_S = 5.0
SECOND_RETRY_DELAY_S = 20.0
RETRY_DELAYS_S = (FIRST_RETRY_DELAY_S, SECOND_RETRY_DELAY_S)
MAX_MASKED_STDERR_CHARS = 2000
_TOKEN_RUN_RE = re.compile(r"[A-Za-z0-9_-]{20,}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_ABS_PATH_RE = re.compile(r"(?<![\w.])/[^\s'\"\)\]\}]*")
_REDACTED = "[redacted]"


def mask_stderr(raw: bytes, private_terms: Sequence[str] = ()) -> str:
    """Mask child stderr so the ledger can keep it.

    Decodes with replacement, removes control characters, replaces each
    private term case-insensitively, the home directory and any absolute
    path whole up to the next whitespace or closing quote or bracket,
    whatever character comes before it, email-shaped text and any long
    token-shaped run, then cuts to 2000 characters. A slash following a
    word character or a dot is not a path start, so `a/b` and `./c`
    survive. A plain error sentence survives.
    """
    text = raw.decode("utf-8", errors="replace")
    text = "".join(char for char in text if unicodedata.category(char) != "Cc")
    for term in private_terms:
        if term:
            text = re.sub(re.escape(term), _REDACTED, text, flags=re.IGNORECASE)
    home = os.path.expanduser("~")
    if home and home != "~":
        text = text.replace(home, _REDACTED)
    text = _ABS_PATH_RE.sub(_REDACTED, text)
    text = _EMAIL_RE.sub(_REDACTED, text)
    text = _TOKEN_RUN_RE.sub(_REDACTED, text)
    return text[:MAX_MASKED_STDERR_CHARS]


@dataclass(frozen=True)
class LocalStartRecord:
    """One retried local start failure, in try order."""

    attempt: int
    reason: str
    latency_ms: int
    exit_code: int | None
    stderr_masked: str


class LocalRetryClient:
    """A ``WonderClient`` that retries local start failures with fixed delays.

    Wraps any other ``WonderClient``; only ``LocalStartFailure`` is ever
    retried, and every one is recorded masked in ``failures``. The retry
    stops and re-raises the same failure when no delay remains or the
    next delay does not fit in the seconds left.
    """

    def __init__(
        self,
        inner: WonderClient,
        *,
        sleep: Callable[[float], None] = time.sleep,
        seconds_left: Callable[[], float] | None = None,
    ) -> None:
        self._inner = inner
        self._sleep = sleep
        self._seconds_left = seconds_left
        self._failures: list[LocalStartRecord] = []

    @property
    def failures(self) -> tuple[LocalStartRecord, ...]:
        """The retried failures so far, in try order."""
        return tuple(self._failures)

    @property
    def transport(self) -> str:
        return self._inner.transport

    @property
    def transport_version(self) -> str | None:
        return self._inner.transport_version

    @property
    def harness_rules_file(self) -> bool | None:
        return self._inner.harness_rules_file

    def complete(self, request: WonderRequest) -> WonderResponse:
        attempt = 0
        while True:
            try:
                return self._inner.complete(request)
            except LocalStartFailure as exc:
                attempt += 1
                self._failures.append(
                    LocalStartRecord(
                        attempt=attempt,
                        reason=str(exc),
                        latency_ms=exc.latency_ms,
                        exit_code=exc.exit_code,
                        stderr_masked=exc.stderr_masked,
                    )
                )
                if attempt > len(RETRY_DELAYS_S):
                    raise
                delay = RETRY_DELAYS_S[attempt - 1]
                if self._seconds_left is not None and delay > self._seconds_left():
                    raise
                self._sleep(delay)
