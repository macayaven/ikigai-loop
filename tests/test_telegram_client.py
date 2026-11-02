"""Transport behaviour against the fake: retries, classes, timeouts (synthetic)."""

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from telegram_fake import (  # noqa: F401  (autouse fixture)
    FAKE_BOT_VALUE,
    FAKE_CHAT_ID,
    PNG_SIGNATURE,
    FakeTelegram,
    no_sockets,
)
from test_telegram_models import card as make_card

from framework.telegram import client as client_module
from framework.telegram.client import (
    TelegramApiError,
    TelegramAuthError,
    TelegramClient,
    TelegramConfigError,
    TelegramConflict,
    TelegramDeliveryUnknown,
    TelegramRateLimited,
    TelegramTransportError,
    _allowed_chat_id,
)
from framework.telegram.models import ChartData, ChartSeries
from framework.telegram.service import send_card

PHOTO = PNG_SIGNATURE + b"synthetic-image-bytes"


def make_client(monkeypatch: pytest.MonkeyPatch, fake: FakeTelegram) -> TelegramClient:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(client_module, "_open_url", fake)
    sleeps: list[float] = []
    return TelegramClient(sleep_fn=sleeps.append)  # type: ignore[arg-type]


def test_send_photo_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    message = client.send_photo(FAKE_CHAT_ID, PHOTO, "hello", {"inline_keyboard": []})
    assert message["message_id"] >= 1001
    assert len(fake.requests) == 1
    method, tail, _headers, _body, timeout = fake.requests[0]
    assert method == "sendPhoto"
    assert tail == "sendPhoto"
    assert timeout == 30.0


def test_no_parse_mode_in_any_recorded_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    client.call("answerCallbackQuery", {"callback_query_id": "q", "text": "ok"})
    for _, _, _, body, _ in fake.requests:
        assert b"parse_mode" not in body


def test_backoff_retries_sleep_1_2_4(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("500",), ("500",), ("500",))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1, 2, 4]


def test_backoff_gives_up_as_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("500",), ("500",), ("500",), ("500",))
    with pytest.raises(TelegramApiError, match=r"status 500"):
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})


def test_rate_limit_sleeps_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429", 7))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [7]


def test_rate_limit_over_300_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429", 400))
    with pytest.raises(TelegramRateLimited) as info:
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert info.value.retry_after == 400
    assert "retry_after=400" in str(info.value)
    assert isinstance(info.value, TelegramApiError)


def test_rate_limit_uses_header_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429-header", 3))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert sleeps == [3]


def test_auth_failure_on_401_and_404(monkeypatch: pytest.MonkeyPatch) -> None:
    for outcome in (("401",),):
        fake = FakeTelegram()
        client = make_client(monkeypatch, fake)
        fake.queue_script("sendMessage", outcome)
        with pytest.raises(TelegramAuthError):
            client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    monkeypatch.setattr(client_module, "_open_url", fake)
    fake.queue_script("nope", ("401",))
    with pytest.raises(TelegramAuthError):
        client.call("nope", {})


def test_conflict_only_on_get_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("getUpdates", ("409",))
    with pytest.raises(TelegramConflict):
        client.get_updates(None, 0)
    fake.queue_script("sendMessage", ("409",))
    with pytest.raises(TelegramApiError) as info:
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert not isinstance(info.value, TelegramConflict)


def test_get_updates_timeout_greater_than_long_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    updates = client.get_updates(None, 50)
    assert updates == []
    _, _, _, body, timeout = fake.requests[0]
    assert json.loads(body.decode())["timeout"] == 50
    assert timeout is not None and timeout > 50
    assert timeout == 65


def test_bad_token_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "synthetic bad value")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(client_module, "_open_url", fake)
    client = TelegramClient()
    with pytest.raises(TelegramConfigError) as info:
        client.call("sendMessage", {"text": "hi"})
    assert "TELEGRAM_BOT_TOKEN" in str(info.value)
    assert "synthetic bad value" not in str(info.value)
    assert fake.requests == []


def test_missing_token_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(client_module, "_open_url", fake)
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient().call("sendMessage", {"text": "hi"})


def test_token_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram(bot_value="2:second-synthetic-marker")
    monkeypatch.setattr(client_module, "_open_url", fake)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    client = TelegramClient()
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(TelegramConfigError):
        client.call("sendMessage", {"text": "hi"})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "2:second-synthetic-marker")
    assert client.call("sendMessage", {"text": "hi"})["text"] == "hi"


