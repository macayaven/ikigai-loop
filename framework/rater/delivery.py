"""Slice A, AD1: which cards count as delivered, and the run scope.

Read-only SELECTs on a store copy. Delivered is the union of the three
post-acceptance signals; everything else is a named disagreement. The
13 run instants are pinned here and reused by Slice B.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from framework.cycle.orchestrator import SLOT_TIMES

MADRID = ZoneInfo("Europe/Madrid")

_RUN_DAYS = (2, 3, 4)
_FIRST_CARD = datetime(2026, 11, 2, 13, 30, tzinfo=MADRID)
_LAST_CARD = datetime(2026, 11, 4, 18, 0, tzinfo=MADRID)


def run_slots() -> tuple[datetime, ...]:
    """The 13 run instants: Nov 2-4 at the pinned slot times, in bounds."""
    return tuple(
        datetime(2026, 11, day, mark.hour, mark.minute, tzinfo=MADRID)
        for day in _RUN_DAYS
        for mark in SLOT_TIMES
        if _FIRST_CARD
        <= datetime(2026, 11, day, mark.hour, mark.minute, tzinfo=MADRID)
        <= _LAST_CARD
    )


def inside_git_tree(path: Path) -> bool:
    """True when the path or any parent holds a ``.git`` entry."""
    for parent in (path, *path.parents):
        try:
            if (parent / ".git").exists():
                return True
        except OSError:
            return False
    return False


@dataclass(frozen=True)
class DeliveredJoin:
    """Delivered card ids with per-card slots, plus the disagreement counts."""

    delivered: tuple[str, ...]
    slots: dict[str, datetime | None] = field(
        default_factory=dict[str, "datetime | None"]
    )
    counts: dict[str, int] = field(default_factory=dict[str, int])


def column_rows(
    conn: sqlite3.Connection, table: str, column: str, extra: str = ""
) -> list[tuple[Any, ...]]:
    try:
        return [
            tuple(row)
            for row in conn.execute(f"SELECT {column} FROM {table}{extra}").fetchall()
        ]
    except sqlite3.OperationalError:
        return []


def _slots_for(conn: sqlite3.Connection) -> dict[str, datetime | None]:
    import json

    slots: dict[str, datetime | None] = {}
    for card_id, stamp in column_rows(
        conn, "slot_cards", "card_id, slot", " ORDER BY rowid"
    ):
        if card_id not in slots:
            slots[str(card_id)] = (
                datetime.fromisoformat(str(stamp)) if stamp is not None else None
            )
    for table in ("slot_card_payloads", "telegram_cards"):
        for card_id, raw in column_rows(conn, table, "card_id, card_json"):
            if slots.get(str(card_id)) is not None:
                continue
            try:
                moment = json.loads(str(raw)).get("slot")
                slots[str(card_id)] = (
                    datetime.fromisoformat(str(moment)) if moment else None
                )
            except (ValueError, TypeError):
                slots[str(card_id)] = None
    return slots


def delivered_cards(copy_db: Path | str) -> DeliveredJoin:
    """The delivered-card union over read-only SELECTs on the copy."""
    conn = sqlite3.connect(f"file:{copy_db}?mode=ro", uri=True)
    try:
        slot_rows = {
            str(card_id)
            for (card_id,) in column_rows(
                conn,
                "slot_ledger",
                "card_id",
                " WHERE step = 'send' AND outcome = 'delivered'",
            )
            if card_id is not None
        }
        voice_rows = {
            str(card_id)
            for (card_id,) in column_rows(
                conn,
                "voice_notes",
                "new_card_id",
                " WHERE new_card_id IS NOT NULL AND new_card_id != ''",
            )
        }
        message_rows = {
            str(card_id)
            for (card_id,) in column_rows(conn, "telegram_card_messages", "card_id")
        }
        payload_cards = {
            str(card_id)
            for (card_id,) in column_rows(conn, "slot_card_payloads", "card_id")
        } | {
            str(card_id)
            for (card_id,) in column_rows(conn, "telegram_cards", "card_id")
        }
        slots = _slots_for(conn)
        for card_id in payload_cards:
            slots.setdefault(card_id, None)
    finally:
        conn.close()
    delivered = slot_rows | voice_rows | message_rows
    unknown = {card_id for card_id in payload_cards if card_id not in delivered}
    run = set(run_slots())
    outside = sorted(card_id for card_id in delivered if slots.get(card_id) not in run)
    counts = {
        "delivery_slot_without_message_row": len(slot_rows - message_rows),
        "delivery_voice_without_message_row": len(voice_rows - message_rows),
        "delivery_message_without_send_record": len(
            message_rows - slot_rows - voice_rows
        ),
        "delivery_unknown_cards": len(unknown),
        "delivered_cards_outside_run": len(outside),
    }
    return DeliveredJoin(delivered=tuple(sorted(delivered)), slots=slots, counts=counts)
