"""Ticket 11: Meta edge client (CLI edge only).

Reads config at call time, scans every outbound request before sending,
and posts one chat completion. The API key appears only in the
``Authorization`` header: never logged, never in an exception, never in a
result.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Self, cast

from framework.briefing.gate import scan_outbound_text
from framework.glimmer.llm import sanitise_model_id
from framework.proposal.core import (
    ContributorModelRefused,
    MetaUnavailableError,
    OutboundBlocked,
    WonderRequest,
    WonderResponse,
)

BASE_URL = "https://api.meta.ai/v1"
MAX_TOKENS = 32768
TIMEOUT_S = 300
EFFORTS = frozenset({"minimal", "low", "medium", "high"})

# One cap for both Wonder transports: well above the largest real stream
# measured and below the garbage reply the review used.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


def is_contributor_model(value: Any) -> bool:
    """True when a reported model name carries the contributor marker."""
    return isinstance(value, str) and "contributor" in value.casefold()


def token_count(value: Any) -> int | None:
    """A usable token count, or None; booleans and negatives never count."""
    if isinstance(value, bool):
        return None
    if not isinstance(value, int) or value < 0:
        return None
    return value


Transport = Callable[[urllib.request.Request, float], Any]


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: following one would forward Authorization."""

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_OPENER = urllib.request.build_opener(NoRedirectHandler)


def _open_no_redirect(
    request: urllib.request.Request, timeout: float | None = None
) -> Any:
    """Open without following redirects, so a 30x surfaces as an error."""
    return _OPENER.open(request, timeout=timeout)


