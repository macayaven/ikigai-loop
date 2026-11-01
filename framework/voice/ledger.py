"""Ticket 14: the voice ledger on the shared ``voice_notes`` table.

The DDL lives in ``framework.telegram.ledger`` and is imported here, so the
queue has one home no matter which side writes it. Like ``CardLedger``, the
ledger opens one connection per operation on the resolved store file. Claim
is one ``BEGIN IMMEDIATE`` step from ``pending`` to ``working`` that stamps
``first_claimed_at`` once; a row waiting on ``next_attempt_at`` never holds
back the rows behind it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.store.store import resolve_db_path
from framework.telegram.ledger import VOICE_NOTES_DDL, ensure_voice_columns

_COLUMNS: tuple[str, ...] = (
    "message_id",
    "update_id",
    "telegram_date",
    "file_id",
    "file_unique_id",
    "duration_s",
    "mime_type",
    "file_size",
    "reply_to_message_id",
    "received_at",
    "status",
    "attempts",
    "next_attempt_at",
    "waiting_told",
    "first_claimed_at",
    "applied_at",
    "slot",
    "matched_card_id",
    "transcript",
    "operation",
    "commitment_id",
    "until_value",
    "question",
    "validation_codes",
    "disputed_claims",
    "new_card_id",
    "outcome",
    "step_seconds",
    "total_s",
    "unaccounted_s",
    "arrival_lag_s",
    "compile_model",
    "compile_effort",
    "prompt_tokens",
    "completion_tokens",
    "muse_version",
    "rules_file_present",
)

_UPDATABLE: frozenset[str] = frozenset(
    column for column in _COLUMNS if column != "message_id"
)

_JSON_FIELDS: frozenset[str] = frozenset({"step_seconds", "validation_codes"})


def retry_delay_s(attempts: int) -> int:
    """Transient wait after ``attempts`` failures: +5 s, +30 s, +120 s, then +900 s."""
    if attempts <= 1:
        return 5
    if attempts == 2:
        return 30
    if attempts == 3:
        return 120
    return 900


@dataclass(frozen=True)
class VoiceRow:
    """One voice note row, mirroring the shared table's columns."""

    message_id: int
    update_id: int | None = None
    telegram_date: int | None = None
    file_id: str | None = None
    file_unique_id: str | None = None
    duration_s: int | None = None
    mime_type: str | None = None
    file_size: int | None = None
    reply_to_message_id: int | None = None
    received_at: str | None = None
    status: str = "pending"
    attempts: int = 0
    next_attempt_at: str | None = None
    waiting_told: int = 0
    first_claimed_at: str | None = None
    applied_at: str | None = None
    slot: str | None = None
    matched_card_id: str | None = None
    transcript: str | None = None
    operation: str | None = None
    commitment_id: str | None = None
    until_value: str | None = None
    question: str | None = None
    validation_codes: str | None = None
    disputed_claims: int | None = None
    new_card_id: str | None = None
    outcome: str | None = None
    step_seconds: str | None = None
    total_s: float | None = None
    unaccounted_s: float | None = None
    arrival_lag_s: float | None = None
    compile_model: str | None = None
    compile_effort: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    muse_version: str | None = None
    rules_file_present: int | None = None


def _row_from(values: tuple[Any, ...]) -> VoiceRow:
    return VoiceRow(**dict(zip(_COLUMNS, values, strict=True)))


class VoiceLedger:
    """Own connection per operation on the store file; never overwrites rows."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = resolve_db_path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(VOICE_NOTES_DDL)
        ensure_voice_columns(conn)
        return conn

    def load(self, message_id: int) -> VoiceRow | None:
        """Return one row by Telegram message id, or None when unknown."""
        conn = self._connect()
        try:
            found = conn.execute(
                "SELECT "
                + ", ".join(_COLUMNS)
                + " FROM voice_notes WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        finally:
            conn.close()
        if found is None:
            return None
        return _row_from(tuple(found))

    def claim_next(self, now: datetime) -> VoiceRow | None:
        """Claim the oldest due ``pending`` row, waiting rows excluded.

        One ``BEGIN IMMEDIATE`` step flips the row to ``working`` and stamps
        ``first_claimed_at`` only on the first claim. A row whose
        ``next_attempt_at`` lies ahead does not hold back the rows behind it.
        """
        moment = now.isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            found = conn.execute(
                "SELECT message_id FROM voice_notes"
                " WHERE status = 'pending'"
                " AND (next_attempt_at IS NULL OR next_attempt_at <= ?)"
                " ORDER BY received_at ASC, message_id ASC LIMIT 1",
                (moment,),
            ).fetchone()
            if found is None:
                conn.execute("ROLLBACK")
                return None
            message_id = int(found[0])
            changed = conn.execute(
                "UPDATE voice_notes SET status = 'working',"
                " first_claimed_at = COALESCE(first_claimed_at, ?)"
                " WHERE message_id = ? AND status = 'pending'",
                (moment, message_id),
            )
            if changed.rowcount != 1:
                conn.execute("ROLLBACK")
                return None
            conn.commit()
        finally:
            conn.close()
        return self.load(message_id)

    def requeue_working(self) -> int:
        """Move every ``working`` row back to ``pending``; returns the count."""
        conn = self._connect()
        try:
            changed = conn.execute(
                "UPDATE voice_notes SET status = 'pending' WHERE status = 'working'"
            )
            conn.commit()
            return int(changed.rowcount)
        finally:
            conn.close()

    def update(self, message_id: int, **fields: Any) -> None:
        """Write the closed field set on one row; unknown fields are refused."""
        for key in fields:
            if key not in _UPDATABLE:
                raise ValueError(f"unknown voice field: {key}")
        if not fields:
            return
        assignments: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in _JSON_FIELDS and value is not None and not isinstance(value, str):
                value = json.dumps(value)
            assignments.append(f"{key} = ?")
            values.append(value)
        values.append(message_id)
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE voice_notes SET "
                + ", ".join(assignments)
                + " WHERE message_id = ?",
                tuple(values),
            )
            conn.commit()
        finally:
            conn.close()

    def rows_for_card(self, card_id: str) -> tuple[VoiceRow, ...]:
        """Every row matched to the card or producing it, oldest first."""
        conn = self._connect()
        try:
            found = conn.execute(
                "SELECT " + ", ".join(_COLUMNS) + " FROM voice_notes"
                " WHERE matched_card_id = ? OR new_card_id = ?"
                " ORDER BY message_id ASC",
                (card_id, card_id),
            ).fetchall()
        finally:
            conn.close()
        return tuple(_row_from(tuple(values)) for values in found)

    def corrected_count_for_slot(self, slot: datetime | str) -> int:
        """How many corrected cards a slot already sent (rows with a new card)."""
        stamp = slot.isoformat() if isinstance(slot, datetime) else slot
        conn = self._connect()
        try:
            found = conn.execute(
                "SELECT COUNT(*) FROM voice_notes"
                " WHERE slot = ? AND new_card_id IS NOT NULL",
                (stamp,),
            ).fetchone()
        finally:
            conn.close()
        return int(found[0]) if found is not None else 0
