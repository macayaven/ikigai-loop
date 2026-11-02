"""Telegram Bot API client: one token-reading function, pinned failures."""

import http.client
import json
import logging
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from framework.collectors.common import as_dict
from framework.telegram.models import utf16_len

API_BASE = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^[0-9]+:[A-Za-z0-9_-]+$")
REDACTED = "[redacted]"

NETWORK_BACKOFF = (1.0, 2.0, 4.0)
LOOP_BACKOFF_CAP = 60.0
RATE_LIMIT_CAP = 300

logger = logging.getLogger(__name__)


class TelegramError(Exception):
    """Base for every Telegram failure; never carries the value or URL."""


class TelegramConfigError(TelegramError):
    """Process context value missing or malformed; names the variable."""


class TelegramTransportError(TelegramError):
    """No status, or a body that is not usable JSON on a 2xx."""


class TelegramDeliveryUnknown(TelegramTransportError):
    """The request may have reached Telegram: never retry it blindly."""


class TelegramApiError(TelegramError):
    """A classified API failure; description is scrubbed and cut."""

    def __init__(self, message: str, description: str | None = None) -> None:
        super().__init__(message)
        self.description = description


class TelegramAuthError(TelegramApiError):
    """401 and 404: stop the loop."""


class TelegramConflict(TelegramApiError):
    """409 on getUpdates: a webhook or a second poller."""


class TelegramRateLimited(TelegramApiError):
    """429; carries the wait when Telegram named one."""

    def __init__(
        self,
        message: str,
        retry_after: int | None = None,
        description: str | None = None,
    ) -> None:
        super().__init__(message, description)
        self.retry_after = retry_after


