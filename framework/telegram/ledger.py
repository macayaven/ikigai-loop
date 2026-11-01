"""Card ledger: card bodies and voice arrivals beside the event store."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from framework.store.store import resolve_db_path
from framework.telegram.models import Card

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


class CardLedger:
    """Own connection per operation on the store file; never overwrites."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = resolve_db_path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(LEDGER_DDL)
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
