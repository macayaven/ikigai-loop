"""Retry one timed-out Wonder call inside the propose deadline.

A stall on the service side shows as one open call that never returns
while a second identical request goes through. Only a call that ends in
the closed reason ``timeout`` gets one more attempt, and only when a
full call's time still remains before the propose deadline. Every other
closed reason, a local start failure and any other exception go up
unchanged on the first try, and the time is never read for those.
"""

from __future__ import annotations

from collections.abc import Callable

from framework.proposal.core import (
    MetaUnavailableError,
    WonderClient,
    WonderRequest,
    WonderResponse,
)


class TimeoutRetryClient:
    """A ``WonderClient`` that retries one timeout with the same request.

    Wraps another ``WonderClient``; when ``complete`` raises exactly
    ``MetaUnavailableError`` with the message ``timeout`` and the
    seconds left are at or above ``min_seconds_left``, it counts one
    retry and calls the inner client once more with the same request.
    Whatever the second call returns or raises is the result. A
    ``None`` seconds left, for the kill file, never retries.
    """

    def __init__(
        self,
        inner: WonderClient,
        seconds_left: Callable[[], float | None],
        min_seconds_left: float,
    ) -> None:
        self._inner = inner
        self._seconds_left = seconds_left
        self._min_seconds_left = min_seconds_left
        self._retries = 0

    @property
    def retries(self) -> int:
        """The timeouts retried so far, across calls."""
        return self._retries

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
        try:
            return self._inner.complete(request)
        except MetaUnavailableError as exc:
            if type(exc) is not MetaUnavailableError or str(exc) != "timeout":
                raise
            left = self._seconds_left()
            if left is None or left < self._min_seconds_left:
                raise
            self._retries += 1
        return self._inner.complete(request)
