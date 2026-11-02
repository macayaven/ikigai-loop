"""Ticket 20b: one closed voice-note entry per slot on the export.

Made-up rows only. Each test fails on the pre-ticket tree because the
voice_notes field does not exist there yet.
"""

import json
import sqlite3
from pathlib import Path

from framework.provenance.export import main
from framework.provenance.schemas import ProvenanceLine

SLOT_LOCAL = "2026-11-02T15:30:00+01:00"
SLOT_UTC = "2026-11-02T14:30:00+00:00"
CARD = "syn-voice-card-9"

VOICE_COLUMNS = (
    "message_id, update_id, telegram_date, file_id, file_unique_id,"
    " duration_s, mime_type, file_size, reply_to_message_id, received_at,"
    " status, attempts, next_attempt_at, waiting_told, first_claimed_at,"
    " applied_at, slot, matched_card_id, transcript, operation,"
    " commitment_id, until_value, question, validation_codes,"
    " disputed_claims, new_card_id, outcome, step_seconds, total_s,"
    " unaccounted_s, arrival_lag_s, compile_model, compile_effort,"
    " prompt_tokens, completion_tokens, muse_version, rules_file_present"
)


def _base(db: Path, with_voice=True):
    """Real DDL on a temp path, plus one delivered slot with a side."""
    from framework.cycle.slot_ledger import DDL as SLOT_DDL
    from framework.telegram.ledger import LEDGER_DDL, VOICE_NOTES_DDL

    conn = sqlite3.connect(db)
    try:
        conn.executescript(SLOT_DDL)
        conn.executescript(LEDGER_DDL)
        if with_voice:
            conn.executescript(VOICE_NOTES_DDL)
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'start', 'ok', 0.1, NULL, '')",
            (SLOT_UTC,),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'card', 'ok', 0.2, ?, '')",
            (SLOT_UTC, CARD),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'send', 'delivered', 0.3, ?, '')",
            (SLOT_UTC, CARD),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'done', 'delivered', 0.4, ?, '')",
            (SLOT_UTC, CARD),
        )
        conn.execute(
            "INSERT INTO slot_cards (card_id, letter, slot, subject_id,"
            " as_of, bucket, profile_id, commitment_id, kind, policy_pick,"
            " policy_alternative) VALUES (?, 'A', ?, 'subject-a', ?, NULL,"
            " 'builder', 'c-1', 'proposal', NULL, NULL)",
            (CARD, SLOT_UTC, SLOT_UTC),
        )
        conn.commit()
    finally:
        conn.close()


def _voice(
    db: Path,
    message_id,
    status,
    operation,
    new_card_id,
    total_s,
    slot=SLOT_UTC,
    extra="",
):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            f"INSERT INTO voice_notes ({VOICE_COLUMNS}) VALUES (?, NULL, NULL,"
            " NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, 0, NULL, 0, NULL,"
            " NULL, ?, NULL, ?, ?, NULL, NULL, ?, NULL, NULL, ?, NULL, NULL,"
            " ?, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
            (
                message_id,
                status,
                slot,
                extra or None,
                operation,
                extra or None,
                new_card_id,
                total_s,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _line(db: Path, capsys):
    code = main(["--db", str(db)])
    out = capsys.readouterr()
    assert code == 0, out.err
    rows = [json.loads(line) for line in out.out.splitlines() if line.strip()]
    assert len(rows) == 1
    return rows[0], out.out


def test_closed_entries_in_message_order(tmp_path, capsys):
    """Two closed notes read as entries in message order.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "voice.db"
    _base(db)
    _voice(db, 9, "done", "done", CARD, 1.5)
    _voice(db, 3, "gave_up", "none", None, 0.25)
    row, _ = _line(db, capsys)
    assert row["voice_notes"] == [
        {"operation": "asked", "new_card_sent": False, "latency_ms": 250},
        {"operation": "done", "new_card_sent": True, "latency_ms": 1500},
    ]
    assert list(row.keys())[-1] == "voice_notes"


def test_open_rows_are_left_out(tmp_path, capsys):
    """Pending and working rows wait until they close.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "open.db"
    _base(db)
    _voice(db, 1, "pending", "done", CARD, 1.0)
    _voice(db, 2, "working", "skip", None, 2.0)
    _voice(db, 3, "done", "keep", None, 3.0)
    row, _ = _line(db, capsys)
    assert row["voice_notes"] == [
        {"operation": "keep", "new_card_sent": False, "latency_ms": 3000}
    ]


def test_missing_table_reads_unknown(tmp_path, capsys):
    """No voice_notes table means unknown on every line, never empty.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "notable.db"
    _base(db, with_voice=False)
    row, _ = _line(db, capsys)
    assert row["voice_notes"] == "unknown"


def test_missing_column_reads_unknown(tmp_path, capsys):
    """A voice_notes table without total_s means unknown on every line.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "nocol.db"
    _base(db, with_voice=False)
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "CREATE TABLE voice_notes (message_id INTEGER PRIMARY KEY,"
            " slot TEXT, status TEXT, operation TEXT, new_card_id TEXT)"
        )
        conn.execute(
            "INSERT INTO voice_notes VALUES (1, ?, 'done', 'done', ?)",
            (SLOT_UTC, CARD),
        )
        conn.commit()
    finally:
        conn.close()
    row, _ = _line(db, capsys)
    assert row["voice_notes"] == "unknown"