def test_chat_id_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert _allowed_chat_id() is None
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    assert _allowed_chat_id() == FAKE_CHAT_ID
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "not-a-number")
    assert _allowed_chat_id() is None


def test_bad_chat_id_raises_config_error_on_send(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "synthetic-bad-chat")
    monkeypatch.setattr(client_module, "_open_url", fake)
    db = Path(str(tmp_path)) / "ikigai.db"
    with pytest.raises(TelegramConfigError) as info:
        send_card(make_card(), _chart(), db_path=db)
    assert "TELEGRAM_CHAT_ID" in str(info.value)
    assert "synthetic-bad-chat" not in str(info.value)


def _chart():  # minimal chart payload for the send path
    series = ChartSeries(label="Build", earlier=1.0, prior=2.0, last=3.0)
    return ChartData(
        period_labels=("One", "Two", "Three"),
        screen=(series,),
        pushes=series,
        tally=(),
    )


def test_default_sleep_fn_is_time_sleep() -> None:
    assert TelegramClient().sleep_fn is time.sleep


def test_trailing_slashes_stripped_from_api_base() -> None:
    assert TelegramClient(api_base="https://api.telegram.org///").api_base == (
        "https://api.telegram.org"
    )


def test_transport_error_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", "timeout-urlopen")
    with pytest.raises(TelegramTransportError, match="network error"):
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"}, attempts=1)


def test_get_updates_carries_allowed_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    client.get_updates(None, 0)
    client.get_updates(5, 10)
    assert len(fake.requests) == 2
    for _, _, _, body, _ in fake.requests:
        assert json.loads(body.decode())["allowed_updates"] == [
            "message",
            "callback_query",
        ]


def test_html_502_body_is_a_server_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", "html-502", "html-502", "html-502", "html-502")
    with pytest.raises(TelegramApiError, match=r"status 502") as info:
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert not isinstance(info.value, TelegramTransportError)


def test_negative_retry_after_falls_back_to_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429", -5))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1]
    fake.queue_script("sendMessage", ("429-header", -3))
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1, 1]


def test_zero_retry_after_sleeps_network_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429", 0))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1]
    fake.queue_script("sendMessage", ("429-header", 0))
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1, 1]


def test_retries_sleep_1_2_4_on_call_and_photo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script(
        "sendMessage", "timeout-urlopen", "timeout-urlopen", "timeout-urlopen"
    )
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1, 2, 4]
    fake.queue_script(
        "sendPhoto", "connect-refused", "connect-refused", "connect-refused"
    )
    message = client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert message["message_id"] >= 1001
    assert sleeps == [1, 2, 4, 1, 2, 4]


def test_four_429s_raise_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", ("429", 7), ("429", 7), ("429", 7), ("429", 7))
    with pytest.raises(TelegramRateLimited) as info:
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert info.value.retry_after == 7


def test_chat_id_rejects_underscores_and_plus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1_000")
    assert _allowed_chat_id() is None
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "+5")
    assert _allowed_chat_id() is None
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-5")
    assert _allowed_chat_id() == -5


def test_photo_lost_response_after_accept_raises_delivery_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    before = fake.message_seq
    fake.queue_script("sendPhoto", "accept-then-timeout")
    with pytest.raises(TelegramDeliveryUnknown):
        client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert fake.message_seq == before + 1
    assert len(fake.requests) == 1


def test_photo_connect_refused_then_success_delivers_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendPhoto", "connect-refused")
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    message = client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert message["message_id"] >= 1001
    assert len(fake.requests) == 2
    assert sleeps == [1]


def test_photo_429_then_success_delivers_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendPhoto", ("429", 2))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    message = client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert message["message_id"] >= 1001
    assert len(fake.requests) == 2
    assert sleeps == [2]


def test_photo_5xx_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendPhoto", ("500",))
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    with pytest.raises(TelegramDeliveryUnknown):
        client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert len(fake.requests) == 1
    assert sleeps == []


def test_photo_read_timeout_does_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendPhoto", "timeout-read")
    with pytest.raises(TelegramDeliveryUnknown):
        client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert len(fake.requests) == 1


