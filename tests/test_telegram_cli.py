"""CLI: send-sample, poll --once, interrupts and errors (synthetic only)."""

import urllib.request
from dataclasses import fields
from pathlib import Path

import pytest
from telegram_fake import (  # noqa: F401  (autouse fixture)
    FAKE_BOT_VALUE,
    FAKE_CHAT_ID,
    FakeTelegram,
    no_sockets,
)

from framework.store import EventStore
from framework.telegram.__main__ import main
from framework.telegram.client import TelegramClient
from framework.telegram.models import PollStats
from framework.telegram.sample import SAMPLE_CARD


def run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    argv: list[str],
    fake: FakeTelegram,
) -> tuple[int, object, object]:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    db = tmp_path / "ikigai.db"
    code = main(argv, client=TelegramClient(), db_path=db)
    assert fake.parse_mode_requests == []
    return code, db, fake


def zero_line() -> str:
    return " ".join(f"{item.name}=0" for item in fields(PollStats)) + "\n"


def test_send_sample_prints_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, _ = run_main(monkeypatch, tmp_path, ["send-sample"], FakeTelegram())
    assert code == 0
    out = capsys.readouterr().out
    assert out == f"sent card_id={SAMPLE_CARD.card_id} message_id=1001\n"


def test_poll_once_prints_every_field_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue(fake.text_update(1, "hello"))
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 0
    fields = [field for field in PollStats.__dataclass_fields__]
    assert len(fields) == 18
    line = capsys.readouterr().out.strip()
    parts = line.split(" ")
    assert [part.split("=")[0] for part in parts] == fields
    assert "unhandled=1" in parts


def test_keyboard_interrupt_prints_last_line_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue(fake.text_update(1, "hello"))
    calls = {"count": 0}
    original = fake._get_updates

    def flaky(body: bytes) -> object:
        calls["count"] += 1
        if calls["count"] > 1:
            raise KeyboardInterrupt()
        return original(body)

    fake._get_updates = flaky  # type: ignore[method-assign]
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll"], fake)
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 2
    assert "unhandled=1" in lines[0]
    assert lines[1] == lines[0]


def test_poll_once_http_error_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", ("500",))
    with caplog.at_level("DEBUG"):
        code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: getUpdates")
    assert "status 500" in captured.err
    assert FAKE_BOT_VALUE not in captured.err + caplog.text


def test_poll_once_timeout_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", "timeout-urlopen")
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: getUpdates network error")


def test_poll_once_malformed_json_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", "malformed")
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 1
    assert "invalid response" in capsys.readouterr().err


def test_poll_once_propagated_conflict_prints_description(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", ("409",))
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("error: getUpdates failed (status 409): Conflict:")


def test_poll_once_defaults_long_poll_to_zero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    seen: list[int] = []

    def spy(
        self: TelegramClient, offset: int | None, long_poll_s: int, **kwargs: object
    ) -> list[object]:
        seen.append(long_poll_s)
        raise KeyboardInterrupt()

    monkeypatch.setattr(TelegramClient, "get_updates", spy)
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll", "--once"], fake)
    assert code == 0
    assert seen == [0]
    assert capsys.readouterr().out == zero_line()


def test_poll_defaults_long_poll_to_fifty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    seen: list[int] = []

    def spy(
        self: TelegramClient, offset: int | None, long_poll_s: int, **kwargs: object
    ) -> list[object]:
        seen.append(long_poll_s)
        raise KeyboardInterrupt()

    monkeypatch.setattr(TelegramClient, "get_updates", spy)
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll"], fake)
    assert code == 0
    assert seen == [50]
    assert capsys.readouterr().out == zero_line()


def test_poll_conflict_then_interrupt_prints_conflicts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    fake.queue_script("getUpdates", ("409",), ("409",))
    calls = {"count": 0}
    original = fake._get_updates

    def flaky(body: bytes) -> object:
        calls["count"] += 1
        if calls["count"] > 2:
            raise KeyboardInterrupt()
        return original(body)

    fake._get_updates = flaky  # type: ignore[method-assign]
    code, _, _ = run_main(monkeypatch, tmp_path, ["poll"], fake)
    assert code == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3
    assert "conflicts=1" in lines[0]
    assert "conflicts=2" in lines[1]
    assert lines[2] == lines[1]


def test_malformed_cursor_prints_error_and_exits_one(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    db = tmp_path / "ikigai.db"
    store = EventStore(db)
    try:
        store.poll_transaction("telegram", [], {"offset": "bad", "foreign_total": 0})
    finally:
        store.close()
    code = main(["poll", "--once"], client=TelegramClient(), db_path=db)
    assert fake.parse_mode_requests == []
    assert code == 1
    captured = capsys.readouterr()
    assert captured.err == "error: telegram cursor is malformed\n"


def test_long_poll_out_of_range_is_argparse_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as info:
        run_main(monkeypatch, tmp_path, ["poll", "--long-poll", "51"], FakeTelegram())
    assert info.value.code == 2


def test_no_token_in_cli_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("DEBUG"):
        code, _, _ = run_main(monkeypatch, tmp_path, ["send-sample"], FakeTelegram())
    assert code == 0
    captured = capsys.readouterr()
    assert FAKE_BOT_VALUE not in captured.out + captured.err + caplog.text


def test_privacy_note_states_five_claims() -> None:
    text = (Path(__file__).resolve().parent.parent / "docs" / "PRIVACY.md").read_text(
        encoding="utf-8"
    )
    lines = text.splitlines()
    assert len(lines) < 30
    lowered = text.lower()
    assert "card text" in lowered and "chart" in lowered
    assert "why?" in lowered and "reason codes" in lowered
    assert "voice notes" in lowered and "pass through telegram" in lowered
    assert "stay on my machine" in lowered
    assert "only my own messages" in lowered
