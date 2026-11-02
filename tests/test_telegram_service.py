"""Send and poll end to end on the fake: rulings, filters, replies (synthetic)."""

import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from telegram_fake import (  # noqa: F401  (autouse fixture)
    FAKE_BOT_VALUE,
    FAKE_CHAT_ID,
    MISSING,
    NOT_MODIFIED_DESCRIPTION,
    FakeTelegram,
    no_sockets,
)
from test_telegram_chart import data as chart_data
from test_telegram_models import card as make_card
from test_telegram_models import proposal

from framework.store import EventStore
from framework.telegram import client as client_module
from framework.telegram import service
from framework.telegram.chart import render_chart_png
from framework.telegram.client import (
    TelegramAuthError,
    TelegramClient,
    TelegramConfigError,
    TelegramConflict,
    TelegramDeliveryUnknown,
)
from framework.telegram.ledger import CardLedger
from framework.telegram.models import (
    Card,
    VoiceNote,
    first_rulings,
    render_card_text,
    split_messages,
    utf16_len,
)
from framework.telegram.sample import SAMPLE_CARD, SAMPLE_CHART
from framework.telegram.service import (
    load_card,
    poll_once,
    run_poll_loop,
    send_card,
)

T0 = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)


class Clock:
    def __init__(self, moments: list[datetime]) -> None:
        self.moments = list(moments)
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        if len(self.moments) > 1:
            return self.moments.pop(0)
        return self.moments[0]


def bounded(predicate: Callable[[], bool], limit: int = 50) -> Callable[[], bool]:
    """Stop for run_poll_loop that fails instead of looping forever.

    ``stop`` runs outside the loop's ``try``, so the AssertionError leaves
    the loop and fails the test instead of hanging the suite.
    """
    calls = {"count": 0}

    def stop() -> bool:
        calls["count"] += 1
        if calls["count"] > limit:
            raise AssertionError("run_poll_loop did not stop")
        return predicate()

    return stop


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[tuple[FakeTelegram, TelegramClient, Path]]:
    fake = FakeTelegram()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", FAKE_BOT_VALUE)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", str(FAKE_CHAT_ID))
    monkeypatch.setattr(client_module, "_open_url", fake)
    db = tmp_path / "ikigai.db"
    yield fake, TelegramClient(), db
    assert fake.parse_mode_requests == []


def tap_events(db: Path) -> list[Any]:
    store = EventStore(db)
    try:
        return store.events_between(
            "subject-1",
            datetime(2000, 1, 1, tzinfo=UTC),
            datetime(2030, 1, 1, tzinfo=UTC),
            types=["app.tap"],
        )
    finally:
        store.close()