def test_photo_four_not_sent_raises_plain_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script(
        "sendPhoto",
        "connect-refused",
        "connect-refused",
        "connect-refused",
        "connect-refused",
    )
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    with pytest.raises(TelegramTransportError) as info:
        client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert not isinstance(info.value, TelegramDeliveryUnknown)
    assert len(fake.requests) == 4
    assert sleeps == [1, 2, 4]


def test_call_retries_unknown_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", "timeout-urlopen", "timeout-urlopen")
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    result = client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert result["text"] == "hi"
    assert sleeps == [1, 2]


class _RefusedConnection:
    """Fake connection whose request never reaches the server."""

    def __init__(self, host: str, timeout: float | None = None) -> None:
        self.sock = None

    def set_debuglevel(self, level: int) -> None:
        pass

    def request(self, *args: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("synthetic refused")

    def getresponse(self) -> object:
        raise AssertionError("no response without a request")

    def close(self) -> None:
        pass


class _LostConnection:
    """Fake connection that accepts the request then loses the response."""

    def __init__(self, host: str, timeout: float | None = None) -> None:
        self.sock = None

    def set_debuglevel(self, level: int) -> None:
        pass

    def request(self, *args: object, **kwargs: object) -> None:
        pass

    def getresponse(self) -> object:
        raise TimeoutError("synthetic lost response")

    def close(self) -> None:
        pass


def _post_request() -> urllib.request.Request:
    request = urllib.request.Request(
        "http://127.0.0.1/synthetic", data=b"{}", method="POST"
    )
    request.timeout = 30.0
    return request


def test_do_open_wraps_request_failure_in_urlerror() -> None:
    handler = urllib.request.AbstractHTTPHandler()
    with pytest.raises(urllib.error.URLError) as info:
        handler.do_open(_RefusedConnection, _post_request())  # type: ignore[arg-type]
    assert isinstance(info.value.reason, ConnectionRefusedError)


def test_do_open_leaves_getresponse_failure_raw() -> None:
    handler = urllib.request.AbstractHTTPHandler()
    with pytest.raises(TimeoutError) as info:
        handler.do_open(_LostConnection, _post_request())  # type: ignore[arg-type]
    assert not isinstance(info.value, urllib.error.URLError)


class _FakeRawSocket:
    """Socket stand-in: records the family, connects to nothing."""

    def __init__(self, family: int, socktype: int, proto: int = 0) -> None:
        _FAKE_SOCKET_FAMILIES.append(family)
        self.connected: tuple[str, int] | None = None

    def settimeout(self, timeout: float | None) -> None:
        pass

    def bind(self, address: object) -> None:
        pass

    def connect(self, address: tuple[str, int]) -> None:
        self.connected = address

    def setsockopt(self, *args: object) -> None:
        pass

    def close(self) -> None:
        pass


_FAKERESOLVER_CALLS: list[tuple[str, int]] = []
_FAKE_SOCKET_FAMILIES: list[int] = []


class _FakeContext:
    """TLS stand-in: records the server name, wraps nothing."""

    def __init__(self) -> None:
        self.names: list[str | None] = []

    def wrap_socket(self, sock: object, server_hostname: str | None = None) -> object:
        self.names.append(server_hostname)
        return sock


def test_ipv4_connection_uses_af_inet_and_real_tls_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FAKERESOLVER_CALLS.clear()
    _FAKE_SOCKET_FAMILIES.clear()

    def fake_getaddrinfo(
        host: str, port: int, family: int = 0, *args: object, **kwargs: object
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        _FAKERESOLVER_CALLS.append((host, family))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.9.8.7", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "socket", _FakeRawSocket)
    context = _FakeContext()
    conn = client_module._IPv4HTTPSConnection(
        "api.telegram.org",
        context=context,  # type: ignore[arg-type]
    )
    conn.connect()
    assert _FAKERESOLVER_CALLS == [("api.telegram.org", socket.AF_INET)]
    assert _FAKE_SOCKET_FAMILIES == [socket.AF_INET]
    assert context.names == ["api.telegram.org"]


def test_open_url_skips_ipv4_opener_off_the_bot_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, float | None]] = []
    sentinel = object()
    handler_kinds: list[tuple[type, ...]] = []

    class FakeOpener:
        def open(
            self, request: urllib.request.Request, timeout: float | None = None
        ) -> object:
            seen.append((request.full_url, timeout))
            return sentinel

    def _is(item: object, cls: type) -> bool:
        if isinstance(item, type):
            return issubclass(item, cls)
        return isinstance(item, cls)

    def fake_build_opener(*handlers: object, **kwargs: object) -> FakeOpener:
        handler_kinds.append(tuple(type(item) for item in handlers))
        for item in handlers:
            assert not _is(item, client_module._IPv4HTTPSHandler), (
                "no IPv4 opener off the Bot host"
            )
        assert any(_is(item, client_module._NoRedirect) for item in handlers), (
            "off-host path still refuses redirects"
        )
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    request = urllib.request.Request(
        "https://example.com/synthetic", data=b"{}", method="POST"
    )
    assert client_module._open_url(request, 5.0) is sentinel
    request = urllib.request.Request(
        "http://127.0.0.1/synthetic", data=b"{}", method="POST"
    )
    assert client_module._open_url(request, 5.0) is sentinel
    assert seen == [
        ("https://example.com/synthetic", 5.0),
        ("http://127.0.0.1/synthetic", 5.0),
    ]


