"""Read-only store reads, table checks, and the scratch-copy helper."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import tempfile
import urllib.parse
from datetime import datetime
from typing import Any

from source_audit.recount import parse_instant

TICKET13 = ("slot_ledger", "slot_cards", "slot_card_payloads")

STORE_COLUMNS: dict[str, tuple[str, ...]] = {
    "events": (
        "subject_id",
        "source",
        "source_id",
        "type",
        "time",
        "collected_at",
        "data",
    ),
    "cycles": ("cycle_id", "run", "subject_id", "as_of", "snapshot"),
    "facts": ("cycle_id", "run", "window_start", "window_end", "statement", "origin"),
    "proposal_results": (
        "profile_id",
        "cycle_id",
        "run",
        "kind",
        "slot",
        "subject_id",
        "briefing_json",
        "snapshot",
    ),
    "telegram_cards": ("card_id", "card_json"),
    "slot_ledger": ("slot", "step", "outcome", "card_id"),
    "slot_cards": ("card_id", "slot", "subject_id", "as_of"),
    "slot_card_payloads": ("card_id", "card_json", "chart_json"),
    "telegram_card_charts": ("card_id", "chart_json"),
    "voice_notes": ("new_card_id",),
}


class StoreError(Exception):
    """A store failure carrying its closed code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def open_ro(path: Any) -> sqlite3.Connection:
    """Open a store read-only without creating anything."""
    text = str(path)
    try:
        conn = sqlite3.connect(f"file:{urllib.parse.quote(text)}?mode=ro", uri=True)
    except sqlite3.Error:
        raise StoreError("STORE_MISSING") from None
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.Error:
        conn.close()
        if os.path.exists(text):
            raise StoreError("STORE_UNREADABLE") from None
        raise StoreError("STORE_MISSING") from None
    return conn


def tables(conn: sqlite3.Connection) -> set[str]:
    """Return the table names in a store."""
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def has(conn: sqlite3.Connection, name: str) -> bool:
    """Check one table exists."""
    return name in tables(conn)


class Scratch:
    """A consistent copy of a live store in a private temporary folder."""

    def __init__(self, path: Any) -> None:
        self.path = str(path)
        open_ro(self.path).close()
        self.folder = tempfile.mkdtemp(prefix="source-audit-")
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> sqlite3.Connection:
        try:
            dest = sqlite3.connect(os.path.join(self.folder, "audit.db"))
            try:
                with contextlib.closing(open_ro(self.path)) as source:
                    source.backup(dest)
                dest.close()
                self._conn = open_ro(os.path.join(self.folder, "audit.db"))
            except BaseException:
                dest.close()
                raise
        except BaseException:
            shutil.rmtree(self.folder, ignore_errors=True)
            raise
        return self._conn

    def __exit__(self, *args: object) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
        finally:
            shutil.rmtree(self.folder, ignore_errors=True)


def _when(value: Any) -> datetime | None:
    """Parse an instant or return None; one helper for every read."""
    if not isinstance(value, str):
        return None
    try:
        return parse_instant(value)
    except ValueError:
        return None


def _loads(text: Any) -> Any:
    """Parse JSON or return None with a marker for invalid JSON."""
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return {"__invalid__": True}


def is_invalid(value: Any) -> bool:
    """Check a loaded column for the invalid-JSON marker."""
    return isinstance(value, dict) and value.get("__invalid__") is True


def distinct_subjects(conn: sqlite3.Connection) -> list[str]:
    """Return distinct subjects among stored GitHub rows."""
    if not has(conn, "events"):
        return []
    query = "SELECT DISTINCT subject_id FROM events WHERE source = 'github'"
    return [row[0] for row in conn.execute(query)]


def _cycle_rows(conn: sqlite3.Connection, subject: str) -> list[dict[str, Any]]:
    """Read one subject's cycles with parsed instants; one read for all picks."""
    if not has(conn, "cycles"):
        return []
    query = "SELECT cycle_id, run, as_of, snapshot FROM cycles WHERE subject_id = ?"
    out = []
    for cycle_id, run, as_of_text, snapshot_text in conn.execute(query, (subject,)):
        as_of = _when(as_of_text)
        if as_of is None:
            continue
        entry = {"cycle_id": str(cycle_id), "run": int(run), "as_of": as_of}
        entry["snapshot"] = _loads(snapshot_text)
        out.append(entry)
    return out