@dataclass(frozen=True)
class _PendingRequest:
    api_base: str
    body: bytes
    content_type: str


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """HTTPS over IPv4 only; the TLS server name stays the real host."""

    def connect(self) -> None:
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        timeout = self.timeout if isinstance(self.timeout, (float, int)) else None
        source_address: tuple[str, int] | None = getattr(self, "source_address", None)
        last: OSError | None = None
        sock: socket.socket | None = None
        for family, socktype, proto, _canon, sockaddr in infos:
            try:
                sock = socket.socket(family, socktype, proto)
                if timeout is not None:
                    sock.settimeout(timeout)
                if source_address is not None:
                    sock.bind(source_address)
                sock.connect(sockaddr)
            except OSError as exc:
                last = exc
                if sock is not None:
                    sock.close()
                    sock = None
                continue
            break
        if sock is None:
            raise last if last is not None else OSError("ipv4 connect failed")
        self.sock = sock
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        tunnel_host: str | None = getattr(self, "_tunnel_host", None)
        if tunnel_host is not None:
            getattr(self, "_tunnel")()  # noqa: B009 - stubs hide this stdlib private
            server_hostname = tunnel_host
        else:
            server_hostname = self.host
        context = getattr(self, "_context")  # noqa: B009 - stubs hide this stdlib private
        self.sock = context.wrap_socket(self.sock, server_hostname=server_hostname)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPS handler that connects over IPv4 only, for the Bot API host."""

    def https_open(  # type: ignore[override]
        self, req: urllib.request.Request
    ) -> urllib.response.addinfourl:
        result = self.do_open(
            _IPv4HTTPSConnection,
            req,
            context=getattr(self, "_context"),  # noqa: B009 - stubs hide this stdlib private
        )
        return cast("urllib.response.addinfourl", result)


_API_HOST = urllib.parse.urlsplit(API_BASE).hostname or ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: a 3xx comes back as a plain status.

    A 3xx on a POST would otherwise become a GET to wherever the server
    says, and a failed GET would read as ``not_sent`` even though the POST
    already reached the server. The Bot API has no reason to redirect, so
    no method follows one, on either path below.
    """

    def redirect_request(  # type: ignore[override]
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


def _open_url(
    request: urllib.request.Request, timeout: float | None = None
) -> urllib.response.addinfourl:
    """One seam for every Bot API read; IPv4 only for the Bot API host.

    Neither path follows a redirect, still with no ``install_opener``.
    """
    host = (urllib.parse.urlsplit(request.full_url).hostname or "").lower()
    if request.type == "https" and host == _API_HOST:
        opener = urllib.request.build_opener(_IPv4HTTPSHandler, _NoRedirect)
        return opener.open(request, timeout=timeout)  # type: ignore[no-any-return]
    opener = urllib.request.build_opener(_NoRedirect)
    return opener.open(request, timeout=timeout)  # type: ignore[no-any-return]


def _request_once(
    method: str, request: _PendingRequest, timeout_s: float
) -> tuple[int | None, dict[str, str], bytes, str | None]:
    """Read the value, build the URL, run one POST; never raises.

    Returns ``(status, headers, scrubbed body, failure_kind)`` where the kind
    is None, "config", "not_sent" or "unknown". "not_sent" means the request
    never reached Telegram in full: stdlib ``do_open`` wraps only ``OSError``
    from ``h.request`` into ``URLError`` and lets ``getresponse`` and read
    failures through raw. Any other exception means delivery is unknown.
    """
    raw_value = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    value = raw_value.strip()
    if not TOKEN_RE.fullmatch(value):
        return (None, {}, b"", "config")
    url = f"{request.api_base}/bot{value}/{method}"
    try:
        http_request = urllib.request.Request(
            url,
            data=request.body,
            headers={"Content-Type": request.content_type},
            method="POST",
        )
        with _open_url(http_request, timeout_s) as response:
            if response.status is None:
                return (None, {}, b"", "unknown")
            status: int | None = int(response.status)
            headers = {k.lower(): v for k, v in response.headers.items()}
            raw_body = response.read()
    except urllib.error.HTTPError as exc:
        try:
            status = int(exc.code)
            headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
            raw_body = exc.read()
        except Exception:  # noqa: BLE001 - D17 pins the broad catch
            return (None, {}, b"", "unknown")
    except urllib.error.URLError:
        return (None, {}, b"", "not_sent")
    except Exception:  # noqa: BLE001 - D17 pins the broad catch
        return (None, {}, b"", "unknown")
    encoded = value.encode()
    quoted = urllib.parse.quote(value, safe="").encode()
    body = raw_body.replace(encoded, REDACTED.encode()).replace(
        quoted, REDACTED.encode()
    )
    return (status, headers, body, None)


CHAT_RE = re.compile(r"-?[0-9]+")


def _allowed_chat_id() -> int | None:  # pyright: ignore[reportUnusedFunction] - used cross-module
    """Parse TELEGRAM_CHAT_ID at call time; None when unusable."""
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not CHAT_RE.fullmatch(raw):
        return None
    return int(raw)


def _parse_json(body: bytes) -> dict[str, Any] | None:
    try:
        payload: Any = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return as_dict(payload)


def _describe(payload: dict[str, Any]) -> str | None:
    description = payload.get("description")
    if not isinstance(description, str) or not description:
        return None
    return description[:120]


def _retry_after(payload: dict[str, Any], headers: dict[str, str]) -> int | None:
    parameters = as_dict(payload.get("parameters"))
    if parameters is not None:
        wait: Any = parameters.get("retry_after")
        if isinstance(wait, int) and not isinstance(wait, bool) and wait > 0:
            return wait
    header: Any = headers.get("retry-after")
    if header is not None:
        try:
            parsed = int(header.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _failure_message(method: str, status: int, description: str | None) -> str:
    if description:
        return f"{method} failed (status {status}): {description}"
    return f"{method} failed (status {status})"


class TelegramClient:
    """HTTPS client; holds no value, reads it per call."""

    def __init__(
        self,
        api_base: str = API_BASE,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.sleep_fn = sleep_fn

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout_s: float = 30.0,
        attempts: int = 4,
    ) -> Any:
        """POST one JSON body; return the decoded result value."""
        body = json.dumps(payload if payload is not None else {}).encode()
        request = _PendingRequest(self.api_base, body, "application/json")
        return self._request_with_retry(method, request, timeout_s, attempts)

    def _request_with_retry(
        self,
        method: str,
        request: _PendingRequest,
        timeout_s: float,
        attempts: int,
        *,
        no_blind_retry: bool = False,
    ) -> Any:
        """Run one retry loop; return the decoded result value.

        With ``no_blind_retry`` (photo sends), an unknown delivery, a 5xx
        or an unusable 2xx body raises ``TelegramDeliveryUnknown`` at once;
        only a refused request (429) or one that never connected retries.
        """
        for attempt in range(max(attempts, 1)):
            last = attempt == max(attempts, 1) - 1
            backoff = NETWORK_BACKOFF[min(attempt, len(NETWORK_BACKOFF) - 1)]
            status, headers, raw, failure = _request_once(method, request, timeout_s)
            if failure == "config":
                logger.debug("telegram %s config error", method)
                raise TelegramConfigError(
                    "TELEGRAM_BOT_TOKEN is not set or is malformed"
                )
            if failure == "unknown" and no_blind_retry:
                logger.debug("telegram %s delivery unknown", method)
                raise TelegramDeliveryUnknown(f"{method} delivery unknown")
            if failure in ("not_sent", "unknown") or status is None:
                logger.debug("telegram %s network failure", method)
                if last:
                    raise TelegramTransportError(f"{method} network error")
                self.sleep_fn(backoff)
                continue
            payload_body = _parse_json(raw)
            if payload_body is None:
                if 200 <= status <= 299:
                    logger.debug("telegram %s invalid response", method)
                    if no_blind_retry:
                        raise TelegramDeliveryUnknown(f"{method} invalid response")
                    if last:
                        raise TelegramTransportError(f"{method} invalid response")
                    self.sleep_fn(backoff)
                    continue
                error = self._classified(
                    method, status, {}, headers, last, backoff, no_blind_retry
                )
            elif payload_body.get("ok") is True:
                logger.debug("telegram %s ok", method)
                decoded: Any = payload_body.get("result")
                return decoded
            else:
                error = self._classified(
                    method, status, payload_body, headers, last, backoff, no_blind_retry
                )
            if error is None:
                continue
            logger.debug("telegram %s failed with status %s", method, status)
            raise error
        raise TelegramTransportError(f"{method} network error")

    def _classified(
        self,
        method: str,
        status: int,
        payload_body: dict[str, Any],
        headers: dict[str, str],
        last: bool,
        backoff: float,
        no_blind_retry: bool = False,
    ) -> TelegramError | None:
        raw_code = payload_body.get("error_code")
        if isinstance(raw_code, int) and not isinstance(raw_code, bool):
            code = raw_code
        else:
            code = status
        description = _describe(payload_body)
        if 300 <= code <= 399:
            if no_blind_retry:
                return TelegramDeliveryUnknown(
                    _failure_message(method, code, description)
                )
            return TelegramApiError(
                _failure_message(method, code, description), description
            )
        if code == 429:
            wait = _retry_after(payload_body, headers)
            if wait is not None and wait <= RATE_LIMIT_CAP and not last:
                self.sleep_fn(float(wait))
                return None
            if wait is None and not last:
                self.sleep_fn(backoff)
                return None
            return TelegramRateLimited(
                f"{method} rate limited (retry_after={wait})",
                retry_after=wait,
                description=description,
            )
        if code in (401, 404):
            return TelegramAuthError(
                _failure_message(method, code, description), description
            )
        if code == 409 and method == "getUpdates":
            return TelegramConflict(
                _failure_message(method, code, description), description
            )
        if 500 <= code <= 599:
            if no_blind_retry:
                return TelegramDeliveryUnknown(
                    _failure_message(method, code, description)
                )
            if last:
                return TelegramApiError(
                    _failure_message(method, code, description), description
                )
            self.sleep_fn(backoff)
            return None
        return TelegramApiError(
            _failure_message(method, code, description), description
        )

    def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        caption: str,
        reply_markup: dict[str, Any],
        *,
        timeout_s: float = 30.0,
    ) -> dict[str, Any]:
        """Send one photo message; return the decoded message dict."""
        if utf16_len(caption) > 1024:
            raise ValueError("caption exceeds 1024 UTF-16 code units")
        body, content_type = _encode_multipart(
            [
                ("chat_id", str(chat_id)),
                ("caption", caption),
                ("reply_markup", json.dumps(reply_markup, ensure_ascii=False)),
            ],
            "photo",
            "card.png",
            "image/png",
            photo,
        )
        request = _PendingRequest(self.api_base, body, content_type)
        photo_result: Any = self._request_with_retry(
            "sendPhoto", request, timeout_s, 4, no_blind_retry=True
        )
        if isinstance(photo_result, dict):
            return cast("dict[str, Any]", photo_result)
        raise TelegramDeliveryUnknown("sendPhoto invalid response")

    def get_updates(
        self,
        offset: int | None,
        long_poll_s: int,
        *,
        timeout_s: float | None = None,
    ) -> list[Any]:
        """Fetch raw updates; the socket timeout always exceeds the poll."""
        socket_timeout = long_poll_s + 15 if timeout_s is None else timeout_s
        payload: dict[str, Any] = {
            "timeout": long_poll_s,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        updates: Any = self.call(
            "getUpdates", payload, timeout_s=socket_timeout, attempts=1
        )
        if not isinstance(updates, list):
            raise TelegramTransportError("getUpdates invalid response")
        return cast("list[Any]", updates)


def _encode_multipart(
    fields: list[tuple[str, str]],
    file_field: str,
    filename: str,
    file_content_type: str,
    file_bytes: bytes,
) -> tuple[bytes, str]:
    """Hand-built multipart/form-data with a payload-checked boundary."""
    encoded_fields = [(name, value.encode("utf-8")) for name, value in fields]
    for _ in range(100):
        boundary = "----" + secrets.token_hex(16)
        marker = boundary.encode()
        if any(marker in value for _, value in encoded_fields):
            continue
        if marker in file_bytes:
            continue
        chunks: list[bytes] = []
        for name, value in encoded_fields:
            chunks.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                f"\r\n\r\n".encode()
                + value
                + b"\r\n"
            )
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}";'
            f' filename="{filename}"\r\nContent-Type: {file_content_type}\r\n\r\n'.encode()
            + file_bytes
            + b"\r\n"
        )
        chunks.append(f"--{boundary}--\r\n".encode())
        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
    raise TelegramError("sendPhoto failed")