def test_open_url_uses_ipv4_opener_for_bot_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[tuple[str, float | None]] = []
    result = object()
    seen_handlers: list[tuple[object, ...]] = []

    class FakeOpener:
        def open(
            self, request: urllib.request.Request, timeout: float | None = None
        ) -> object:
            built.append((request.full_url, timeout))
            return result

    def fake_build_opener(*handlers: object, **kwargs: object) -> FakeOpener:
        seen_handlers.append(handlers)
        return FakeOpener()

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    request = urllib.request.Request(
        "https://api.telegram.org/botsynthetic/sendMessage",
        data=b"{}",
        method="POST",
    )

    def _is(item: object, cls: type) -> bool:
        if isinstance(item, type):
            return issubclass(item, cls)
        return isinstance(item, cls)

    assert client_module._open_url(request, 7.0) is result
    assert built == [(request.full_url, 7.0)]
    assert len(seen_handlers) == 1
    assert any(_is(item, client_module._IPv4HTTPSHandler) for item in seen_handlers[0])
    assert any(_is(item, client_module._NoRedirect) for item in seen_handlers[0]), (
        "the Bot host path still refuses redirects"
    )


def test_open_url_never_installs_global_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = getattr(urllib.request, "_opener")  # noqa: B009 -- private by design

    class FakeOpener:
        def open(
            self, request: urllib.request.Request, timeout: float | None = None
        ) -> object:
            return object()

    def no_install(opener: object) -> object:
        raise AssertionError("must not install a global opener")

    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: FakeOpener())
    monkeypatch.setattr(urllib.request, "install_opener", no_install)
    request = urllib.request.Request(
        "https://api.telegram.org/botsynthetic/sendMessage",
        data=b"{}",
        method="POST",
    )
    client_module._open_url(request, 1.0)
    assert getattr(urllib.request, "_opener") is before  # noqa: B009 -- private by design


def test_no_redirect_handler_refuses_every_redirect() -> None:
    handler = client_module._NoRedirect()
    for code in (301, 302, 303, 307, 308):
        request = urllib.request.Request(
            "https://api.telegram.org/botsynthetic/sendPhoto",
            data=b"{}",
            method="POST",
        )
        assert (
            handler.redirect_request(request, None, code, "Moved", {}, "https://x/")
            is None
        )


def test_photo_3xx_raises_delivery_unknown_after_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendPhoto", "redirect-302")
    sleeps: list[float] = []
    client.sleep_fn = sleeps.append  # type: ignore[method-assign]
    with pytest.raises(TelegramDeliveryUnknown, match="status 302"):
        client.send_photo(FAKE_CHAT_ID, PHOTO, "hi", {"inline_keyboard": []})
    assert len(fake.requests) == 1
    assert sleeps == []
    assert fake.message_seq == 1000


def test_other_methods_treat_3xx_as_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeTelegram()
    client = make_client(monkeypatch, fake)
    fake.queue_script("sendMessage", "redirect-302")
    with pytest.raises(TelegramApiError, match="status 302") as info:
        client.call("sendMessage", {"chat_id": FAKE_CHAT_ID, "text": "hi"})
    assert not isinstance(info.value, TelegramDeliveryUnknown)
    assert len(fake.requests) == 1