def latest_cycle(conn: sqlite3.Connection, subject: str) -> dict[str, Any] | None:
    """Pick the latest cycle: greatest as_of, then run, then id."""
    rows = _cycle_rows(conn, subject)
    if not rows:
        return None
    return max(rows, key=lambda r: (r["as_of"], r["run"], r["cycle_id"]))


def cycle_at(
    conn: sqlite3.Connection, subject: str, instant: datetime
) -> dict[str, Any] | None:
    """Pick the stored cycle at an instant, greatest run wins."""
    cands = [r for r in _cycle_rows(conn, subject) if r["as_of"] == instant]
    if not cands:
        return None
    return max(cands, key=lambda r: (r["run"], r["cycle_id"]))


def cycle_get(conn: sqlite3.Connection, cycle_id: str, run: int) -> dict | None:
    """Fetch one cycle run with its snapshot, or None."""
    if not has(conn, "cycles"):
        return None
    query = "SELECT as_of, snapshot FROM cycles WHERE cycle_id = ? AND run = ?"
    row = conn.execute(query, (cycle_id, run)).fetchone()
    as_of = _when(row[0]) if row is not None else None
    if as_of is None:
        return None
    entry = {"cycle_id": cycle_id, "run": run, "as_of": as_of}
    entry["snapshot"] = _loads(row[1] if row is not None else None)
    return entry


def facts_for(conn: sqlite3.Connection, cycle_id: str, run: int) -> list[dict]:
    """Read a cycle's facts in rowid order without printing origins."""
    if not has(conn, "facts"):
        return []
    cols = [row[1] for row in conn.execute("PRAGMA table_info(facts)")]
    extra = ", origin" if "origin" in cols else ""
    query = (
        "SELECT rowid, cycle_id, run, window_start, window_end, statement"
        f"{extra} FROM facts WHERE cycle_id = ? AND run = ? ORDER BY rowid"
    )
    return [
        {
            "rowid": row[0],
            "window_start": _when(row[3]),
            "window_end": _when(row[4]),
            "statement": row[5],
        }
        for row in conn.execute(query, (cycle_id, run)).fetchall()
    ]


def github_rows(
    conn: sqlite3.Connection, subject: str, start: Any, end: Any
) -> tuple[list[dict], list[dict]]:
    """Read stored GitHub rows in the floored window as instants."""
    if not has(conn, "events"):
        return [], []
    if isinstance(start, str):
        start = parse_instant(start)
    if isinstance(end, str):
        end = parse_instant(end)
    query = (
        "SELECT source_id, type, time, collected_at, data FROM events "
        "WHERE subject_id = ? AND source = 'github' ORDER BY time, id"
    )
    out, unreadable = [], []
    for source_id, kind, time_text, collected_text, data_text in conn.execute(
        query, (subject,)
    ):
        moment, collected = _when(time_text), _when(collected_text)
        if moment is None or collected is None or not start <= moment < end:
            continue
        try:
            data = json.loads(data_text)
        except (ValueError, TypeError):
            data = None
        if not isinstance(data, dict):
            unreadable.append({"source_id": str(source_id), "type": str(kind)})
            continue
        counts = data.get("counts")
        row = {
            "source_id": str(source_id),
            "type": str(kind),
            "time": moment,
            "collected_at": collected,
        }
        row["counts"] = counts if isinstance(counts, dict) else {}
        out.append(row)
    return out, unreadable


