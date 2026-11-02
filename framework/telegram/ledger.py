"""Card ledger: card bodies, voice arrivals, and the voice queue."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from framework.store.store import resolve_db_path
from framework.telegram.models import Card, ChartData, VoiceNote

LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS telegram_cards (
    card_id TEXT PRIMARY KEY,
    card_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_voice_arrivals (
    message_id INTEGER PRIMARY KEY,
    received_at TEXT NOT NULL,
    duration_s INTEGER NOT NULL
);
"""

VOICE_NOTES_DDL = """
CREATE TABLE IF NOT EXISTS voice_notes (
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
    disputed_claims INTEGER,
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
);
CREATE TABLE IF NOT EXISTS telegram_card_messages (
    message_id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS telegram_card_charts (
    card_id TEXT PRIMARY KEY,
    chart_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_voice_columns(conn: sqlite3.Connection) -> None:
    """Add newer ``voice_notes`` columns to a file created before them."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(voice_notes)")]
    if "disputed_claims" not in columns:
        conn.execute("ALTER TABLE voice_notes ADD COLUMN disputed_claims INTEGER")
        conn.commit()


class CardLedger:
    """Own connection per operation on the store file; never overwrites."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = resolve_db_path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(LEDGER_DDL)
        conn.executescript(VOICE_NOTES_DDL)
        ensure_voice_columns(conn)
        return conn

    def save_card(self, card: Card, now: datetime | None = None) -> None:
        conn = self._connect()
        try:
            present = conn.execute(
                "SELECT 1 FROM telegram_cards WHERE card_id = ?",
                (card.card_id,),
            ).fetchone()
            if present is not None:
                return
            moment = now if now is not None else datetime.now(UTC)
            conn.execute(
                "INSERT INTO telegram_cards (card_id, card_json, created_at)"
                " VALUES (?, ?, ?)",
                (card.card_id, card.model_dump_json(), moment.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    def load(self, card_id: str) -> Card | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT card_json FROM telegram_cards WHERE card_id = ?",
                (card_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return Card.model_validate_json(row[0])

    def record_voice_arrival(
        self, message_id: int, received_at: str, duration_s: int
    ) -> bool:
        """Insert one arrival row; False when already recorded."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO telegram_voice_arrivals"
                " (message_id, received_at, duration_s) VALUES (?, ?, ?)",
                (message_id, received_at, duration_s),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def record_voice_note(
        self, note: VoiceNote, update_id: int, received_at: str
    ) -> bool:
        """Insert one durable voice row; False on re-delivery.

        The row is the queue: the worker claims it later, so the poller
        must write it before the handler runs and before the cursor moves.
        """
        conn = self._connect()
        try:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO voice_notes"
                " (message_id, update_id, telegram_date, file_id,"
                " file_unique_id, duration_s, mime_type, file_size,"
                " reply_to_message_id, received_at, status)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                (
                    note.message_id,
                    update_id,
                    note.date,
                    note.file_id,
                    note.file_unique_id,
                    note.duration_s,
                    note.mime_type,
                    note.file_size,
                    note.reply_to_message_id,
                    received_at,
                ),
            )
            conn.commit()
            return cursor.rowcount == 1
        finally:
            conn.close()

    def save_card_message(
        self, message_id: int, card_id: str, sent_at: str | None = None
    ) -> None:
        """Map one sent Telegram message id to its card; keeps the first."""
        moment = sent_at if sent_at is not None else datetime.now(UTC).isoformat()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR IGNORE INTO telegram_card_messages"
                " (message_id, card_id, sent_at) VALUES (?, ?, ?)",
                (message_id, card_id, moment),
            )
            conn.commit()
        finally:
            conn.close()

    def load_card_message(self, message_id: int) -> str | None:
        """Return the card id sent as a message, or None when unknown."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT card_id FROM telegram_card_messages WHERE message_id = ?",
                (message_id,),
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row is not None else None

    def save_chart(
        self, card_id: str, chart: ChartData, created_at: str | None = None
    ) -> None:
        """Store the sent chart beside the card body; never overwrites."""
        conn = self._connect()
        try:
            present = conn.execute(
                "SELECT 1 FROM telegram_card_charts WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if present is not None:
                return
            moment = (
                created_at if created_at is not None else datetime.now(UTC).isoformat()
            )
            conn.execute(
                "INSERT INTO telegram_card_charts (card_id, chart_json, created_at)"
                " VALUES (?, ?, ?)",
                (card_id, chart.model_dump_json(), moment),
            )
            conn.commit()
        finally:
            conn.close()

    def load_chart(self, card_id: str) -> ChartData | None:
        """Return the stored chart for a card, or None when unknown."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT chart_json FROM telegram_card_charts WHERE card_id = ?",
                (card_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return ChartData.model_validate_json(row[0])
