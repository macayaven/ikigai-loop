"""Faithful offline fake of the Telegram Bot API over the urlopen seam.

Synthetic values only. Never binds or connects a socket: tests patch
``urllib.request.urlopen`` with ``FakeTelegram`` and drive everything locally.
"""

import io
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from email.message import Message
from email.parser import BytesParser
from typing import Self

import pytest

FAKE_BOT_VALUE = "1:synthetic-token-marker"
FAKE_CHAT_ID = 424242
FAKE_USER_ID = 424242
FAKE_API_BASE = "https://api.telegram.org"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

NOT_MODIFIED_DESCRIPTION = (
    "Bad Request: message is not modified: specified new message content and "
    "reply markup are exactly the same as a current content and reply markup "
    "of the message"
)
QUERY_TOO_OLD_DESCRIPTION = (
    "Bad Request: query is too old and response timeout expired or query ID is invalid"
)
CONFLICT_DESCRIPTION = (
    "Conflict: terminated by other getUpdates request; make sure that only "
    "one bot instance is running"
)


def utf16_units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _checked_id(value: int, label: str) -> int:
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an int, got {value!r}"
    )
    return value


class _Response:
    def __init__(
        self, status: int, headers: dict[str, str] | None, body: bytes
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class _BoomReader(_Response):
    def read(self) -> bytes:
        raise TimeoutError("timed out during read")


def _http_error(
    url: str,
    code: int,
    description: str,
    parameters: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> urllib.error.HTTPError:
    payload: dict[str, object] = {
        "ok": False,
        "error_code": code,
        "description": description,
    }
    if parameters is not None:
        payload["parameters"] = parameters
    hdrs = Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    return urllib.error.HTTPError(
        url, code, "Error", hdrs, io.BytesIO(json.dumps(payload).encode())
    )


def _parse_multipart(
    content_type: str, body: bytes
) -> dict[str, tuple[str | None, bytes]]:
    head = b"Content-Type: " + content_type.encode() + b"\r\n\r\n"
    message = BytesParser().parsebytes(head + body)
    fields: dict[str, tuple[str | None, bytes]] = {}
    assert message.is_multipart()
    for part in message.get_payload():
        assert isinstance(part, Message)
        name = part.get_param("name", header="content-disposition")
        assert isinstance(name, str)
        filename = part.get_param("filename", header="content-disposition")
        payload = part.get_payload(decode=True)
        assert isinstance(payload, bytes)
        fields[name] = (
            filename if isinstance(filename, str) else None,
            payload,
        )
    return fields


class FakeTelegram:
    """Callable ``urlopen`` replacement enforcing what the real API enforces."""

    def __init__(
        self,
        bot_value: str = FAKE_BOT_VALUE,
        chat_id: int = FAKE_CHAT_ID,
        user_id: int = FAKE_USER_ID,
        api_base: str = FAKE_API_BASE,
    ) -> None:
        self.bot_value = bot_value
        self.chat_id = chat_id
        self.user_id = user_id
        self.api_base = api_base.rstrip("/")
        self.requests: list[tuple[str, str, dict[str, str], bytes, float | None]] = []
        self.parse_mode_requests: list[str] = []
        self.updates: list[dict[str, object]] = []
        self.scripts: dict[str, list[object]] = {}
        self.markups: dict[tuple[int, int], object] = {}
        self.message_seq = 1000
        self.expired_queries: set[str] = set()

    # -- update builders (refuse string ids so tests cannot pass on strings) --

    def callback_update(
        self,
        update_id: int,
        query_id: str,
        data: object,
        *,
        message_id: int = 55,
        chat_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, object]:
        chat = chat_id if chat_id is not None else self.chat_id
        user = user_id if user_id is not None else self.user_id
        _checked_id(update_id, "update_id")
        _checked_id(message_id, "message_id")
        _checked_id(chat, "chat_id")
        _checked_id(user, "user_id")
        query: dict[str, object] = {
            "id": query_id,
            "from": {"id": user, "is_bot": False},
            "message": {
                "message_id": message_id,
                "chat": {"id": chat, "type": "private"},
                "date": 1790985600,
                "text": "card",
            },
            "chat_instance": "synthetic-instance",
        }
        if data is not _SENTINEL and data is not MISSING:
            query["data"] = data
        return {"update_id": update_id, "callback_query": query}

    def text_update(
        self,
        update_id: int,
        text: str,
        *,
        message_id: int = 56,
        chat_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, object]:
        chat = chat_id if chat_id is not None else self.chat_id
        user = user_id if user_id is not None else self.user_id
        _checked_id(update_id, "update_id")
        _checked_id(message_id, "message_id")
        _checked_id(chat, "chat_id")
        _checked_id(user, "user_id")
        return {
            "update_id": update_id,
            "message": {
                "message_id": message_id,
                "from": {"id": user, "is_bot": False},
                "chat": {"id": chat, "type": "private"},
                "date": 1790985600,
                "text": text,
            },
        }

    def voice_update(
        self,
        update_id: int,
        *,
        message_id: int = 57,
        chat_id: int | None = None,
        user_id: int | None = None,
        file_id: object = "synthetic-file-id",
        file_unique_id: object = "synthetic-unique-id",
        duration: object = 12,
        mime_type: object = "audio/ogg",
        file_size: object = 4100,
        reply_to: int | None = None,
    ) -> dict[str, object]:
        chat = chat_id if chat_id is not None else self.chat_id
        user = user_id if user_id is not None else self.user_id
        _checked_id(update_id, "update_id")
        _checked_id(message_id, "message_id")
        _checked_id(chat, "chat_id")
        _checked_id(user, "user_id")
        voice: dict[str, object] = {
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "duration": duration,
        }
        if mime_type is not None:
            voice["mime_type"] = mime_type
        if file_size is not None:
            voice["file_size"] = file_size
        message: dict[str, object] = {
            "message_id": message_id,
            "from": {"id": user, "is_bot": False},
            "chat": {"id": chat, "type": "private"},
            "date": 1790985600,
            "voice": voice,
        }
        if reply_to is not None:
            message["reply_to_message"] = {"message_id": reply_to}
        return {"update_id": update_id, "message": message}

    def queue(self, update: dict[str, object]) -> None:
        self.updates.append(update)

    def queue_script(self, method: str, *outcomes: object) -> None:
        self.scripts.setdefault(method, []).extend(outcomes)

    # -- the urlopen seam --

    def __call__(
        self, request: urllib.request.Request, timeout: float | None = None
    ) -> _Response:
        url = request.full_url
        raw_data = request.data
        assert raw_data is None or isinstance(raw_data, bytes)
        body = raw_data if raw_data is not None else b""
        headers = {key.lower(): value for key, value in request.header_items()}
        prefix = f"{self.api_base}/bot"
        assert url.startswith(prefix), f"unexpected url {url!r}"
        token_seg, _, method = url[len(prefix) :].partition("/")
        self.requests.append((method, method, headers, body, timeout))
        if b"parse_mode" in body:
            self.parse_mode_requests.append(method)
        if token_seg != self.bot_value:
            raise _http_error(url, 401, "Unauthorized")
        if method not in (
            "getUpdates",
            "sendPhoto",
            "sendMessage",
            "editMessageReplyMarkup",
            "answerCallbackQuery",
        ):
            raise _http_error(url, 404, "Not Found")
        pending = self.scripts.get(method, [])
        if pending:
            return self._scripted(url, method, dict(headers), body, pending.pop(0))
        return self._route(url, method, dict(headers), body)

    def _scripted(
        self,
        url: str,
        method: str,
        headers: dict[str, str],
        body: bytes,
        outcome: object,
    ) -> _Response:
        if outcome == "timeout-urlopen":
            raise TimeoutError("timed out at urlopen")
        if outcome == "timeout-read":
            return _BoomReader(200, {}, b"")
        if outcome == "malformed":
            return _Response(200, {}, b"<html>not json</html>")
        if outcome == "echo-url":
            assert self.bot_value in url, "echo case requires the value in the URL"
            return _Response(200, {}, b"oops " + url.encode() + b" not json")
        if outcome == "error-with-url":
            raise OSError(f"connection failed for {url}")
        if outcome == "echo-json":
            payload = {
                "ok": False,
                "error_code": 500,
                "description": f"oops {url} {urllib.parse.quote(url, safe='')}",
            }
            hdrs = Message()
            raise urllib.error.HTTPError(
                url, 500, "Error", hdrs, io.BytesIO(json.dumps(payload).encode())
            )
        if outcome == "html-502":
            # Real urllib raises HTTPError on a 5xx; go through that path.
            hdrs = Message()
            hdrs["Content-Type"] = "text/html"
            raise urllib.error.HTTPError(
                url,
                502,
                "Bad Gateway",
                hdrs,
                io.BytesIO(b"<html><body>Bad Gateway</body></html>"),
            )
        assert isinstance(outcome, tuple)
        kind = outcome[0]
        if kind == "429":
            retry_after = int(outcome[1])
            raise _http_error(
                url,
                429,
                f"Too Many Requests: retry after {retry_after}",
                {"retry_after": retry_after},
            )
        if kind == "429-header":
            raise _http_error(
                url,
                429,
                "Too Many Requests: retry after 3",
                None,
                {"Retry-After": str(outcome[1])},
            )
        if kind == "409":
            raise _http_error(url, 409, CONFLICT_DESCRIPTION)
        if kind == "401":
            raise _http_error(url, 401, "Unauthorized")
        if kind == "500":
            raise _http_error(url, 500, "Internal Server Error")
        raise AssertionError(f"unknown scripted outcome {outcome!r}")

    def _route(
        self, url: str, method: str, headers: dict[str, str], body: bytes
    ) -> _Response:
        if method == "getUpdates":
            return self._get_updates(body)
        if method == "sendPhoto":
            return self._send_photo(headers, body)
        payload = json.loads(body.decode("utf-8"))
        assert isinstance(payload, dict)
        if method == "sendMessage":
            return self._send_message(payload)
        if method == "editMessageReplyMarkup":
            return self._edit_markup(url, payload)
        return self._answer_query(url, payload)

    def _ok(self, result: object) -> _Response:
        return _Response(200, {}, json.dumps({"ok": True, "result": result}).encode())

    def _get_updates(self, body: bytes) -> _Response:
        payload = json.loads(body.decode("utf-8"))
        offset = payload.get("offset")
        if offset is not None:
            assert isinstance(offset, int)
            kept: list[dict[str, object]] = []
            for update in self.updates:
                raw_uid = update["update_id"]
                assert isinstance(raw_uid, int)
                if raw_uid >= offset:
                    kept.append(update)
            self.updates = kept
            served = list(self.updates)
        else:
            served = list(self.updates)
        return self._ok(served)

    def _check_markup(self, url: str, markup: object) -> None:
        if not isinstance(markup, dict):
            raise _http_error(url, 400, "Bad Request: reply markup invalid")
        rows = markup.get("inline_keyboard", [])
        for row in rows:
            for button in row:
                data = button.get("callback_data", "")
                if utf16_units(str(data)) > 64:
                    raise _http_error(url, 400, "Bad Request: BUTTON_DATA_INVALID")

    def _send_photo(self, headers: dict[str, str], body: bytes) -> _Response:
        content_type = headers.get("content-type", "")
        assert "multipart/form-data" in content_type
        fields = _parse_multipart(content_type, body)
        raw_chat = fields["chat_id"][1].decode()
        assert raw_chat.lstrip("+-").isdigit()
        chat_id = int(raw_chat)
        caption = fields["caption"][1].decode("utf-8")
        markup = json.loads(fields["reply_markup"][1].decode("utf-8"))
        filename, photo = fields["photo"]
        assert filename == "card.png"
        assert photo[:8] == PNG_SIGNATURE, "photo bytes are not a PNG"
        if utf16_units(caption) > 1024:
            raise _http_error(
                url="photo", code=400, description="Bad Request: caption is too long"
            )
        self._check_markup("photo", markup)
        self.message_seq += 1
        self.markups[(chat_id, self.message_seq)] = markup
        return self._ok(
            {
                "message_id": self.message_seq,
                "chat": {"id": chat_id, "type": "private"},
                "date": 1790985600,
                "caption": caption,
            }
        )

    def _send_message(self, payload: dict[str, object]) -> _Response:
        text = payload.get("text", "")
        assert isinstance(text, str)
        if not (1 <= utf16_units(text) <= 4096):
            raise _http_error(
                url="message", code=400, description="Bad Request: text too long"
            )
        if "reply_markup" in payload:
            self._check_markup("message", payload["reply_markup"])
        self.message_seq += 1
        return self._ok(
            {
                "message_id": self.message_seq,
                "chat": {"id": payload.get("chat_id"), "type": "private"},
                "date": 1790985600,
                "text": text,
            }
        )

    def _edit_markup(self, url: str, payload: dict[str, object]) -> _Response:
        raw_chat = payload["chat_id"]
        raw_message = payload["message_id"]
        assert isinstance(raw_chat, int) and isinstance(raw_message, int)
        chat_id = raw_chat
        message_id = raw_message
        markup = payload["reply_markup"]
        self._check_markup(url, markup)
        key = (chat_id, message_id)
        if self.markups.get(key) == markup:
            raise _http_error(url, 400, NOT_MODIFIED_DESCRIPTION)
        self.markups[key] = markup
        return self._ok(
            {"message_id": message_id, "chat": {"id": chat_id}, "date": 1790985600}
        )

    def _answer_query(self, url: str, payload: dict[str, object]) -> _Response:
        query_id = str(payload.get("callback_query_id"))
        if query_id in self.expired_queries:
            raise _http_error(url, 400, QUERY_TOO_OLD_DESCRIPTION)
        return self._ok(True)


_SENTINEL: object = object()

#: Pass as ``data`` to omit the key from a callback update.
MISSING: object = object()


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny(*args: object, **kwargs: object) -> None:
        raise AssertionError("no sockets in tests")

    monkeypatch.setattr(socket.socket, "connect", _deny)
    monkeypatch.setattr(socket.socket, "bind", _deny)
