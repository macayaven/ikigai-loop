"""Local-model edge client (Ticket 9). CLI edge only.

Reads config at call time, posts one OpenAI-compatible chat completion,
and returns only ``message.content`` plus completion metadata. The API
key appears only in the ``Authorization`` header: never logged, never in
an exception, never in a result. ``reasoning_content`` is never parsed,
logged, or stored.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlsplit

from framework.glimmer.facts import LLMResponse, LLMUnavailableError

MODEL_MAX_TOKENS = 32768
MODEL_TIMEOUT_S = 1800


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


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}), NoRedirectHandler
)


def urlopen(request: urllib.request.Request, timeout: float | None = None) -> Any:
    """Open without following redirects, so a 30x surfaces as an error."""
    return _OPENER.open(request, timeout=timeout)


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str


def _require(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "")
    if not value:
        raise SystemExit(f"missing required environment variable: {name}")
    return value


def _check_key(value: str) -> bool:
    """ASCII, printable, and free of whitespace throughout."""
    return (
        value.isascii()
        and value.isprintable()
        and not any(ch.isspace() for ch in value)
    )


def _check_base_url(value: str) -> bool:
    """Scheme http/https with a host, and no whitespace or control character."""
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def load_llm_config(environ: Mapping[str, str] | None = None) -> LLMConfig:
    """Read ``LOCAL_LLM_*`` at call time; a bad value names the variable."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    base_url = _require(env, "LOCAL_LLM_BASE_URL")
    model = _require(env, "LOCAL_LLM_MODEL")
    api_key = _require(env, "LOCAL_LLM_API_KEY")
    if not _check_base_url(base_url):
        raise SystemExit("invalid environment variable: LOCAL_LLM_BASE_URL")
    if not _check_key(api_key):
        raise SystemExit("invalid environment variable: LOCAL_LLM_API_KEY")
    return LLMConfig(base_url=base_url, model=model, api_key=api_key)


def sanitise_model_id(raw: object) -> str:
    """Keep only the last path component; ``"unreported"`` when absent."""
    if not isinstance(raw, str) or not raw:
        return "unreported"
    return re.split(r"[/\\]", raw)[-1] or "unreported"


class OpenAICompatibleClient:
    """POST ``{base_url}/chat/completions`` with temperature 0."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_s: int = MODEL_TIMEOUT_S,
        response_format: Mapping[str, Any] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout_s = timeout_s
        self.response_format = response_format

    def complete(self, prompt: str) -> LLMResponse:
        start = time.monotonic()
        failure: str | None = None
        raw = b""
        try:
            payload: dict[str, Any] = {
                "model": self._model,
                "temperature": 0,
                "max_tokens": MODEL_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
            if self.response_format is not None:
                payload["response_format"] = self.response_format
            body = json.dumps(payload).encode()
            request = urllib.request.Request(
                f"{self._base_url}/chat/completions",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            with urlopen(request, timeout=self._timeout_s) as response:
                raw = response.read()
        except TimeoutError:
            failure = "timeout"
        except urllib.error.HTTPError as exc:
            failure = f"status {exc.code}"
        except (OSError, http.client.HTTPException, ValueError):
            failure = "transport error"
        if failure is not None:
            # Raised outside the handler so the transport detail behind
            # ``failure`` stays out of ``__context__`` and ``__cause__``.
            raise LLMUnavailableError(
                failure, latency_ms=int((time.monotonic() - start) * 1000)
            )
        latency_ms = int((time.monotonic() - start) * 1000)
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
            raise LLMUnavailableError(
                "invalid response", latency_ms=latency_ms
            ) from None
        finish: Any = choice.get("finish_reason")
        usage: Any = parsed.get("usage")
        tokens: Any = (
            cast(dict[str, Any], usage).get("completion_tokens")
            if isinstance(usage, dict)
            else None
        )
        return LLMResponse(
            text=text,
            model_id=sanitise_model_id(parsed.get("model")),
            latency_ms=latency_ms,
            finish_reason=finish if isinstance(finish, str) else None,
            completion_tokens=tokens if isinstance(tokens, int) else None,
        )
