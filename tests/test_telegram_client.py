"""Transport behaviour against the fake: retries, classes, timeouts (synthetic)."""

import json
import time
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

from framework.telegram.client import (
    TelegramApiError,
    TelegramAuthError,
    TelegramClient,
    TelegramConfigError,
    TelegramConflict,
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
    monkeypatch.setattr(urllib.request, "urlopen", fake)
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
    monkeypatch.setattr(urllib.request, "urlopen", fake)
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
    monkeypatch.setattr(urllib.request, "urlopen", fake)
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
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramClient().call("sendMessage", {"text": "hi"})


def test_token_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTelegram(bot_value="2:second-synthetic-marker")
    monkeypatch.setattr(urllib.request, "urlopen", fake)
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
    monkeypatch.setattr(urllib.request, "urlopen", fake)
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
        "sendPhoto", "timeout-urlopen", "timeout-urlopen", "timeout-urlopen"
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
