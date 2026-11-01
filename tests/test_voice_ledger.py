"""Ticket 14 Step 5: the voice ledger on the shared voice_notes table (D3, D5).

Inserts go through CardLedger.record_voice_note; claims, retries and reads go
through VoiceLedger. Synthetic rows only, one tmp database per test.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from framework.telegram.ledger import CardLedger
from framework.telegram.models import VoiceNote
from framework.voice.ledger import VoiceLedger, VoiceRow, retry_delay_s

UTC_PLUS_ONE = "+01:00"


def _instant(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(
        f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00{UTC_PLUS_ONE}"
    )


def _note(message_id: int, **kwargs: Any) -> VoiceNote:
    args: dict[str, Any] = {
        "message_id": message_id,
        "date": 1761924000 + message_id,
        "file_id": f"file-{message_id}",
        "file_unique_id": f"uniq-{message_id}",
        "duration_s": 4,
    }
    args.update(kwargs)
    return VoiceNote(**args)  # type: ignore[arg-type]


def _ledgers(tmp_path: Path) -> tuple[CardLedger, VoiceLedger]:
    db_path = tmp_path / "voice.db"
    return CardLedger(db_path), VoiceLedger(db_path)


def _store(cards: CardLedger, message_id: int, received: datetime) -> bool:
    return cards.record_voice_note(
        _note(message_id), 1000 + message_id, received.isoformat()
    )


def test_row_round_trip(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    received = _instant(31, 9)
    assert _store(cards, 11, received) is True

    row = voice.load(11)
    assert isinstance(row, VoiceRow)
    assert row.message_id == 11
    assert row.update_id == 1011
    assert row.file_id == "file-11"
    assert row.file_unique_id == "uniq-11"
    assert row.duration_s == 4
    assert row.received_at == received.isoformat()
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.next_attempt_at is None
    assert row.waiting_told == 0
    assert row.first_claimed_at is None
    assert row.transcript is None
    assert row.outcome is None


def test_redelivery_adds_no_row(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    received = _instant(31, 9)
    assert _store(cards, 11, received) is True
    assert _store(cards, 11, received) is False
    assert voice.load(11) is not None


def test_claim_takes_oldest_due_first(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 3, _instant(31, 9, 30))
    _store(cards, 1, _instant(31, 9, 5))
    _store(cards, 2, _instant(31, 9, 10))
    now = _instant(31, 10)

    first = voice.claim_next(now)
    second = voice.claim_next(now)
    third = voice.claim_next(now)
    assert first is not None and first.message_id == 1
    assert second is not None and second.message_id == 2
    assert third is not None and third.message_id == 3
    assert voice.claim_next(now) is None
    assert first.status == "working"
    assert first.first_claimed_at == now.isoformat()


def test_waiting_row_does_not_hold_back_rows_behind(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    _store(cards, 2, _instant(31, 9, 10))
    now = _instant(31, 10)
    voice.update(1, next_attempt_at=(now + timedelta(hours=2)).isoformat())

    claimed = voice.claim_next(now)
    assert claimed is not None and claimed.message_id == 2
    assert voice.load(1) is not None
    assert voice.load(1).status == "pending"  # type: ignore[union-attr]


def test_due_row_claims_when_wait_expired(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    voice.update(1, next_attempt_at=_instant(31, 9, 50).isoformat())
    claimed = voice.claim_next(_instant(31, 10))
    assert claimed is not None and claimed.message_id == 1


def test_first_claimed_at_stamped_once(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    first_claim = voice.claim_next(_instant(31, 10))
    assert first_claim is not None
    assert first_claim.first_claimed_at == _instant(31, 10).isoformat()

    assert voice.requeue_working() == 1
    second_claim = voice.claim_next(_instant(31, 11))
    assert second_claim is not None
    assert second_claim.first_claimed_at == _instant(31, 10).isoformat()


def test_requeue_working_only_touches_working(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    _store(cards, 2, _instant(31, 9, 6))
    now = _instant(31, 10)
    voice.claim_next(now)
    assert voice.requeue_working() == 1
    assert voice.requeue_working() == 0
    row = voice.load(1)
    assert row is not None and row.status == "pending"
    other = voice.load(2)
    assert other is not None and other.status == "pending"


def test_update_accepts_the_closed_field_set(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    voice.update(
        1,
        status="working",
        attempts=2,
        next_attempt_at=_instant(31, 10).isoformat(),
        waiting_told=1,
        first_claimed_at=_instant(31, 9, 40).isoformat(),
        applied_at=_instant(31, 9, 41).isoformat(),
        slot=_instant(31, 15, 7).isoformat(),
        matched_card_id="card-1",
        transcript="skip the write-up",
        operation="skip",
        commitment_id="write-up",
        until_value="today",
        question=None,
        validation_codes='["X"]',
        new_card_id="card-2",
        outcome="applied_card",
        step_seconds='{"transcribe": 1.5}',
        total_s=3.25,
        unaccounted_s=0.5,
        arrival_lag_s=0.1,
        compile_model="muse-spark-1.3",
        compile_effort="minimal",
        prompt_tokens=5,
        completion_tokens=7,
        muse_version="1.4.14",
        rules_file_present=0,
    )
    row = voice.load(1)
    assert row is not None
    assert row.status == "working"
    assert row.attempts == 2
    assert row.matched_card_id == "card-1"
    assert row.transcript == "skip the write-up"
    assert row.operation == "skip"
    assert row.new_card_id == "card-2"
    assert row.outcome == "applied_card"
    assert row.total_s == 3.25
    assert row.compile_model == "muse-spark-1.3"


def test_update_rejects_unknown_fields(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    with pytest.raises(ValueError, match="unknown voice field"):
        voice.update(1, no_such_column="x")  # type: ignore[call-arg]
    # The primary key is not part of the updatable set: Python itself
    # rejects it as a duplicate argument before the closed-set check runs.
    with pytest.raises(TypeError):
        voice.update(1, message_id=2)  # type: ignore[call-arg]


def test_update_serialises_structured_fields(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    voice.update(
        1,
        step_seconds={"transcribe": 1.5, "compile": 2.0},
        validation_codes=("CORRECTION_UNKNOWN_COMMITMENT",),
    )
    row = voice.load(1)
    assert row is not None
    assert row.step_seconds == '{"transcribe": 1.5, "compile": 2.0}'
    assert row.validation_codes == '["CORRECTION_UNKNOWN_COMMITMENT"]'


def test_rows_for_card_reads_both_sides_of_the_chain(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    _store(cards, 1, _instant(31, 9, 5))
    _store(cards, 2, _instant(31, 9, 6))
    _store(cards, 3, _instant(31, 9, 7))
    voice.update(1, matched_card_id="card-1", new_card_id="card-2")
    voice.update(2, matched_card_id="card-2", new_card_id="card-3")

    assert [row.message_id for row in voice.rows_for_card("card-2")] == [1, 2]
    assert [row.message_id for row in voice.rows_for_card("card-1")] == [1]
    assert [row.message_id for row in voice.rows_for_card("card-3")] == [2]
    assert voice.rows_for_card("card-9") == ()


def test_corrected_count_for_slot_counts_only_sent_cards(tmp_path: Path) -> None:
    cards, voice = _ledgers(tmp_path)
    slot = _instant(31, 15, 7)
    _store(cards, 1, _instant(31, 9, 5))
    _store(cards, 2, _instant(31, 9, 6))
    _store(cards, 3, _instant(31, 9, 7))
    voice.update(1, slot=slot.isoformat(), new_card_id="card-2")
    voice.update(2, slot=slot.isoformat())
    voice.update(3, slot=_instant(31, 19, 7).isoformat(), new_card_id="card-4")

    assert voice.corrected_count_for_slot(slot) == 1
    assert voice.corrected_count_for_slot(_instant(31, 19, 7)) == 1
    assert voice.corrected_count_for_slot(_instant(31, 21, 7)) == 0


@pytest.mark.parametrize(
    ("attempts", "expected"),
    [(0, 5), (1, 5), (2, 30), (3, 120), (4, 900), (10, 900)],
)
def test_retry_waits_back_off(attempts: int, expected: int) -> None:
    assert retry_delay_s(attempts) == expected


def test_load_missing_returns_none(tmp_path: Path) -> None:
    _, voice = _ledgers(tmp_path)
    assert voice.load(999) is None


def _create_voice_notes_without_disputed_claims(db_path: Path) -> None:
    """Mimic a database file from before the disputed_claims column existed."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE voice_notes (
                message_id INTEGER PRIMARY KEY,
                update_id INTEGER,
                telegram_date INTEGER,
                file_id TEXT,
                file_unique_id TEXT,
                duration_s INTEGER,
                mime_type TEXT,
                file_size INTEGER,
                reply_to_message_id INTEGER,
                received_at TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                waiting_told INTEGER NOT NULL DEFAULT 0,
                first_claimed_at TEXT,
                applied_at TEXT,
                slot TEXT,
                matched_card_id TEXT,
                transcript TEXT,
                operation TEXT,
                commitment_id TEXT,
                until_value TEXT,
                question TEXT,
                validation_codes TEXT,
                new_card_id TEXT,
                outcome TEXT,
                step_seconds TEXT,
                total_s REAL,
                unaccounted_s REAL,
                arrival_lag_s REAL,
                compile_model TEXT,
                compile_effort TEXT,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                muse_version TEXT,
                rules_file_present INTEGER
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_ensure_voice_columns_backfills_disputed_claims(tmp_path: Path) -> None:
    """A file without disputed_claims gains the column on first use."""
    db_path = tmp_path / "old-voice.db"
    _create_voice_notes_without_disputed_claims(db_path)
    cards, voice = _ledgers(tmp_path)
    cards.db_path = db_path
    voice.db_path = db_path
    assert voice.load(7) is None
    assert _store(cards, 7, _instant(31, 9, 5)) is True
    voice.update(7, disputed_claims=3)
    row = voice.load(7)
    assert row is not None and row.disputed_claims == 3


def test_card_ledger_first_use_backfills_disputed_claims(tmp_path: Path) -> None:
    """The card ledger's first use also backfills the missing column."""
    db_path = tmp_path / "old-voice-cards.db"
    _create_voice_notes_without_disputed_claims(db_path)
    cards, voice = _ledgers(tmp_path)
    cards.db_path = db_path
    voice.db_path = db_path
    assert _store(cards, 9, _instant(31, 9, 5)) is True
    voice.update(9, disputed_claims=1)
    row = voice.load(9)
    assert row is not None and row.disputed_claims == 1
