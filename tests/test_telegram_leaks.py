"""Token-secrecy shape: the value never escapes into errors, logs or tables."""

import logging
import sqlite3
import traceback
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from telegram_fake import (  # noqa: F401  (autouse fixture)
    FAKE_BOT_VALUE,
    FAKE_CHAT_ID,
    FakeTelegram,
    no_sockets,
)
from test_telegram_chart import data as chart_data
from test_telegram_models import card as make_card

from framework.store import EventStore
from framework.telegram.client import (
    TelegramApiError,
    TelegramClient,
    TelegramConfigError,
    TelegramError,
    TelegramTransportError,
)
from framework.telegram.ledger import CardLedger
from framework.telegram.service import poll_once, run_poll_loop, send_card

RAW_NEWLINE_VALUE = FAKE_BOT_VALUE + "\n"
INNER_SPACE_VALUE = "1:synthetic token-marker"


def run_call(
    monkeypatch: pytest.MonkeyPatch,
    fake: FakeTelegram,
    token_value: str,
    method: str = "sendMessage",
    payload: dict[str, object] | None = None,
) -> TelegramError:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token_value)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(TelegramError) as info:
        TelegramClient().call(method, payload or {"text": "hi"}, attempts=1)
    return info.value


def assert_scrubbed(
    exc: BaseException, secret: str, raw_secret: str | None = None
) -> None:
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    while queue:
        current = queue.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        assert secret not in str(current), f"secret in str({current!r})"
        assert secret not in repr(current)
        for arg in getattr(current, "args", ()):
            assert secret not in repr(arg)
        for key, value in vars(current).items():
            assert secret not in repr(key), f"secret in attr name {key!r}"
            assert secret not in repr(value), f"secret in attr {key!r}"
        cause = current.__cause__
        context = current.__context__
        if isinstance(cause, BaseException):
            queue.append(cause)
        if isinstance(context, BaseException):
            queue.append(context)
    rendered = "".join(traceback.format_exception(exc))
    assert secret not in rendered
    # capture_locals also records the test's own frame and the fake, both of
    # which hold the value on purpose; the product must not hold it anywhere.
    captured = traceback.TracebackException.from_exception(exc, capture_locals=True)
    for frame in captured.stack:
        if "/tests/" in frame.filename:
            continue
        assert secret not in repr(frame.locals), (
            f"secret in locals of {frame.filename}:{frame.lineno}"
        )
    if raw_secret is not None and raw_secret != secret:
        for frame in captured.stack:
            if "/tests/" in frame.filename:
                continue
            assert raw_secret not in repr(frame.locals)
            assert repr(raw_secret) not in repr(frame.locals)


def assert_tables_clean(db_path: Path, secret: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert tables, "expected tables in the scratch database"
        blob = b""
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"').fetchall():
                blob += repr(row).encode("utf-8", errors="replace")
        assert secret.encode() not in blob
    finally:
        conn.close()


def prime_tables(db_path: Path) -> None:
    store = EventStore(db_path)
    store.get_cursor("telegram")
    store.close()
    CardLedger(db_path).record_voice_arrival(1, "2026-11-02T18:00:00+00:00", 5)


def test_http_error_scrubs_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue_script("sendMessage", ("500",))
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE, "sendMessage")
    # The fake only serves failures after asserting the value reached it.
    assert fake.requests, "fake must have seen the request"
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    out, err = capsys.readouterr()
    assert FAKE_BOT_VALUE not in out + err
    assert FAKE_BOT_VALUE not in caplog.text


def test_urlopen_timeout_scrubs_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTelegram()
    fake.queue_script("sendMessage", "timeout-urlopen")
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE)
    assert isinstance(exc, TelegramTransportError)
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    assert FAKE_BOT_VALUE not in caplog.text


def test_read_timeout_scrubs_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTelegram()
    fake.queue_script("sendMessage", "timeout-read")
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE)
    assert isinstance(exc, TelegramTransportError)
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    assert FAKE_BOT_VALUE not in caplog.text


def test_malformed_echo_body_scrubs_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "ikigai.db"
    prime_tables(db_path)
    fake = FakeTelegram()
    fake.queue_script("sendMessage", "echo-url")
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE)
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    out, err = capsys.readouterr()
    assert FAKE_BOT_VALUE not in out + err
    assert FAKE_BOT_VALUE not in caplog.text
    assert_tables_clean(db_path, FAKE_BOT_VALUE)


def test_urlopen_error_holding_url_scrubs_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTelegram()
    fake.queue_script("sendMessage", "error-with-url")
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE)
    assert isinstance(exc, TelegramTransportError)
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    assert FAKE_BOT_VALUE not in caplog.text