class _CappedResponse:
    """One response body, read at most one byte past the cap into memory."""

    def __init__(self, response: Any) -> None:
        self._response = response

    def __enter__(self) -> Self:
        self._response.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self._response.__exit__(*args)

    def read(self) -> bytes:
        chunks: list[bytes] = []
        remaining = MAX_RESPONSE_BYTES + 1
        while remaining > 0:
            chunk = self._response.read(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _default_transport(request: urllib.request.Request, timeout: float) -> Any:
    return _CappedResponse(_open_no_redirect(request, timeout=timeout))


@dataclass(frozen=True)
class MetaConfig:
    api_key: str


class MetaConfigError(Exception):
    """Missing config; the message names the variable only."""


def load_meta_config(environ: Mapping[str, str] | None = None) -> MetaConfig:
    """Read ``META_API_KEY`` at call time; a missing value names the variable."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    api_key = env.get("META_API_KEY", "")
    if not api_key:
        raise MetaConfigError("META_API_KEY")
    return MetaConfig(api_key=api_key)


def refuse_contributor_model(model: str) -> None:
    """Refuse any model id carrying the contributor marker."""
    if is_contributor_model(model):
        raise ContributorModelRefused("contributor models are refused")


_RETRYABLE_DROPS = (
    http.client.RemoteDisconnected,
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
)


class MetaClient:
    """POST ``{base_url}/chat/completions``; each request names its model."""

    transport = "api"
    transport_version: str | None = None
    harness_rules_file: bool | None = None

    def __init__(
        self,
        *,
        api_key: str,
        private_terms: tuple[str, ...] = (),
        private_terms_available: bool = False,
        base_url: str = BASE_URL,
        timeout_s: float = TIMEOUT_S,
        transport: Transport | None = None,
        resend_pause_s: float = 2.0,
    ) -> None:
        self._api_key = api_key
        self._private_terms = private_terms
        self._private_terms_available = private_terms_available
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._transport = transport
        self._resend_pause_s = resend_pause_s

    def complete(self, request: WonderRequest) -> WonderResponse:
        codes = scan_outbound_text(
            request.prompt,
            private_terms=self._private_terms,
            private_terms_available=self._private_terms_available,
            forbidden_raw_literals=request.forbidden_raw_literals,
        )
        if codes:
            raise OutboundBlocked(codes)
        refuse_contributor_model(request.model)
        if request.effort not in EFFORTS:
            raise ValueError("unknown effort")
        start = time.monotonic()
        failure: str | None = None
        raw = b""
        body = json.dumps(
            {
                "model": request.model,
                "reasoning_effort": request.effort,
                "max_tokens": MAX_TOKENS,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.schema_name,
                        "schema": request.response_schema,
                    },
                },
                "messages": [{"role": "user", "content": request.prompt}],
            }
        ).encode()
        http_request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        opener = self._transport or _default_transport

        def _send() -> bytes:
            with opener(http_request, self._timeout_s) as response:
                return response.read()

        def _failure() -> tuple[str | None, bytes]:
            try:
                return None, _send()
            except TimeoutError:
                return "timeout", b""
            except urllib.error.HTTPError as exc:
                return f"status {exc.code}", b""
            except urllib.error.URLError as exc:
                reason = exc.reason
                if isinstance(reason, _RETRYABLE_DROPS):
                    raise reason from None
                if isinstance(reason, TimeoutError):
                    return "timeout", b""
                return "transport error", b""
            except _RETRYABLE_DROPS:
                raise
            except (OSError, http.client.HTTPException, ValueError):
                return "transport error", b""

        try:
            failure, raw = _failure()
        except _RETRYABLE_DROPS:
            time.sleep(self._resend_pause_s)
            try:
                failure, raw = _failure()
            except _RETRYABLE_DROPS:
                failure, raw = "transport error", b""
        if failure is not None:
            # Raised outside the handler so the transport detail behind
            # ``failure`` stays out of ``__context__`` and ``__cause__``.
            raise MetaUnavailableError(
                failure, latency_ms=int((time.monotonic() - start) * 1000)
            )
        latency_ms = int((time.monotonic() - start) * 1000)
        if len(raw) > MAX_RESPONSE_BYTES:
            # Raised outside the handler so an injected transport that hands
            # back a whole body gets the same result as the capped default.
            raise MetaUnavailableError("output too large", latency_ms=latency_ms)
        try:
            parsed: Any = json.loads(raw)
            choice: Any = parsed["choices"][0]
            message: Any = choice["message"]
            content: Any = message.get("content")
            if content is None:
                text = ""
            elif isinstance(content, str):
                text = content
            else:
                raise TypeError("non-string content")
        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            RecursionError,
        ):
            raise MetaUnavailableError(
                "invalid response", latency_ms=latency_ms
            ) from None
        reported: Any = parsed.get("model")
        if is_contributor_model(reported):
            # The raw value is checked before sanitising, so a contributor
            # name arriving as a path cannot launder itself.
            raise MetaUnavailableError("contributor model", latency_ms=latency_ms)
        model_reported = sanitise_model_id(reported)
        if (
            not isinstance(reported, str)
            or not reported
            or model_reported == "unreported"
        ):
            raise MetaUnavailableError("no model evidence", latency_ms=latency_ms)
        finish: Any = choice.get("finish_reason")
        usage_raw: Any = parsed.get("usage")
        usage_map = (
            cast("dict[str, Any]", usage_raw) if isinstance(usage_raw, dict) else {}
        )
        details_raw: Any = usage_map.get("completion_tokens_details")
        details_map = (
            cast("dict[str, Any]", details_raw) if isinstance(details_raw, dict) else {}
        )
        prompt_details_raw: Any = usage_map.get("prompt_tokens_details")
        prompt_details_map = (
            cast("dict[str, Any]", prompt_details_raw)
            if isinstance(prompt_details_raw, dict)
            else {}
        )
        return WonderResponse(
            text=text,
            model_reported=model_reported,
            latency_ms=latency_ms,
            finish_reason=finish if isinstance(finish, str) else None,
            prompt_tokens=token_count(usage_map.get("prompt_tokens")),
            completion_tokens=token_count(usage_map.get("completion_tokens")),
            reasoning_tokens=token_count(details_map.get("reasoning_tokens")),
            cached_tokens=token_count(prompt_details_map.get("cached_tokens")),
        )