def conflict_rows(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM conflicts").fetchone()[0])
    finally:
        conn.close()


def cursor(db: Path) -> Any:
    store = EventStore(db)
    try:
        return store.get_cursor("telegram")
    finally:
        store.close()


def ledger_rows(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        try:
            return int(
                conn.execute("SELECT COUNT(*) FROM telegram_cards").fetchone()[0]
            )
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


def bodies_for(fake: FakeTelegram, method: str) -> list[dict[str, Any]]:
    return [
        json.loads(body.decode())
        for name, _, _, body, _ in fake.requests
        if name == method
    ]


def send_two_sided(harness: tuple[FakeTelegram, TelegramClient, Path]) -> Any:
    _fake, client, db = harness
    return send_card(make_card(), chart_data(), db_path=db, client=client)


# -- AT5: restart and offset ----------------------------------------------


def test_restart_keeps_offset_and_foreign_total(
    harness: tuple[FakeTelegram, TelegramClient, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.text_update(10, "hello from a stranger", user_id=999, chat_id=999))
    fake.queue(fake.callback_update(11, "q1", f"{sent.card_id}:A"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0, T0]))
    assert stats.foreign == 1
    assert stats.stored == 1
    assert cursor(db) == {"foreign_total": 1, "offset": 12}
    # Restart: a new fake serves the same updates again on the same file.
    fake2 = FakeTelegram()
    fake2.queue(
        fake2.text_update(10, "hello from a stranger", user_id=999, chat_id=999)
    )
    fake2.queue(fake2.callback_update(11, "q1", f"{sent.card_id}:A"))
    monkeypatch.setattr(client_module, "_open_url", fake2)
    again = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert again.updates == 0
    assert again.stored == 0
    assert len(tap_events(db)) == 1
    assert cursor(db) == {"foreign_total": 1, "offset": 12}


def test_offset_advances_per_update_and_recovers_after_interrupt(
    harness: tuple[FakeTelegram, TelegramClient, Path],
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    for uid, query, target in (
        (20, "a", "A"),
        (21, "b", "B"),
        (22, "c", "neither"),
    ):
        fake.queue(fake.callback_update(uid, query, f"{sent.card_id}:{target}"))
    answers = {"count": 0}
    original_answer = fake._answer_query

    def flaky(url: str, payload: dict[str, Any]) -> Any:
        answers["count"] += 1
        if answers["count"] == 2:
            raise KeyboardInterrupt()
        return original_answer(url, payload)

    fake._answer_query = flaky  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        poll_once(
            db_path=db,
            client=client,
            now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
        )
    assert cursor(db) == {"foreign_total": 0, "offset": 21}
    fake._answer_query = original_answer  # type: ignore[method-assign]
    stats = poll_once(
        db_path=db, client=client, now_fn=Clock([T0 + timedelta(seconds=2)])
    )
    assert stats.stored == 1
    assert stats.duplicates == 1
    events = tap_events(db)
    assert len(events) == 3
    assert [e.source_id for e in events] == [
        f"{sent.card_id}:A",
        f"{sent.card_id}:B",
        f"{sent.card_id}:neither",
    ]


# -- AT6: double tap, A then B, fallback tap ------------------------------


def test_double_tap_stores_once_with_advancing_clock(
    harness: tuple[FakeTelegram, TelegramClient, Path],
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(30, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(31, "q2", f"{sent.card_id}:A"))
    clock = Clock([T0, T0 + timedelta(seconds=5)])
    stats = poll_once(db_path=db, client=client, now_fn=clock)
    assert stats.stored == 1
    assert stats.duplicates == 1
    assert conflict_rows(db) == 0
    assert clock.calls >= 2
    events = tap_events(db)
    assert len(events) == 1
    assert events[0].time == T0
    # The second tap re-edits the same keyboard, which the fake refuses as
    # not-modified; the service matches that by substring and stays silent.
    edits = bodies_for(fake, "editMessageReplyMarkup")
    assert len(edits) == 2
    assert stats.side_effect_errors == 0
    assert stats.answered == 2

    assert "message is not modified" in NOT_MODIFIED_DESCRIPTION.lower()


def test_a_then_b_keeps_first_ruling_on_keyboard(
    harness: tuple[FakeTelegram, TelegramClient, Path],
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(40, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(41, "q2", f"{sent.card_id}:B"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=5)]),
    )
    assert stats.stored == 2
    assert first_rulings(tap_events(db)) == {sent.card_id: "A"}
    answers = bodies_for(fake, "answerCallbackQuery")
    assert answers[0]["text"] == "Recorded: Take A"
    assert answers[1]["text"] == "Stored. Standing ruling: Take A"
    edits = bodies_for(fake, "editMessageReplyMarkup")
    assert edits[-1]["reply_markup"]["inline_keyboard"][0][0]["text"] == (
        "\u2713 Take A"
    )


def test_fallback_tap_stores_normal_event(
    harness: tuple[FakeTelegram, TelegramClient, Path],
) -> None:
    fake, client, db = harness
    card = make_card(
        proposals=[
            make_card(proposals=[proposal("A", "proposal")]).proposals[0],
            proposal(
                "B",
                "fallback",
                profile="Disconnect",
                title="Family call",
                reason_codes=["gate.ok"],
            ),
        ]
    )
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(50, "q1", f"{sent.card_id}:B"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.stored == 1
    assert first_rulings(tap_events(db)) == {sent.card_id: "B"}


Harness = tuple[FakeTelegram, TelegramClient, Path]


def _last_markup(fake: FakeTelegram) -> dict[str, Any]:
    keys = sorted(fake.markups)
    assert keys, "fake stored no markup"
    markup = fake.markups[keys[-1]]
    assert isinstance(markup, dict)
    return markup


# -- AT7: buttons on one- and two-proposal cards --------------------------


def test_buttons_on_two_proposal_card(harness: Harness) -> None:
    fake, _client, _db = harness
    sent = send_two_sided(harness)
    markup = _last_markup(fake)
    rows = markup["inline_keyboard"]
    assert [b["text"] for b in rows[0]] == ["Take A"]
    assert [b["text"] for b in rows[1]] == ["Take B"]
    assert [b["text"] for b in rows[2]] == ["Neither now", "Why?"]
    assert [b["text"] for b in rows[3]] == ["Something's wrong"]
    for row in rows:
        for button in row:
            assert len(button["callback_data"].encode()) <= 64
            assert button["callback_data"].startswith(sent.card_id)


def test_buttons_on_one_proposal_cards(harness: Harness) -> None:
    fake, client, db = harness
    only_a = make_card(proposals=[proposal("A", "proposal")])
    send_card(only_a, chart_data(), db_path=db, client=client)
    rows_a = _last_markup(fake)["inline_keyboard"]
    assert [b["text"] for b in rows_a[0]] == ["Take A"]
    assert [b["text"] for b in rows_a[1]] == ["Neither now", "Why?"]
    assert [b["text"] for b in rows_a[2]] == ["Something's wrong"]
    assert len(rows_a) == 3
    only_b = make_card(
        proposals=[proposal("B", "proposal", profile="Disconnect", title="Family call")]
    )
    send_card(only_b, chart_data(), db_path=db, client=client)
    rows_b = _last_markup(fake)["inline_keyboard"]
    assert [b["text"] for b in rows_b[0]] == ["Take B"]
    assert [b["text"] for b in rows_b[1]] == ["Neither now", "Why?"]
    assert [b["text"] for b in rows_b[2]] == ["Something's wrong"]


# -- AT8: foreign, unhandled, odd shapes ----------------------------------


def test_foreign_updates_make_no_calls_and_still_advance(
    harness: Harness,
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    base_calls = len(fake.requests)
    fake.queue(fake.text_update(60, "stranger", user_id=999, chat_id=FAKE_CHAT_ID))
    fake.queue(fake.text_update(61, "other chat", user_id=FAKE_CHAT_ID, chat_id=777))
    fake.queue(
        {
            "update_id": 62,
            "callback_query": {
                "id": "q-foreign",
                "from": {"id": 999, "is_bot": False},
                "message": {
                    "message_id": 55,
                    "chat": {"id": FAKE_CHAT_ID, "type": "private"},
                },
                "data": f"{sent.card_id}:A",
            },
        }
    )
    fake.queue(fake.voice_update(63, user_id=999, chat_id=999))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.foreign == 4
    assert len(fake.requests) == base_calls + 1
    assert all(name == "getUpdates" for name, *_ in fake.requests[base_calls:])
    assert tap_events(db) == []
    assert cursor(db) == {"foreign_total": 4, "offset": 64}


def test_unhandled_text_message_from_me(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    fake.queue(fake.text_update(70, "just typing"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.unhandled == 1
    assert bodies_for(fake, "sendMessage") == []
    assert tap_events(db) == []
    assert cursor(db) == {"foreign_total": 0, "offset": 71}


def test_odd_shape_not_a_dict_or_bad_update_id(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    fake.queue("not-a-dict")  # type: ignore[arg-type]
    fake.queue({"callback_query": {}})
    fake.queue({"update_id": "7"})
    fake.queue({"update_id": True})
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.malformed == 4
    assert cursor(db) is None


def test_odd_shape_update_with_no_kind_is_unhandled(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    fake.queue({"update_id": 80})
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.unhandled == 1
    assert cursor(db) == {"foreign_total": 0, "offset": 81}


def test_odd_shape_bad_identity_is_foreign(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    base = len(fake.requests)
    fake.queue({"update_id": 90, "message": {"message_id": 1}})
    fake.queue(
        {
            "update_id": 91,
            "callback_query": {
                "id": "q",
                "from": {"id": True, "is_bot": False},
                "message": {
                    "message_id": 55,
                    "chat": {"id": FAKE_CHAT_ID, "type": "private"},
                },
                "data": "x",
            },
        }
    )
    fake.queue(
        {
            "update_id": 92,
            "callback_query": {
                "id": "q",
                "from": {"id": FAKE_CHAT_ID, "is_bot": False},
            },
        }
    )
    # String ids matching the allowed id are still foreign: the builders
    # refuse strings, so these arrive as raw dicts.
    allowed_str = str(FAKE_CHAT_ID)
    fake.queue(
        {
            "update_id": 93,
            "callback_query": {
                "id": "q-str",
                "from": {"id": allowed_str, "is_bot": False},
                "message": {
                    "message_id": 55,
                    "chat": {"id": allowed_str, "type": "private"},
                },
                "data": "card-0123456789abcdef:A",
            },
        }
    )
    fake.queue(
        {
            "update_id": 94,
            "message": {
                "message_id": 56,
                "from": {"id": allowed_str, "is_bot": False},
                "chat": {"id": allowed_str, "type": "private"},
                "date": 1790985600,
                "text": "string ids are not me",
            },
        }
    )
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.foreign == 5
    assert len(fake.requests) == base + 1
    assert all(name == "getUpdates" for name, *_ in fake.requests[base:])
    assert cursor(db) == {"foreign_total": 5, "offset": 95}


def test_foreign_one_sided_string_or_bool_ids_stay_foreign(
    harness: Harness,
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    base = len(fake.requests)
    allowed_str = str(FAKE_CHAT_ID)
    pairs = [
        (allowed_str, FAKE_CHAT_ID),
        (FAKE_CHAT_ID, allowed_str),
        (True, FAKE_CHAT_ID),
        (FAKE_CHAT_ID, True),
    ]
    uid = 300
    for pos, (user_id, chat_id) in enumerate(pairs):
        fake.queue(
            {
                "update_id": uid + pos,
                "callback_query": {
                    "id": f"q-one-sided-{pos}",
                    "from": {"id": user_id, "is_bot": False},
                    "message": {
                        "message_id": 55,
                        "chat": {"id": chat_id, "type": "private"},
                    },
                    "data": f"{sent.card_id}:A",
                },
            }
        )
    for pos, (user_id, chat_id) in enumerate(pairs):
        fake.queue(
            {
                "update_id": uid + 4 + pos,
                "message": {
                    "message_id": 56,
                    "from": {"id": user_id, "is_bot": False},
                    "chat": {"id": chat_id, "type": "private"},
                    "date": 1790985600,
                    "text": "one-sided id",
                },
            }
        )
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.foreign == 8
    assert len(fake.requests) == base + 1
    assert all(name == "getUpdates" for name, *_ in fake.requests[base:])
    assert tap_events(db) == []
    assert cursor(db) == {"foreign_total": 8, "offset": 308}


def test_odd_shape_callback_without_usable_id_is_malformed(
    harness: Harness,
) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    message = {
        "message_id": 55,
        "chat": {"id": FAKE_CHAT_ID, "type": "private"},
    }
    me = {"id": FAKE_CHAT_ID, "is_bot": False}
    fake.queue(
        {
            "update_id": 100,
            "callback_query": {"from": me, "message": message, "data": "x"},
        }
    )
    fake.queue(
        {
            "update_id": 101,
            "callback_query": {
                "id": 7,
                "from": me,
                "message": message,
                "data": "x",
            },
        }
    )
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.malformed == 2
    assert bodies_for(fake, "answerCallbackQuery") == []
    assert cursor(db) == {"foreign_total": 0, "offset": 102}


def test_odd_shape_bad_callback_data_is_invalid(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(110, "q1", MISSING))
    fake.queue(fake.callback_update(111, "q2", 42))
    fake.queue(fake.callback_update(112, "q3", "bogus"))
    fake.queue(fake.callback_update(113, "q4", f"{sent.card_id}:C"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.invalid == 4
    answers = bodies_for(fake, "answerCallbackQuery")
    assert [a["text"] for a in answers] == ["That button is not on this card."] * 4
    assert tap_events(db) == []
    assert cursor(db) == {"foreign_total": 0, "offset": 114}


def test_odd_shape_bad_voice_is_malformed(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    fake.queue(fake.voice_update(120, file_id=None))
    fake.queue(fake.voice_update(121, duration="long"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.malformed == 2
    assert stats.voice == 0
    assert cursor(db) == {"foreign_total": 0, "offset": 122}


# -- AT9: voice ------------------------------------------------------------


def test_voice_note_reaches_handler_and_default_stores_arrival(
    harness: Harness,
) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    seen: list[VoiceNote] = []
    fake.queue(fake.voice_update(130, reply_to=55))
    stats = poll_once(
        db_path=db, client=client, now_fn=Clock([T0]), on_voice=seen.append
    )
    assert stats.voice == 1
    (note,) = seen
    assert note.message_id == 57
    assert note.file_id == "synthetic-file-id"
    assert note.duration_s == 12
    assert note.reply_to_message_id == 55
    # Default handler: one arrival row, no file id anywhere in the database.
    fake.queue(fake.voice_update(131, message_id=131))
    default_stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert default_stats.voice == 1
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT message_id, duration_s FROM telegram_voice_arrivals"
        ).fetchall()
        blob = repr(conn.execute("SELECT * FROM telegram_voice_arrivals").fetchall())
    finally:
        conn.close()
    assert rows == [(131, 12)]
    assert "synthetic-file-id" not in blob
    # Re-delivery adds no row.
    fake.queue(fake.voice_update(132, message_id=131))
    redelivered = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert redelivered.voice == 1
    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM telegram_voice_arrivals").fetchone()[
            0
        ]
    finally:
        conn.close()
    assert count == 1


def test_voice_raising_handler_counts_and_advances(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.voice_update(140))

    def boom(note: object) -> None:
        raise RuntimeError("synthetic handler failure")

    fake.queue(fake.callback_update(141, "q1", f"{sent.card_id}:A"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]), on_voice=boom)
    assert stats.voice_errors == 1
    assert stats.stored == 1
    assert cursor(db) == {"foreign_total": 0, "offset": 142}


# -- AT10: why, wrong, unknown card, invalid letter -------------------------


def mixed_card_with_statements() -> Card:

    return make_card(
        statements=["First cited line.", "Second cited line."],
        proposals=[
            proposal("A", "proposal"),
            proposal(
                "B",
                "fallback",
                profile="Disconnect",
                title="Family call",
                reason_codes=["gate.ok", "other:1"],
            ),
        ],
    )


def test_why_on_mixed_card_replies_verbatim(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_card(
        mixed_card_with_statements(), chart_data(), db_path=db, client=client
    )
    fake.queue(fake.callback_update(150, "q1", f"{sent.card_id}:why"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.stored == 1
    answers = bodies_for(fake, "answerCallbackQuery")
    assert answers[0]["text"] == "Sending the cited statements."
    assert bodies_for(fake, "editMessageReplyMarkup") == []
    (reply,) = bodies_for(fake, "sendMessage")
    assert reply["disable_notification"] is True
    assert reply["reply_parameters"]["message_id"] == 55
    assert reply["reply_parameters"]["allow_sending_without_reply"] is True
    assert reply["link_preview_options"] == {"is_disabled": True}
    assert reply["text"] == (
        "First cited line.\n\nSecond cited line.\n\n"
        "B has no checked facts this time. Reason codes: gate.ok, other:1."
    )


def test_why_on_fallback_only_cards(harness: Harness) -> None:
    fake, client, db = harness
    card = make_card(
        since_line=None,
        proposals=[
            proposal("A", "fallback"),
            proposal(
                "B",
                "fallback",
                profile="Disconnect",
                title="Family call",
                reason_codes=["gate.ok"],
            ),
        ],
    )
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(160, "q1", f"{sent.card_id}:why"))
    poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    (reply,) = bodies_for(fake, "sendMessage")
    assert reply["text"] == (
        "No cited statements on this card.\n\n"
        "A has no checked facts this time.\n\n"
        "B has no checked facts this time. Reason codes: gate.ok."
    )
    assert reply["disable_notification"] is True


def test_why_without_fallback_sends_statements_alone(
    harness: Harness,
) -> None:
    fake, client, db = harness
    card = make_card(statements=["Only line."])
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(161, "q1", f"{sent.card_id}:why"))
    poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    (reply,) = bodies_for(fake, "sendMessage")
    assert reply["text"] == "Only line."


def test_why_splits_oversized_statement_at_surrogate_boundary(
    harness: Harness,
) -> None:
    piece = "a" * 3000 + "\U0001f600" * 500 + "b" * 2000
    assert utf16_len(piece) > 4096
    messages = split_messages([piece])
    assert len(messages) >= 2
    for text in messages:
        assert utf16_len(text) <= 4096
        text.encode("utf-16-le").decode("utf-16-le")
    assert "".join(messages) == piece
    fake, client, db = harness
    card = make_card(statements=[piece])
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(162, "q1", f"{sent.card_id}:why"))
    poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    replies = bodies_for(fake, "sendMessage")
    assert len(replies) >= 2
    for reply in replies:
        assert utf16_len(reply["text"]) <= 4096
        reply["text"].encode("utf-16-le").decode("utf-16-le")
    assert "".join(r["text"] for r in replies) == piece


def test_why_statement_arrives_verbatim(harness: Harness) -> None:
    fake, client, db = harness
    statement = "  leading kept\ninner newline kept  "
    card = make_card(statements=[statement])
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(163, "q1", f"{sent.card_id}:why"))
    poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    (reply,) = bodies_for(fake, "sendMessage")
    assert reply["text"].encode() == statement.encode()


def test_why_twice_replies_twice_but_stores_once(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(164, "q1", f"{sent.card_id}:why"))
    fake.queue(fake.callback_update(165, "q2", f"{sent.card_id}:why"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.stored == 1
    assert stats.duplicates == 1
    answers = bodies_for(fake, "answerCallbackQuery")
    assert [a["text"] for a in answers] == ["Sending the cited statements."] * 2
    assert len(bodies_for(fake, "sendMessage")) == 2


def test_unknown_card_why_and_ruling_store_without_reply(
    harness: Harness,
) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    unknown = "card-" + "0" * 16
    fake.queue(fake.callback_update(170, "q1", f"{unknown}:why"))
    fake.queue(fake.callback_update(171, "q2", f"{unknown}:A"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.stored == 2
    answers = bodies_for(fake, "answerCallbackQuery")
    assert answers[0]["text"] == "I no longer have that card."
    assert answers[1]["text"] == "Recorded: Take A"
    assert bodies_for(fake, "sendMessage") == []
    edits = bodies_for(fake, "editMessageReplyMarkup")
    assert edits, "the ruling edit is attempted even for an unknown card"
    assert first_rulings(tap_events(db)) == {unknown: "A"}


def test_invalid_letter_is_answered_and_not_stored(
    harness: Harness,
) -> None:
    fake, client, db = harness
    card = make_card(proposals=[proposal("A", "proposal")])
    sent = send_card(card, chart_data(), db_path=db, client=client)
    fake.queue(fake.callback_update(180, "q1", f"{sent.card_id}:B"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.invalid == 1
    assert bodies_for(fake, "answerCallbackQuery")[0]["text"] == (
        "That button is not on this card."
    )
    assert tap_events(db) == []


def test_wrong_sends_voice_request_once(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(190, "q1", f"{sent.card_id}:wrong"))
    fake.queue(fake.callback_update(191, "q2", f"{sent.card_id}:wrong"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.stored == 1
    assert stats.duplicates == 1
    answers = bodies_for(fake, "answerCallbackQuery")
    assert answers[0]["text"] == "Noted. Voice note please."
    assert answers[1]["text"] == "Already noted for this card."
    (request,) = bodies_for(fake, "sendMessage")
    assert request["text"] == "Tell me what is wrong in a voice note."
    assert request["disable_notification"] is True
    assert request["reply_parameters"]["message_id"] == 55
    assert bodies_for(fake, "editMessageReplyMarkup") == []


# -- AT11: poison, store failure, handler error, answered on --------------


def test_poison_ledger_row_counts_handler_error_and_advances(
    harness: Harness,
) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    bad_id = "card-" + "1" * 16
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO telegram_cards (card_id, card_json, created_at)"
            " VALUES (?, ?, ?)",
            (bad_id, '{"nope": true}', "2026-11-02T18:00:00+00:00"),
        )
        conn.commit()
    finally:
        conn.close()
    fake.queue(fake.callback_update(200, "q1", f"{bad_id}:A"))
    fake.queue(fake.callback_update(201, "q2", f"{bad_id}:A"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.handler_errors == 2
    answers = bodies_for(fake, "answerCallbackQuery")
    assert [a["text"] for a in answers] == ["Could not handle that tap."] * 2
    assert tap_events(db) == []
    assert cursor(db) == {"foreign_total": 0, "offset": 202}


def test_store_failure_stops_batch_and_next_poll_recovers(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:

    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(210, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(211, "q2", f"{sent.card_id}:neither"))
    original = EventStore.append_event
    calls = {"count": 0}

    def flaky(self: EventStore, event: Any) -> bool:
        calls["count"] += 1
        if calls["count"] == 1:
            raise sqlite3.Error("synthetic disk failure")
        return original(self, event)

    monkeypatch.setattr(EventStore, "append_event", flaky)
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.store_errors == 1
    assert stats.stored == 0
    answers = bodies_for(fake, "answerCallbackQuery")
    assert answers == [
        {"callback_query_id": "q1", "text": ("Not stored yet. Retrying.")}
    ]
    assert cursor(db) is None
    monkeypatch.setattr(EventStore, "append_event", original)
    recovered = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0 + timedelta(seconds=2), T0 + timedelta(seconds=3)]),
    )
    assert recovered.stored == 2
    events = tap_events(db)
    assert [e.source_id for e in events] == [
        f"{sent.card_id}:A",
        f"{sent.card_id}:neither",
    ]
    reloaded = load_card(sent.card_id, db_path=db)
    assert reloaded is not None
    assert reloaded.card_id == sent.card_id
    # Stored JSON round trip for a non-UTC card with codes and no since_line.

    plus_one = timezone(timedelta(hours=1))
    offset_card = make_card(
        slot=datetime(2026, 11, 2, 17, 0, tzinfo=plus_one),
        since_line=None,
        statements=[],
        proposals=[
            proposal(
                "A",
                "fallback",
                start=datetime(2026, 11, 2, 17, 0, tzinfo=plus_one),
                end=datetime(2026, 11, 2, 17, 25, tzinfo=plus_one),
            ),
            proposal(
                "B",
                "fallback",
                profile="Disconnect",
                title="Family call",
                start=datetime(2026, 11, 2, 17, 0, tzinfo=plus_one),
                end=datetime(2026, 11, 2, 17, 25, tzinfo=plus_one),
                reason_codes=["gate.ok"],
            ),
        ],
    )

    CardLedger(db).save_card(offset_card)
    loaded = load_card(offset_card.card_id, db_path=db)
    assert loaded is not None
    assert loaded.card_id == offset_card.card_id
    assert loaded is not None
    assert loaded.since_line is None
    assert loaded.proposals[1].reason_codes == ("gate.ok",)
    assert load_card("card-" + "f" * 16, db_path=db) is None


def test_handler_error_answers_and_advances(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(220, "q1", f"{sent.card_id}:A"))

    def boom(events: Any) -> Any:
        raise RuntimeError("synthetic ruling failure")

    monkeypatch.setattr(service, "first_rulings", boom)
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.handler_errors == 1
    assert bodies_for(fake, "answerCallbackQuery")[0]["text"] == (
        "Could not handle that tap."
    )
    assert cursor(db) == {"foreign_total": 0, "offset": 221}


def test_answered_on_every_path(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    unknown = "card-" + "2" * 16
    fake.queue(fake.callback_update(230, "q1", f"{unknown}:why"))
    fake.queue(fake.callback_update(231, "q2", "bogus"))
    fake.queue(fake.callback_update(232, "q3", f"{sent.card_id}:A"))
    fake.expired_queries.add("q3")
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1), T0 + timedelta(seconds=2)]),
    )
    assert stats.answer_errors == 1
    assert stats.stored == 2
    answered_ids = {
        a["callback_query_id"] for a in bodies_for(fake, "answerCallbackQuery")
    }
    assert answered_ids == {"q1", "q2", "q3"}
    edits = bodies_for(fake, "editMessageReplyMarkup")
    assert edits, "the ruling edit still runs after a stale answer"


def test_send_failure_keeps_ledger_card(harness: Harness) -> None:
    fake, _client, db = harness
    card = make_card()
    quiet = TelegramClient(sleep_fn=lambda _s: None)
    fake.queue_script("sendPhoto", ("500",))
    with pytest.raises(TelegramDeliveryUnknown):
        send_card(card, chart_data(), db_path=db, client=quiet)
    assert load_card(card.card_id, db_path=db) is not None
    assert len([r for r in fake.requests if r[0] == "sendPhoto"]) == 1


def test_answered_on_side_effect_timeout_and_answer_retry(
    harness: Harness,
) -> None:
    fake, _client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(233, "q1", f"{sent.card_id}:why"))
    fake.queue(fake.callback_update(234, "q2", f"{sent.card_id}:A"))
    fake.queue_script("answerCallbackQuery", "timeout-urlopen", "timeout-urlopen")

    quiet = TelegramClient(sleep_fn=lambda _s: None)
    stats = poll_once(
        db_path=db, client=quiet, now_fn=Clock([T0, T0 + timedelta(seconds=1)])
    )
    assert stats.side_effect_errors == 1
    assert stats.stored == 2
    assert stats.answered == 1
    for name, _, _, body, timeout in fake.requests:
        if name in ("answerCallbackQuery", "editMessageReplyMarkup", "sendMessage"):
            assert timeout == 10
    q1_answers = [
        json.loads(body.decode())
        for name, _, _, body, _ in fake.requests
        if name == "answerCallbackQuery"
        and json.loads(body.decode()).get("callback_query_id") == "q1"
    ]
    assert len(q1_answers) == 2
    assert cursor(db) == {"foreign_total": 0, "offset": 235}


def test_handler_error_with_failing_cursor_write_stops_batch(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:

    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(236, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(237, "q2", f"{sent.card_id}:B"))

    def boom(events: Any) -> Any:
        raise RuntimeError("synthetic ruling failure")

    def boom_cursor(self: EventStore, *args: Any, **kwargs: Any) -> Any:
        raise sqlite3.Error("synthetic cursor failure")

    monkeypatch.setattr(service, "first_rulings", boom)
    monkeypatch.setattr(EventStore, "poll_transaction", boom_cursor)
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.handler_errors == 1
    assert stats.store_errors == 1
    assert stats.updates == 1
    answers = bodies_for(fake, "answerCallbackQuery")
    assert [a["callback_query_id"] for a in answers] == ["q1"]
    assert cursor(db) is None


# -- AT12: sample and late taps --------------------------------------------


def test_sample_send_and_tap_store_nothing(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_card(SAMPLE_CARD, SAMPLE_CHART, db_path=db, client=client)
    assert sent.card_id == SAMPLE_CARD.card_id
    assert [side.kind for side in SAMPLE_CARD.proposals] == [
        "proposal",
        "proposal",
    ]
    assert ledger_rows(db) == 0
    assert render_chart_png(SAMPLE_CHART)[:8] == b"\x89PNG\r\n\x1a\n"
    fake.queue(fake.callback_update(240, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(241, "q2", f"{sent.card_id}:why"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.sample == 2
    assert tap_events(db) == []
    assert ledger_rows(db) == 0
    answers = bodies_for(fake, "answerCallbackQuery")
    assert [a["text"] for a in answers] == [
        "Sample card. Nothing stored.",
        "Sample card. Nothing stored.",
    ]
    assert bodies_for(fake, "editMessageReplyMarkup"), "sample tap edits"
    assert bodies_for(fake, "sendMessage"), "sample why replies"


def test_sample_card_and_chart_keep_synthetic_labels() -> None:
    assert "sample card, synthetic values" in render_card_text(SAMPLE_CARD)
    assert SAMPLE_CARD.statements == ("Sample statement, synthetic values.",)
    assert SAMPLE_CHART.period_labels == ("earlier", "prior", "last")
    assert [item.label for item in SAMPLE_CHART.screen] == [
        "code",
        "comms",
        "feed",
    ]
    assert SAMPLE_CHART.pushes is not None
    assert SAMPLE_CHART.pushes.label == "pushes"
    assert [item.label for item in SAMPLE_CHART.tally] == [
        "Builder",
        "Disconnect",
        "Neither",
    ]


def test_late_tap_on_old_card_stores_against_that_card(
    harness: Harness,
) -> None:
    fake, client, db = harness
    older = make_card(
        proposals=[proposal("B", "proposal", profile="Disconnect", title="Family call")]
    )
    older_sent = send_card(older, chart_data(), db_path=db, client=client)
    newer_sent = send_two_sided(harness)
    assert newer_sent.card_id != older_sent.card_id
    fake.queue(fake.callback_update(250, "q1", f"{older_sent.card_id}:B"))
    stats = poll_once(db_path=db, client=client, now_fn=Clock([T0]))
    assert stats.stored == 1
    assert first_rulings(tap_events(db)) == {older_sent.card_id: "B"}
    events = tap_events(db)
    assert [event.source_id for event in events] == [f"{older_sent.card_id}:B"]
    edits = bodies_for(fake, "editMessageReplyMarkup")
    assert edits, "the late tap edits the old card keyboard"
    assert edits[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == (
        f"{older_sent.card_id}:B"
    )


# -- loop progress, store trouble, cursor safety ----------------------------


def test_offset_never_regresses_within_batch(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(105, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(102, "q2", f"{sent.card_id}:B"))
    stats = poll_once(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
    )
    assert stats.stored == 2
    assert cursor(db) == {"foreign_total": 0, "offset": 106}


def test_malformed_offset_cursor_raises_config_error(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    store = EventStore(db)
    try:
        store.poll_transaction("telegram", [], {"offset": "bad", "foreign_total": 0})
    finally:
        store.close()
    base = len(fake.requests)
    with pytest.raises(TelegramConfigError, match="telegram cursor is malformed"):
        poll_once(db_path=db, client=client)
    with pytest.raises(TelegramConfigError, match="telegram cursor is malformed"):
        run_poll_loop(db_path=db, client=client, stop=bounded(lambda: False))
    assert len(fake.requests) == base


def test_malformed_cursor_shapes_raise_config_error(harness: Harness) -> None:
    fake, client, db = harness
    send_two_sided(harness)
    for bad in (5, [1, 2], {"offset": 3}):
        store = EventStore(db)
        try:
            store.poll_transaction("telegram", [], bad)
        finally:
            store.close()
        base = len(fake.requests)
        with pytest.raises(TelegramConfigError, match="telegram cursor is malformed"):
            poll_once(db_path=db, client=client)
        with pytest.raises(TelegramConfigError, match="telegram cursor is malformed"):
            run_poll_loop(db_path=db, client=client, stop=bounded(lambda: False))
        assert len(fake.requests) == base


def test_no_progress_backoff_sleeps_and_grows(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue("not-a-dict")  # type: ignore[arg-type]
    sleeps: list[float] = []
    seen: list[Any] = []
    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(seen) >= 2),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert total.malformed == 2
    assert sleeps == [1, 2]


def test_store_failure_in_loop_sleeps_refetches_and_stores(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:

    fake, _client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(210, "q1", f"{sent.card_id}:A"))
    real_store = service.EventStore
    opens = {"count": 0}

    def flaky_store(db_path: Path | None = None) -> EventStore:
        opens["count"] += 1
        if opens["count"] == 1:
            raise sqlite3.Error("synthetic open failure")
        return real_store(db_path)

    monkeypatch.setattr(service, "EventStore", flaky_store)
    original = EventStore.append_event
    appends = {"count": 0}

    def flaky_append(self: EventStore, event: Any) -> bool:
        appends["count"] += 1
        if appends["count"] == 1:
            raise sqlite3.Error("synthetic disk failure")
        return original(self, event)

    monkeypatch.setattr(EventStore, "append_event", flaky_append)
    quiet = TelegramClient(sleep_fn=lambda _s: None)
    sleeps: list[float] = []
    seen: list[Any] = []
    total = run_poll_loop(
        db_path=db,
        client=quiet,
        now_fn=Clock([T0, T0 + timedelta(seconds=1)]),
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(seen) >= 3),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert total.store_errors == 2
    assert sleeps == [1, 2]
    assert [s.store_errors for s in seen] == [1, 2, 2]
    assert len(tap_events(db)) == 1
    assert cursor(db) == {"foreign_total": 0, "offset": 211}


def test_store_failure_after_progress_still_backs_off(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(210, "q1", f"{sent.card_id}:A"))
    fake.queue(fake.callback_update(211, "q2", f"{sent.card_id}:neither"))
    original = EventStore.append_event
    calls = {"count": 0}

    def flaky(self: EventStore, event: Any) -> bool:
        calls["count"] += 1
        if calls["count"] == 2:
            raise sqlite3.Error("synthetic disk failure")
        return original(self, event)

    monkeypatch.setattr(EventStore, "append_event", flaky)
    sleeps: list[float] = []
    seen: list[Any] = []
    total = run_poll_loop(
        db_path=db,
        client=client,
        now_fn=Clock([T0, T0 + timedelta(seconds=1), T0 + timedelta(seconds=2)]),
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(seen) >= 2),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert sleeps == [1]
    assert total.store_errors == 1
    assert total.stored == 2
    events = tap_events(db)
    assert [e.source_id for e in events] == [
        f"{sent.card_id}:A",
        f"{sent.card_id}:neither",
    ]
    assert cursor(db) == {"foreign_total": 0, "offset": 212}


def test_html_502_backoff_counts_poll_errors(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", "html-502", "html-502")
    sleeps: list[float] = []
    seen: list[Any] = []
    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(fake.requests) >= 2),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert total.poll_errors == 2
    assert [s.poll_errors for s in seen] == [1, 2]
    assert sleeps == [1, 2]


def test_conflict_backoff_reports_on_batch_and_continues(
    harness: Harness,
) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("409",), ("409",))
    sleeps: list[float] = []
    seen: list[Any] = []
    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(fake.requests) >= 2),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert total.conflicts == 2
    assert [s.conflicts for s in seen] == [1, 2]
    assert sleeps == [1, 2]


# -- AT14: loop backoff, rate limit, conflict, auth --------------------------


def run_until(
    fake: FakeTelegram,
    client: TelegramClient,
    db: Path,
    calls: int,
) -> tuple[Any, list[float]]:
    sleeps: list[float] = []
    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(lambda: len(fake.requests) >= calls),
    )
    return total, sleeps


def test_rate_limit_loop_sleeps_exactly_and_continues(
    harness: Harness,
) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("429", 7))
    total, sleeps = run_until(fake, client, db, 2)
    assert total.rate_limited == 1
    assert sleeps == [7]


def test_rate_limit_loop_reports_before_each_sleep(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("429", 7), ("429", 7))
    events: list[tuple[str, float]] = []
    seen: list[int] = []

    def on_batch(stats: Any) -> None:
        seen.append(stats.rate_limited)
        events.append(("batch", float(stats.rate_limited)))

    def sleep_fn(slept: float) -> None:
        events.append(("sleep", slept))

    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleep_fn,
        stop=bounded(lambda: len(fake.requests) >= 3),
        on_batch=on_batch,
    )
    assert total.rate_limited == 2
    assert seen == [1, 2]
    assert events == [
        ("batch", 1.0),
        ("sleep", 7.0),
        ("batch", 2.0),
        ("sleep", 7.0),
    ]


def test_rate_limit_zero_retry_after_backs_off_in_loop(
    harness: Harness,
) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("429", 0), ("429", 0))
    total, sleeps = run_until(fake, client, db, 3)
    assert total.rate_limited == 2
    assert sleeps == [1, 2]


def test_on_batch_that_raises_leaves_the_loop(harness: Harness) -> None:
    fake, client, db = harness
    sent = send_two_sided(harness)
    fake.queue(fake.callback_update(320, "q1", f"{sent.card_id}:A"))

    def on_batch(stats: Any) -> None:
        raise RuntimeError("synthetic")

    with pytest.raises(RuntimeError, match="synthetic"):
        run_poll_loop(
            db_path=db,
            client=client,
            now_fn=Clock([T0]),
            stop=bounded(lambda: False),
            on_batch=on_batch,
        )


def test_conflict_loop_counts_backs_off_and_continues(
    harness: Harness,
) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("409",))
    total, sleeps = run_until(fake, client, db, 2)
    assert total.conflicts == 1
    assert sleeps == [1]


def test_backoff_loop_grows_and_resets(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("500",), ("500",))
    sleeps: list[float] = []
    seen: list[Any] = []

    def stop_after_fourth() -> bool:
        if len(fake.requests) == 3:
            # The third getUpdates is an empty success that resets the
            # backoff; arm one more failure after it.
            fake.queue_script("getUpdates", ("500",))
        return len(fake.requests) >= 4

    total = run_poll_loop(
        db_path=db,
        client=client,
        sleep_fn=sleeps.append,  # type: ignore[arg-type]
        stop=bounded(stop_after_fourth),
        on_batch=seen.append,  # type: ignore[arg-type]
    )
    assert sleeps == [1, 2, 1]
    assert total.updates == 0
    assert total.poll_errors == 3


def test_backoff_loop_caps_at_sixty(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue_script(
        "getUpdates",
        ("500",),
        ("500",),
        ("500",),
        ("500",),
        ("500",),
        ("500",),
        ("500",),
        ("500",),
        ("500",),
    )
    total, sleeps = run_until(fake, client, db, 10)
    assert sleeps == [1, 2, 4, 8, 16, 32, 60, 60, 60]
    assert total.poll_errors == 9
    assert total.updates == 0


def test_auth_error_stops_loop_and_propagates(harness: Harness) -> None:
    fake, client, db = harness
    fake.queue_script("getUpdates", ("401",))
    with pytest.raises(TelegramAuthError):
        run_until(fake, client, db, 1)


def test_poll_once_propagates_conflict(harness: Harness) -> None:
    _, client, db = harness
    harness[0].queue_script("getUpdates", ("409",))
    with pytest.raises(TelegramConflict):
        poll_once(db_path=db, client=client)


def test_send_card_uses_sixty_second_timeout(harness: Harness) -> None:
    fake, _client, db = harness
    sent = send_card(make_card(), chart_data(), db_path=db)
    assert sent.message_id >= 1001
    photo_calls = [r for r in fake.requests if r[0] == "sendPhoto"]
    assert len(photo_calls) == 1
    assert photo_calls[0][4] == 60.0


def test_send_card_without_message_id_is_delivery_unknown(
    harness: Harness,
) -> None:
    fake, _client, db = harness
    card = make_card()
    quiet = TelegramClient(sleep_fn=lambda _s: None)
    fake.queue_script("sendPhoto", "ok-no-message-id")
    with pytest.raises(TelegramDeliveryUnknown):
        send_card(card, chart_data(), db_path=db, client=quiet)
    assert load_card(card.card_id, db_path=db) is not None
    assert len([r for r in fake.requests if r[0] == "sendPhoto"]) == 1
