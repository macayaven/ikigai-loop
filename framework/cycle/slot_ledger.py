"""Ticket 13 slice 2: the slot ledger, one owner of the append-only record.

Five tables, each with update and delete triggers: ``slot_ledger`` holds
one row per step, ``slot_cards`` one row per card side, ``slot_card_payloads``
the exact bytes that went out, ``learner_states`` one row per replayed state,
and ``local_start_retries`` one row per retried local start failure.
Send rows use steps ``send_intent`` and ``send``; a ``send`` outcome is one of
``delivered``, ``DELIVERY_UNKNOWN``, ``SEND_NOT_SENT``, ``SEND_REFUSED``.
A ``watchdog`` row records a code ``check-slot`` already reported. Masked
stderr lives only in ``local_start_retries``; ``slot_ledger.detail`` keeps
closed codes and counts.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")

DDL = """
CREATE TABLE IF NOT EXISTS slot_ledger (
    slot TEXT NOT NULL,
    step TEXT NOT NULL,
    outcome TEXT NOT NULL,
    seconds REAL NOT NULL,
    card_id TEXT,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slot_cards (
    card_id TEXT NOT NULL,
    letter TEXT NOT NULL,
    slot TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    bucket TEXT,
    profile_id TEXT NOT NULL,
    commitment_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    policy_pick TEXT,
    policy_alternative TEXT,
    PRIMARY KEY (card_id, letter)
);
CREATE TABLE IF NOT EXISTS slot_card_payloads (
    card_id TEXT PRIMARY KEY,
    card_json TEXT NOT NULL,
    chart_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learner_states (
    id INTEGER PRIMARY KEY,
    slot TEXT NOT NULL,
    state_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_start_retries (
    slot TEXT NOT NULL,
    profile TEXT NOT NULL,
    try INTEGER NOT NULL,
    reason TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    exit_code INTEGER,
    stderr TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS slot_ledger_no_update
BEFORE UPDATE ON slot_ledger
BEGIN
    SELECT RAISE(ABORT, 'slot_ledger is append-only');
END;
CREATE TRIGGER IF NOT EXISTS slot_ledger_no_delete
BEFORE DELETE ON slot_ledger
BEGIN
    SELECT RAISE(ABORT, 'slot_ledger is append-only');
END;
CREATE TRIGGER IF NOT EXISTS slot_cards_no_update
BEFORE UPDATE ON slot_cards
BEGIN
    SELECT RAISE(ABORT, 'slot_cards is append-only');
END;
CREATE TRIGGER IF NOT EXISTS slot_cards_no_delete
BEFORE DELETE ON slot_cards
BEGIN
    SELECT RAISE(ABORT, 'slot_cards are append-only');
END;
CREATE TRIGGER IF NOT EXISTS slot_card_payloads_no_update
BEFORE UPDATE ON slot_card_payloads
BEGIN
    SELECT RAISE(ABORT, 'slot_card_payloads is append-only');
END;
CREATE TRIGGER IF NOT EXISTS slot_card_payloads_no_delete
BEFORE DELETE ON slot_card_payloads
BEGIN
    SELECT RAISE(ABORT, 'slot_card_payloads is append-only');
END;
CREATE TRIGGER IF NOT EXISTS learner_states_no_update
BEFORE UPDATE ON learner_states
BEGIN
    SELECT RAISE(ABORT, 'learner_states is append-only');
END;
CREATE TRIGGER IF NOT EXISTS learner_states_no_delete
BEFORE DELETE ON learner_states
BEGIN
    SELECT RAISE(ABORT, 'learner_states is append-only');
END;
CREATE TRIGGER IF NOT EXISTS local_start_retries_no_update
BEFORE UPDATE ON local_start_retries
BEGIN
    SELECT RAISE(ABORT, 'local_start_retries is append-only');
END;
CREATE TRIGGER IF NOT EXISTS local_start_retries_no_delete
BEFORE DELETE ON local_start_retries
BEGIN
    SELECT RAISE(ABORT, 'local_start_retries is append-only');
END;
"""

_SEND_STEPS = ("send_intent", "send")
_SEND_OUTCOMES = (
    "delivered",
    "DELIVERY_UNKNOWN",
    "SEND_NOT_SENT",
    "SEND_REFUSED",
)
_NO_SEND = "none"
_INTENT_OPEN = "intent_open"


class LedgerWriteBlocked(Exception):
    """A write hit a locked database past the caller-given deadline."""


@dataclass(frozen=True)
class SlotLedgerRow:
    """One step row, in rowid order."""

    rowid: int
    slot: datetime
    step: str
    outcome: str
    seconds: float
    card_id: str | None
    detail: str


@dataclass(frozen=True)
class LocalStartRetryRow:
    """One retried local start failure: masked stderr only, never raw text."""

    slot: datetime
    profile: str
    attempt: int
    reason: str
    latency_ms: int
    exit_code: int | None
    stderr_masked: str


@dataclass(frozen=True)
class SlotCardRow:
    """One card side: everything replay needs, in stored letter order."""

    card_id: str
    letter: str
    slot: datetime
    subject_id: str
    as_of: datetime
    bucket: str | None
    profile_id: str
    commitment_id: str
    kind: str
    policy_pick: str | None
    policy_alternative: str | None


def _open(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(DDL)
    except Exception:
        conn.close()
        raise
    return conn


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(ZoneInfo("UTC")).isoformat()


def _has_whitespace(value: str) -> bool:
    return any(mark in value for mark in (" ", "\t", "\n", "\r"))


_DETAIL_CLEAN_RE = "[^A-Za-z0-9._-]"


def sanitise_detail_value(value: str) -> str:
    """Make free text safe for a ``detail`` value.

    Every character outside ``[A-Za-z0-9._-]`` becomes ``_``, cut to
    40 characters, so a value like a ``muse --version`` line can never
    trip the whitespace refusal and stop a slot. Closed codes and
    numbers never need this; they go through unchanged.
    """
    import re

    return re.sub(_DETAIL_CLEAN_RE, "_", value)[:40]


def _format_detail(detail: Mapping[str, object] | None) -> str:
    if not detail:
        return ""
    pairs: list[str] = []
    for key in sorted(detail):
        if not key or _has_whitespace(key) or "=" in key:
            raise ValueError(f"detail key is not closed: {key!r}")
        value = "" if detail[key] is None else str(detail[key])
        if _has_whitespace(value):
            raise ValueError(f"detail value holds whitespace for {key!r}")
        pairs.append(f"{key}={value}")
    return " ".join(pairs)


def parse_detail(detail: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for pair in detail.split(" "):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        parsed[key] = value
    return parsed


class SlotLedger:
    """Append-only slot state; one connection per operation."""

    def __init__(
        self,
        db_path: Path | str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._sleep = sleep
        self._clock = clock

    def _write(
        self, work: Callable[[sqlite3.Connection], int], timeout_s: float
    ) -> int:
        start = self._clock()
        while True:
            try:
                conn = _open(self.db_path)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if self._clock() - start >= timeout_s:
                    raise LedgerWriteBlocked("database is locked") from exc
                self._sleep(0.05)
                continue
            try:
                return work(conn)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if self._clock() - start >= timeout_s:
                    raise LedgerWriteBlocked("database is locked") from exc
                self._sleep(0.05)
            finally:
                conn.close()

    def _read(self, query: str, args: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        conn = _open(self.db_path)
        try:
            return [tuple(row) for row in conn.execute(query, args).fetchall()]
        finally:
            conn.close()

    def append_step(
        self,
        slot: datetime,
        step: str,
        outcome: str,
        seconds: float,
        card_id: str | None,
        detail: Mapping[str, object] | None,
        *,
        timeout_s: float = 30.0,
    ) -> int:
        """Append one step row; detail values must hold no whitespace."""
        text = _format_detail(detail)
        stamp = _utc_text(slot)

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO slot_ledger (slot, step, outcome, seconds,"
                " card_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (stamp, step, outcome, seconds, card_id, text),
            )
            conn.commit()
            rowid = cursor.lastrowid
            assert rowid is not None
            return rowid

        return self._write(_insert, timeout_s)

    def rows_for_slot(self, slot: datetime) -> tuple[SlotLedgerRow, ...]:
        """Every step row for one slot, in rowid order."""
        found = self._read(
            "SELECT rowid, slot, step, outcome, seconds, card_id, detail"
            " FROM slot_ledger WHERE slot = ? ORDER BY rowid",
            (_utc_text(slot),),
        )
        return tuple(
            SlotLedgerRow(
                rowid=int(rowid),
                slot=datetime.fromisoformat(str(stamp)),
                step=str(step),
                outcome=str(outcome),
                seconds=float(seconds),
                card_id=None if card_id is None else str(card_id),
                detail=str(detail),
            )
            for rowid, stamp, step, outcome, seconds, card_id, detail in found
        )

    def latest_start_as_of(self, slot: datetime) -> datetime | None:
        """The latest ``start`` row's ``as_of``; ``None`` when no start row."""
        rows = [row for row in self.rows_for_slot(slot) if row.step == "start"]
        if not rows:
            return None
        raw = parse_detail(rows[-1].detail).get("as_of")
        return datetime.fromisoformat(raw) if raw else None

    def send_state(self, slot: datetime) -> str:
        """One of none, intent_open, delivered, DELIVERY_UNKNOWN,
        SEND_NOT_SENT, SEND_REFUSED, read from the last send rows."""
        rows = [row for row in self.rows_for_slot(slot) if row.step in _SEND_STEPS]
        if not rows:
            return _NO_SEND
        last = rows[-1]
        if last.step == "send_intent":
            return _INTENT_OPEN
        if last.outcome in _SEND_OUTCOMES:
            return last.outcome
        return _INTENT_OPEN

    def calendar_cursor_times(self) -> tuple[datetime, ...]:
        """The ``updated_at`` of every ``calendar-`` cursor, oldest first.

        A file without the table, or with no such row, gives an empty
        answer and does not fail; an unparseable stamp is skipped. A
        naive stamp reads as UTC here, before anything compares the
        stamps, so a mix of naive and aware stamps still sorts.
        """
        try:
            found = self._read(
                "SELECT updated_at FROM cursors WHERE name LIKE 'calendar-%'"
            )
        except sqlite3.OperationalError:
            return ()
        stamps: list[datetime] = []
        for (raw,) in found:
            try:
                stamp = datetime.fromisoformat(str(raw))
            except ValueError:
                continue
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
            stamps.append(stamp)
        return tuple(sorted(stamps))

    def disconnect_count(self, day: date) -> int:
        """Disconnect cards on one Madrid day over delivered and unknown sends."""
        found = self._read(
            "SELECT DISTINCT slot FROM slot_cards WHERE profile_id = ?",
            ("disconnect",),
        )
        count = 0
        for (stamp,) in found:
            slot = datetime.fromisoformat(str(stamp))
            if slot.astimezone(MADRID).date() != day:
                continue
            if self.send_state(slot) in (
                "delivered",
                "DELIVERY_UNKNOWN",
                "intent_open",
            ):
                count += 1
        return count

    def latest_delivered_card_id(self, before_slot: datetime) -> str | None:
        """The latest ``delivered`` card strictly before a slot."""
        found = self._read(
            "SELECT slot, card_id FROM slot_ledger"
            " WHERE step = 'send' AND outcome = 'delivered'"
            " AND slot < ? ORDER BY slot DESC LIMIT 1",
            (_utc_text(before_slot),),
        )
        if not found:
            return None
        return None if found[0][1] is None else str(found[0][1])

    def latest_proposal_slot(
        self, profile_id: str, before_slot: datetime
    ) -> datetime | None:
        """The latest delivered slot before a slot whose delivered card's
        side for a profile has kind ``proposal``."""
        found = self._read(
            "SELECT DISTINCT slot FROM slot_cards WHERE profile_id = ?",
            (profile_id,),
        )
        best: datetime | None = None
        for (stamp,) in found:
            slot = datetime.fromisoformat(str(stamp))
            if slot >= before_slot.astimezone(ZoneInfo("UTC")):
                continue
            delivered = self._read(
                "SELECT card_id FROM slot_ledger"
                " WHERE slot = ? AND step = 'send' AND outcome = 'delivered'"
                " ORDER BY rowid DESC LIMIT 1",
                (_utc_text(slot),),
            )
            if not delivered or delivered[0][0] is None:
                continue
            kinds = self._read(
                "SELECT kind FROM slot_cards WHERE card_id = ? AND profile_id = ?",
                (str(delivered[0][0]), profile_id),
            )
            if not any(str(kind) == "proposal" for (kind,) in kinds):
                continue
            if best is None or slot > best:
                best = slot
        return best

    def save_slot_cards(
        self, rows: Sequence[SlotCardRow], *, timeout_s: float = 30.0
    ) -> None:
        """Save side rows keyed by ``(card_id, letter)``."""

        def _insert(conn: sqlite3.Connection) -> int:
            for row in rows:
                conn.execute(
                    "INSERT INTO slot_cards (card_id, letter, slot, subject_id,"
                    " as_of, bucket, profile_id, commitment_id, kind,"
                    " policy_pick, policy_alternative)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row.card_id,
                        row.letter,
                        _utc_text(row.slot),
                        row.subject_id,
                        _utc_text(row.as_of),
                        row.bucket,
                        row.profile_id,
                        row.commitment_id,
                        row.kind,
                        row.policy_pick,
                        row.policy_alternative,
                    ),
                )
            conn.commit()
            return len(rows)

        self._write(_insert, timeout_s)

    def _card_rows(
        self, query: str, args: tuple[object, ...]
    ) -> tuple[SlotCardRow, ...]:
        found = self._read(query, args)
        rows = tuple(
            SlotCardRow(
                card_id=str(card_id),
                letter=str(letter),
                slot=datetime.fromisoformat(str(slot)),
                subject_id=str(subject_id),
                as_of=datetime.fromisoformat(str(as_of)),
                bucket=None if bucket is None else str(bucket),
                profile_id=str(profile_id),
                commitment_id=str(commitment_id),
                kind=str(kind),
                policy_pick=None if pick is None else str(pick),
                policy_alternative=None if alt is None else str(alt),
            )
            for (
                card_id,
                letter,
                slot,
                subject_id,
                as_of,
                bucket,
                profile_id,
                commitment_id,
                kind,
                pick,
                alt,
            ) in found
        )
        return tuple(sorted(rows, key=lambda row: (row.slot, row.letter)))

    def slot_cards_for_slot(self, slot: datetime) -> tuple[SlotCardRow, ...]:
        """Side rows for one slot, letter order."""
        return self._card_rows(
            "SELECT card_id, letter, slot, subject_id, as_of, bucket,"
            " profile_id, commitment_id, kind, policy_pick, policy_alternative"
            " FROM slot_cards WHERE slot = ? ORDER BY letter",
            (_utc_text(slot),),
        )

    def slot_cards_for_card(self, card_id: str) -> tuple[SlotCardRow, ...]:
        """Side rows for one card, letter order."""
        return self._card_rows(
            "SELECT card_id, letter, slot, subject_id, as_of, bucket,"
            " profile_id, commitment_id, kind, policy_pick, policy_alternative"
            " FROM slot_cards WHERE card_id = ? ORDER BY letter",
            (card_id,),
        )

    def save_card_payload(
        self,
        card_id: str,
        card_json: str,
        chart_json: str,
        *,
        timeout_s: float = 30.0,
    ) -> None:
        """Save the exact card and chart bytes a resend must reuse."""

        def _insert(conn: sqlite3.Connection) -> int:
            conn.execute(
                "INSERT INTO slot_card_payloads (card_id, card_json, chart_json)"
                " VALUES (?, ?, ?)",
                (card_id, card_json, chart_json),
            )
            conn.commit()
            return 1

        self._write(_insert, timeout_s)

    def load_card_payload(self, card_id: str) -> tuple[str, str] | None:
        """The stored card and chart bytes, or ``None``."""
        found = self._read(
            "SELECT card_json, chart_json FROM slot_card_payloads WHERE card_id = ?",
            (card_id,),
        )
        if not found:
            return None
        return (str(found[0][0]), str(found[0][1]))

    def save_card_step(
        self,
        slot: datetime,
        card_id: str,
        detail: Mapping[str, object] | None,
        sides: Sequence[SlotCardRow],
        card_json: str,
        chart_json: str,
        seconds: float,
        *,
        timeout_s: float = 30.0,
    ) -> int:
        """Write the card step atomically: sides, payload, then the row.

        One transaction holds the side rows (``INSERT OR IGNORE`` on
        ``(card_id, letter)``), the payload (``INSERT OR IGNORE`` on
        ``card_id``) and the ``card`` step row, so a crash can never
        leave sides without a ``card`` row and a rebuild after such a
        crash cannot collide: an identical card id means the same card.
        """
        text = _format_detail(detail)
        stamp = _utc_text(slot)

        def _insert(conn: sqlite3.Connection) -> int:
            for row in sides:
                conn.execute(
                    "INSERT OR IGNORE INTO slot_cards (card_id, letter, slot,"
                    " subject_id, as_of, bucket, profile_id, commitment_id,"
                    " kind, policy_pick, policy_alternative)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row.card_id,
                        row.letter,
                        _utc_text(row.slot),
                        row.subject_id,
                        _utc_text(row.as_of),
                        row.bucket,
                        row.profile_id,
                        row.commitment_id,
                        row.kind,
                        row.policy_pick,
                        row.policy_alternative,
                    ),
                )
            conn.execute(
                "INSERT OR IGNORE INTO slot_card_payloads"
                " (card_id, card_json, chart_json) VALUES (?, ?, ?)",
                (card_id, card_json, chart_json),
            )
            cursor = conn.execute(
                "INSERT INTO slot_ledger (slot, step, outcome, seconds,"
                " card_id, detail) VALUES (?, 'card', 'ok', ?, ?, ?)",
                (stamp, seconds, card_id, text),
            )
            conn.commit()
            rowid = cursor.lastrowid
            assert rowid is not None
            return rowid

        return self._write(_insert, timeout_s)

    def latest_card_id(self, slot: datetime) -> str | None:
        """The latest ``card`` step row's card id, or ``None``.

        This is the card of the slot. ``slot_cards_for_slot`` alone is
        never enough, because ``--fresh`` can leave two card ids here.
        """
        found = self._read(
            "SELECT card_id FROM slot_ledger WHERE slot = ? AND step = 'card'"
            " ORDER BY rowid DESC LIMIT 1",
            (_utc_text(slot),),
        )
        if not found or found[0][0] is None:
            return None
        return str(found[0][0])

    def all_slot_cards(self) -> tuple[SlotCardRow, ...]:
        """Every stored side row, for tally and replay joins."""
        return self._card_rows(
            "SELECT card_id, letter, slot, subject_id, as_of, bucket,"
            " profile_id, commitment_id, kind, policy_pick, policy_alternative"
            " FROM slot_cards",
            (),
        )

    def append_learner_state(
        self, slot: datetime, state_json: str, *, timeout_s: float = 30.0
    ) -> int:
        """Append one replayed learner state row."""

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO learner_states (slot, state_json) VALUES (?, ?)",
                (_utc_text(slot), state_json),
            )
            conn.commit()
            rowid = cursor.lastrowid
            assert rowid is not None
            return rowid

        return self._write(_insert, timeout_s)

    def learner_state_for_slot(self, slot: datetime) -> str | None:
        """The latest stored state for one slot, or ``None``."""
        found = self._read(
            "SELECT state_json FROM learner_states WHERE slot = ?"
            " ORDER BY id DESC LIMIT 1",
            (_utc_text(slot),),
        )
        return None if not found else str(found[0][0])

    def append_local_retry(
        self,
        slot: datetime,
        profile: str,
        attempt: int,
        reason: str,
        latency_ms: int,
        exit_code: int | None,
        stderr_masked: str,
        *,
        timeout_s: float = 30.0,
    ) -> int:
        """Append one retried local start failure row."""

        def _insert(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "INSERT INTO local_start_retries (slot, profile, try, reason,"
                " latency_ms, exit_code, stderr) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _utc_text(slot),
                    profile,
                    attempt,
                    reason,
                    latency_ms,
                    exit_code,
                    stderr_masked,
                ),
            )
            conn.commit()
            rowid = cursor.lastrowid
            assert rowid is not None
            return rowid

        return self._write(_insert, timeout_s)

    def local_retries_for_slot(self, slot: datetime) -> tuple[LocalStartRetryRow, ...]:
        """Every retried local start failure for one slot, in try order."""
        found = self._read(
            "SELECT slot, profile, try, reason, latency_ms, exit_code, stderr"
            " FROM local_start_retries WHERE slot = ? ORDER BY rowid",
            (_utc_text(slot),),
        )
        return tuple(
            LocalStartRetryRow(
                slot=datetime.fromisoformat(str(stamp)),
                profile=str(profile),
                attempt=int(attempt),
                reason=str(reason),
                latency_ms=int(latency_ms),
                exit_code=None if exit_code is None else int(exit_code),
                stderr_masked=str(stderr),
            )
            for stamp, profile, attempt, reason, latency_ms, exit_code, stderr in found
        )

    def append_watchdog(
        self, slot: datetime, code: str, *, timeout_s: float = 30.0
    ) -> int:
        """Record that a degraded code was reported for one slot."""
        return self.append_step(
            slot, "watchdog", code, 0.0, None, None, timeout_s=timeout_s
        )

    def watchdog_alerted(self, code: str, day: date) -> bool:
        """Whether a code already has a watchdog row on a Madrid day."""
        found = self._read(
            "SELECT slot FROM slot_ledger WHERE step = 'watchdog' AND outcome = ?",
            (code,),
        )
        return any(
            datetime.fromisoformat(str(stamp)).astimezone(MADRID).date() == day
            for (stamp,) in found
        )