def test_bad_operation_and_total_read_unknown(tmp_path, capsys):
    """Null or odd operations and bad times read as unknown, never zero.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "bad.db"
    _base(db)
    _voice(db, 1, "done", "skip", CARD, 2.0)
    _voice(db, 2, "done", None, CARD, None)
    _voice(db, 3, "gave_up", "shout", None, -2.0)
    _voice(db, 4, "done", "defer", None, float("inf"))
    _voice(db, 5, "done", "drop", None, float("nan"))
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            f"INSERT INTO voice_notes ({VOICE_COLUMNS}) VALUES (6, NULL,"
            " NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'done', 0,"
            " NULL, 0, NULL, NULL, ?, NULL, NULL, 'fact_correction', NULL,"
            " NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL, NULL, NULL,"
            " NULL, NULL, NULL, NULL, NULL)",
            (SLOT_UTC, "fast"),
        )
        conn.commit()
    finally:
        conn.close()
    row, _ = _line(db, capsys)
    assert row["voice_notes"] == [
        {"operation": "skip", "new_card_sent": True, "latency_ms": 2000},
        {"operation": "unknown", "new_card_sent": True, "latency_ms": "unknown"},
        {"operation": "unknown", "new_card_sent": False, "latency_ms": "unknown"},
        {"operation": "defer", "new_card_sent": False, "latency_ms": "unknown"},
        {"operation": "drop", "new_card_sent": False, "latency_ms": "unknown"},
        {
            "operation": "fact_correction",
            "new_card_sent": False,
            "latency_ms": "unknown",
        },
    ]


def test_old_line_without_field_validates():
    """A line from before this ticket validates and reads as unknown."""
    line = ProvenanceLine.model_validate(
        {
            "slot": SLOT_LOCAL,
            "delivery": "no_card",
            "final_code": "unknown",
            "facts_model_step": "unknown",
            "forced": "unknown",
            "superseded_cards": 0,
            "cycle_origin": "none",
            "facts_cited": {"code": 0, "model": 0, "unknown": 0},
            "not_on_card": [],
            "sides": [],
        }
    )
    assert line.voice_notes == "unknown"
    assert line.model_dump(mode="json")["voice_notes"] == "unknown"


def test_voice_text_never_leaves(tmp_path, capsys):
    """Transcript and question words never reach the log.

    Fails on the pre-ticket tree: the line has no voice_notes key.
    """
    db = tmp_path / "quiet.db"
    _base(db)
    canary = "syn-voice-quiet-q7"
    _voice(db, 1, "done", "done", CARD, 1.0, extra=canary)
    row, stdout = _line(db, capsys)
    assert row["voice_notes"] == [
        {"operation": "done", "new_card_sent": True, "latency_ms": 1000}
    ]
    assert canary not in stdout
    assert CARD not in stdout