def results_at(conn: sqlite3.Connection, subject: str, slot: Any) -> list[dict]:
    """Take the latest proposal or fallback row per profile at one slot."""
    if not has(conn, "proposal_results"):
        return []
    query = (
        "SELECT rowid, profile_id, cycle_id, run, kind, slot, briefing_json,"
        " snapshot FROM proposal_results WHERE subject_id = ?"
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in conn.execute(query, (subject,)):
        rowid, profile, cycle_id, run, kind, slot_text, briefing_text, snap_text = row
        if kind not in ("proposal", "fallback") or _when(slot_text) != slot:
            continue
        if profile not in latest or rowid > latest[profile]["rowid"]:
            entry = {
                "rowid": rowid,
                "profile_id": profile,
                "cycle_id": cycle_id,
                "run": run,
                "kind": kind,
            }
            entry.update(briefing=_loads(briefing_text), snapshot=_loads(snap_text))
            latest[profile] = entry
    return [latest[key] for key in sorted(latest)]


def results_rows_at(conn: sqlite3.Connection, subject: str, slot: Any) -> list[dict]:
    """Read every proposal or fallback row at one slot, in rowid order."""
    if not has(conn, "proposal_results"):
        return []
    query = (
        "SELECT rowid, profile_id, cycle_id, run, kind, slot, briefing_json,"
        " snapshot FROM proposal_results WHERE subject_id = ? ORDER BY rowid"
    )
    out = []
    for row in conn.execute(query, (subject,)):
        rowid, profile, cycle_id, run, kind, slot_text, briefing_text, snap_text = row
        if kind not in ("proposal", "fallback") or _when(slot_text) != slot:
            continue
        out.append(
            {
                "rowid": rowid,
                "profile_id": profile,
                "cycle_id": cycle_id,
                "run": run,
                "kind": kind,
            }
            | {"briefing": _loads(briefing_text), "snapshot": _loads(snap_text)}
        )
    return out


def card_claim_texts(briefing: Any) -> list[str]:
    """Restate the product's card-claim rule without importing it.

    The first overall_state claim first, then the remaining claims in
    section order, three at most. Only string texts count. Anything that
    is not a briefing object with claim lists simply has no card claims.
    """
    if not isinstance(briefing, dict):
        return []
    sections = briefing.get("sections")
    if not isinstance(sections, list):
        return []
    ordered: list[dict] = []
    first: dict | None = None
    for section in sections:
        if not isinstance(section, dict):
            continue
        claims = section.get("claims")
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if first is None and section.get("type") == "overall_state":
                first = claim
            ordered.append(claim)
    if first is not None:
        ordered = [first, *[claim for claim in ordered if claim is not first]]
    return [claim["text"] for claim in ordered if isinstance(claim.get("text"), str)][
        :3
    ]


def own_rows_for(rows: list[dict], statements: Any) -> list[dict]:
    """Pick one row per profile: the latest whose card claims sit on the card.

    A row qualifies when it has at least one card claim and every one
    appears word for word among the card's statements. Otherwise the
    latest row of that profile is taken, which is today's rule.
    """
    wanted = (
        {text for text in statements if isinstance(text, str)}
        if isinstance(statements, list)
        else set()
    )
    by_profile: dict[str, list[dict]] = {}
    for row in rows:
        by_profile.setdefault(str(row["profile_id"]), []).append(row)
    out = []
    for profile in sorted(by_profile):
        cands = by_profile[profile]
        pick = cands[-1]
        for row in reversed(cands):
            texts = card_claim_texts(row.get("briefing"))
            if texts and all(text in wanted for text in texts):
                pick = row
                break
        out.append(pick)
    return out


def card_chart(conn: sqlite3.Connection, card_id: Any) -> Any:
    """Read one corrected card's chart, or None when the table has none."""
    if not has(conn, "telegram_card_charts"):
        return None
    try:
        row = conn.execute(
            "SELECT chart_json FROM telegram_card_charts WHERE card_id = ?",
            (card_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return _loads(row[0])


def _chain_reaches(card: dict, slot_id: Any, slot: Any, by_id: dict[Any, Any]) -> bool:
    """Walk replaces_card_id links to the slot card, staying on this slot."""
    seen: set[Any] = set()
    link = card.get("replaces_card_id")
    while isinstance(link, str) and link and link not in seen:
        if link == slot_id:
            return True
        seen.add(link)
        nxt = by_id.get(link)
        if not isinstance(nxt, dict):
            return False
        if _when(nxt.get("slot")) != slot:
            return False
        link = nxt.get("replaces_card_id")
    return False


def corrected_cards(conn: sqlite3.Connection, slot_card: dict | None) -> list[dict]:
    """Read corrected cards at the slot card's slot with voice proof.

    A corrected card names the slot instant, its replaces_card_id chain
    reaches the slot card through cards of that slot, and a voice_notes
    row names its card id in new_card_id. Only new_card_id is read from
    voice_notes. A missing table or column means no corrected cards.
    """
    if not isinstance(slot_card, dict):
        return []
    slot, slot_id = slot_card.get("slot"), slot_card.get("card_id")
    if not isinstance(slot, datetime):
        return []
    if not has(conn, "telegram_cards") or not has(conn, "voice_notes"):
        return []
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(voice_notes)")]
    except sqlite3.Error:
        return []
    if "new_card_id" not in columns:
        return []
    try:
        proof = {
            row[0]
            for row in conn.execute("SELECT new_card_id FROM voice_notes")
            if isinstance(row[0], str) and row[0]
        }
    except sqlite3.Error:
        return []
    try:
        rows = conn.execute(
            "SELECT rowid, card_id, card_json FROM telegram_cards ORDER BY rowid"
        ).fetchall()
    except sqlite3.Error:
        return []
    by_id: dict[Any, Any] = {}
    cands = []
    for rowid, card_id, card_text in rows:
        card = _loads(card_text)
        by_id[card_id] = card
        cands.append((rowid, card_id, card))
    out = []
    for rowid, card_id, card in cands:
        if not isinstance(card, dict):
            continue
        if _when(card.get("slot")) != slot:
            continue
        if not isinstance(card_id, str) or card_id not in proof:
            continue
        if not _chain_reaches(card, slot_id, slot, by_id):
            continue
        out.append(
            {
                "card_id": card_id,
                "slot": slot,
                "rowid": rowid,
                "card": card,
                "chart": card_chart(conn, card_id),
                "proven": True,
            }
        )
    out.sort(key=lambda entry: entry["rowid"])
    return out


def ticket13_cards(conn: sqlite3.Connection, subject: str) -> list[dict] | None:
    """Read delivered cards for the audited subject, or None without them."""
    if any(not has(conn, name) for name in TICKET13):
        return None
    ledgers = conn.execute(
        "SELECT rowid, slot, step, outcome, card_id FROM slot_ledger"
    ).fetchall()
    cards = conn.execute(
        "SELECT rowid, card_id, slot, subject_id, as_of FROM slot_cards"
    ).fetchall()
    by_card: dict[str, Any] = {}
    for row in cards:
        if row[3] != subject:
            continue
        if row[1] not in by_card or row[0] > by_card[row[1]][0]:
            by_card[row[1]] = row
    payloads = {
        row[0]: row[1:]
        for row in conn.execute(
            "SELECT card_id, card_json, chart_json FROM slot_card_payloads"
        )
    }
    out = []
    for _, slot_text, step, outcome, card_id in ledgers:
        if step != "send" or outcome != "delivered":
            continue
        info = by_card.get(card_id)
        if info is None:
            continue
        slot = _when(info[2])
        if slot is None:
            continue
        payload = payloads.get(card_id, (None, None))
        entry = {
            "card_id": card_id,
            "slot": slot,
            "as_of": _when(info[4]),
            "rowid": info[0],
        }
        entry.update(card=_loads(payload[0]), chart=_loads(payload[1]))
        out.append(entry)
    return out


def fallback_cards(conn: sqlite3.Connection) -> list[dict] | None:
    """Read ledger cards on the fallback path, or None without the table."""
    if not has(conn, "telegram_cards"):
        return None
    query = "SELECT rowid, card_id, card_json FROM telegram_cards"
    out = []
    for rowid, card_id, card_text in conn.execute(query).fetchall():
        card = _loads(card_text)
        slot = _when(card.get("slot")) if isinstance(card, dict) else None
        out.append({"card_id": card_id, "rowid": rowid, "slot": slot, "card": card})
    return out
