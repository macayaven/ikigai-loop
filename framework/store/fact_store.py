"""Append-only cycle store (Ticket 9): facts, cycle metadata, raw responses.

Lives in the same DB file as the event store via this sibling module;
``EventStore`` is untouched. ``(cycle_id, run)`` keys every row; a
byte-identical replay is a no-op returning the existing run, and any other
recording for an existing ``cycle_id`` appends the next run. There is no
conflict error and no wall clock in the write path.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any, Self

from framework.glimmer.facts import FactResult
from framework.store.store import canonical_json

DDL = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_id TEXT NOT NULL,
    run INTEGER NOT NULL,
    subject_id TEXT NOT NULL,
    as_of TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    raw_valid INTEGER NOT NULL,
    is_noop INTEGER NOT NULL,
    noop_reason TEXT,
    snapshot TEXT NOT NULL,
    passes TEXT NOT NULL,
    dropped_codes TEXT NOT NULL,
    kept_count INTEGER NOT NULL,
    dropped_count INTEGER NOT NULL,
    PRIMARY KEY (cycle_id, run)
);
CREATE TABLE IF NOT EXISTS facts (
    cycle_id TEXT NOT NULL,
    run INTEGER NOT NULL,
    fact_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    statement TEXT NOT NULL,
    evidence TEXT NOT NULL,
    tier TEXT NOT NULL,
    PRIMARY KEY (cycle_id, run, fact_id)
);
CREATE TABLE IF NOT EXISTS cycle_responses (
    cycle_id TEXT NOT NULL,
    run INTEGER NOT NULL,
    pass TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (cycle_id, run, pass, attempt)
);
CREATE TRIGGER IF NOT EXISTS cycles_no_update
BEFORE UPDATE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles are append-only');
END;
CREATE TRIGGER IF NOT EXISTS cycles_no_delete
BEFORE DELETE ON cycles
BEGIN
    SELECT RAISE(ABORT, 'cycles are append-only');
END;
CREATE TRIGGER IF NOT EXISTS facts_no_update
BEFORE UPDATE ON facts
BEGIN
    SELECT RAISE(ABORT, 'facts are append-only');
END;
CREATE TRIGGER IF NOT EXISTS facts_no_delete
BEFORE DELETE ON facts
BEGIN
    SELECT RAISE(ABORT, 'facts are append-only');
END;
CREATE TRIGGER IF NOT EXISTS cycle_responses_no_update
BEFORE UPDATE ON cycle_responses
BEGIN
    SELECT RAISE(ABORT, 'cycle_responses are append-only');
END;
CREATE TRIGGER IF NOT EXISTS cycle_responses_no_delete
BEFORE DELETE ON cycle_responses
BEGIN
    SELECT RAISE(ABORT, 'cycle_responses are append-only');
END;
"""


def resolve_fact_db_path(db_path: Path | None = None) -> Path:
    """Same file as the event store unless an explicit path is given."""
    if db_path is not None:
        return db_path
    return Path(os.environ.get("IKIGAI_DATA_DIR", "./data")) / "ikigai.db"


def _identity_payload(result: FactResult) -> str:
    """Canonical bytes identifying a recording; equality means replay."""
    return canonical_json(
        {
            "prompt_hash": result.prompt_hash,
            "snapshot": dict(result.snapshot.values),
            "facts": [
                {
                    "fact_id": f.id,
                    "statement": f.statement,
                    "evidence": list(f.evidence),
                    "tier": f.tier,
                    "window_start": f.window.start.isoformat(),
                    "window_end": f.window.end.isoformat(),
                }
                for f in result.facts
            ],
            "dropped": [d.code for d in result.dropped],
            "responses": [
                {
                    "pass": a.pass_name,
                    "attempt": a.attempt,
                    "content": a.content,
                }
                for a in result.responses
            ],
        }
    )