def test_bad_api_base_is_a_network_error_without_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with caplog.at_level("DEBUG"), pytest.raises(TelegramTransportError) as info:
        TelegramClient(api_base="not-a-url").call(
            "sendMessage", {"text": "hi"}, attempts=1
        )
    assert_scrubbed(info.value, FAKE_BOT_VALUE)
    assert quote(FAKE_BOT_VALUE, safe="") not in str(info.value)
    assert fake.requests == []
    out, err = capsys.readouterr()
    assert FAKE_BOT_VALUE not in out + err
    assert FAKE_BOT_VALUE not in caplog.text


def test_json_error_echoing_url_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "ikigai.db"
    prime_tables(db_path)
    fake = FakeTelegram()
    fake.queue_script("sendMessage", "echo-json", "echo-json")
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, FAKE_BOT_VALUE, "sendMessage")
    assert isinstance(exc, TelegramApiError)
    assert "[redacted]" in str(exc)
    assert exc.description is not None and "[redacted]" in exc.description
    assert_scrubbed(exc, FAKE_BOT_VALUE)
    assert quote(FAKE_BOT_VALUE, safe="") not in str(exc)
    assert quote(FAKE_BOT_VALUE, safe="") not in (exc.description or "")
    out, err = capsys.readouterr()
    assert FAKE_BOT_VALUE not in out + err
    assert FAKE_BOT_VALUE not in caplog.text
    assert_tables_clean(db_path, FAKE_BOT_VALUE)


def test_trailing_newline_value_scrubbed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTelegram()
    fake.queue_script("sendMessage", ("500",))
    with caplog.at_level("DEBUG"):
        exc = run_call(monkeypatch, fake, RAW_NEWLINE_VALUE)
    # Stripped form reaches the URL (fake asserts it); both forms stay secret.
    assert fake.requests, "stripped value must have reached the fake"
    assert_scrubbed(exc, FAKE_BOT_VALUE, RAW_NEWLINE_VALUE)
    assert FAKE_BOT_VALUE not in caplog.text


def test_inner_space_value_never_leaves(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeTelegram()
    with caplog.at_level("DEBUG"):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", INNER_SPACE_VALUE)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
        monkeypatch.setattr(urllib.request, "urlopen", fake)
        with pytest.raises(TelegramConfigError) as info:
            TelegramClient().call("sendMessage", {"text": "hi"})
    assert_scrubbed(info.value, INNER_SPACE_VALUE)
    assert fake.requests == []
    assert INNER_SPACE_VALUE not in caplog.text


def test_tables_clean_after_real_flow_with_echo_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "ikigai.db"
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    quiet = TelegramClient(sleep_fn=lambda _s: None)
    sent = send_card(make_card(), chart_data(), db_path=db_path, client=quiet)
    t0 = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    moments = [t0 + timedelta(seconds=n) for n in range(4)]
    fake.queue(fake.callback_update(1, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(2, "q2", f"{sent.card_id}:why"))
    fake.queue(fake.callback_update(3, "q3", f"{sent.card_id}:wrong"))
    fake.queue(fake.voice_update(4))
    fake.queue(fake.text_update(5, "stranger", user_id=999, chat_id=999))
    fake.queue_script("sendMessage", "echo-url", "echo-url")
    with caplog.at_level("DEBUG"):
        stats = poll_once(db_path=db_path, client=quiet, now_fn=lambda: moments.pop(0))
    assert stats.stored == 3
    assert stats.side_effect_errors == 1
    assert stats.foreign == 1
    assert fake.parse_mode_requests == []
    out, err = capsys.readouterr()
    assert FAKE_BOT_VALUE not in out + err
    assert FAKE_BOT_VALUE not in caplog.text
    assert_tables_clean(db_path, FAKE_BOT_VALUE)


def test_debug_log_names_cause_without_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", "html-502", "timeout-urlopen", ("409",))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    db_path = tmp_path / "ikigai.db"
    calls = {"count": 0}

    def stop() -> bool:
        calls["count"] += 1
        if calls["count"] > 50:
            raise AssertionError("run_poll_loop did not stop")
        return len(fake.requests) >= 4

    with caplog.at_level("DEBUG"):
        total = run_poll_loop(
            db_path=db_path,
            client=TelegramClient(sleep_fn=lambda _s: None),
            sleep_fn=lambda _s: None,
            stop=stop,
        )
    assert total.poll_errors == 2
    assert total.conflicts == 1
    assert "getUpdates failed with status 502" in caplog.text
    assert "TelegramApiError" in caplog.text
    assert "TelegramTransportError" in caplog.text
    assert "TelegramConflict" in caplog.text
    assert FAKE_BOT_VALUE not in caplog.text
    assert all(record.levelno <= logging.DEBUG for record in caplog.records)


def test_malformed_chat_value_never_leaves(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    bad_chat = "synthetic-bad-chat"
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", bad_chat)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with caplog.at_level("DEBUG"), pytest.raises(TelegramConfigError) as info:
        poll_once()
    assert_scrubbed(info.value, bad_chat)
    assert fake.requests == []
    assert bad_chat not in caplog.text