class FactStore:
    """Append-only cycles/facts/cycle_responses in the event DB file."""

    def __init__(self, db_path: Path | None = None) -> None:
        resolved = resolve_fact_db_path(db_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self._conn = sqlite3.connect(resolved, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(DDL)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def runs(self, cycle_id: str) -> list[int]:
        rows = self._conn.execute(
            "SELECT run FROM cycles WHERE cycle_id = ? ORDER BY run", (cycle_id,)
        ).fetchall()
        return [row[0] for row in rows]

    def record_cycle(self, result: FactResult) -> int:
        """Record a cycle; a byte-identical replay returns the existing run."""
        wanted = _identity_payload(result)
        personal, feed = result.passes
        ran = [p for p in (personal, feed) if p.attempts > 0]
        raw_valid = bool(ran) and all(p.raw_valid for p in ran)
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = conn.execute(
                "SELECT run FROM cycles WHERE cycle_id = ?", (result.cycle_id,)
            ).fetchall()
            for (run,) in existing:
                if self._payload_for(result.cycle_id, run, conn) == wanted:
                    conn.execute("COMMIT")
                    return int(run)
            run = max((row[0] for row in existing), default=0) + 1
            conn.execute(
                "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
                " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason,"
                " snapshot, passes, dropped_codes, kept_count, dropped_count)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result.cycle_id,
                    run,
                    result.subject_id,
                    result.as_of.isoformat(),
                    personal.model_id,
                    result.prompt_hash,
                    personal.latency_ms + feed.latency_ms,
                    int(raw_valid),
                    int(result.is_noop),
                    result.noop_reason,
                    canonical_json(dict(result.snapshot.values)),
                    canonical_json([asdict(personal), asdict(feed)]),
                    canonical_json([d.code for d in result.dropped]),
                    len(result.facts),
                    len(result.dropped),
                ),
            )
            for fact in result.facts:
                conn.execute(
                    "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
                    " window_start, window_end, statement, evidence, tier)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.cycle_id,
                        run,
                        fact.id,
                        fact.subject_id,
                        fact.window.start.isoformat(),
                        fact.window.end.isoformat(),
                        fact.statement,
                        canonical_json(list(fact.evidence)),
                        fact.tier,
                    ),
                )
            for attempt in result.responses:
                conn.execute(
                    "INSERT INTO cycle_responses (cycle_id, run, pass, attempt,"
                    " content) VALUES (?, ?, ?, ?, ?)",
                    (
                        result.cycle_id,
                        run,
                        attempt.pass_name,
                        attempt.attempt,
                        attempt.content,
                    ),
                )
            conn.execute("COMMIT")
            return run
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def _payload_for(self, cycle_id: str, run: int, conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT prompt_hash, snapshot, dropped_codes FROM cycles"
            " WHERE cycle_id = ? AND run = ?",
            (cycle_id, run),
        ).fetchone()
        facts = conn.execute(
            "SELECT fact_id, statement, evidence, tier, window_start, window_end"
            " FROM facts WHERE cycle_id = ? AND run = ? ORDER BY rowid",
            (cycle_id, run),
        ).fetchall()
        responses = conn.execute(
            "SELECT pass, attempt, content FROM cycle_responses"
            " WHERE cycle_id = ? AND run = ? ORDER BY rowid",
            (cycle_id, run),
        ).fetchall()
        return canonical_json(
            {
                "prompt_hash": row[0],
                "snapshot": json.loads(row[1]),
                "facts": [
                    {
                        "fact_id": fact_id,
                        "statement": statement,
                        "evidence": json.loads(evidence),
                        "tier": tier,
                        "window_start": window_start,
                        "window_end": window_end,
                    }
                    for fact_id, statement, evidence, tier, window_start, window_end in facts
                ],
                "dropped": json.loads(row[2]),
                "responses": [
                    {"pass": p, "attempt": a, "content": c} for p, a, c in responses
                ],
            }
        )

    def fetch_cycle(self, cycle_id: str, run: int) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT subject_id, as_of, model_id, prompt_hash, latency_ms,"
            " raw_valid, is_noop, noop_reason, snapshot, passes, dropped_codes,"
            " kept_count, dropped_count FROM cycles"
            " WHERE cycle_id = ? AND run = ?",
            (cycle_id, run),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown cycle run: {cycle_id} run {run}")
        return {
            "subject_id": row[0],
            "as_of": row[1],
            "model_id": row[2],
            "prompt_hash": row[3],
            "latency_ms": row[4],
            "raw_valid": bool(row[5]),
            "is_noop": bool(row[6]),
            "noop_reason": row[7],
            "snapshot": json.loads(row[8]),
            "passes": json.loads(row[9]),
            "dropped_codes": json.loads(row[10]),
            "kept_count": row[11],
            "dropped_count": row[12],
        }

    def fetch_facts(self, cycle_id: str, run: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT fact_id, subject_id, window_start, window_end, statement,"
            " evidence, tier FROM facts WHERE cycle_id = ? AND run = ?"
            " ORDER BY rowid",
            (cycle_id, run),
        ).fetchall()
        return [
            {
                "fact_id": fact_id,
                "subject_id": subject_id,
                "window_start": window_start,
                "window_end": window_end,
                "statement": statement,
                "evidence": json.loads(evidence),
                "tier": tier,
            }
            for fact_id, subject_id, window_start, window_end, statement, evidence, tier in rows
        ]

    def fetch_responses(self, cycle_id: str, run: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT pass, attempt, content FROM cycle_responses"
            " WHERE cycle_id = ? AND run = ? ORDER BY rowid",
            (cycle_id, run),
        ).fetchall()
        return [{"pass": p, "attempt": a, "content": c} for p, a, c in rows]
