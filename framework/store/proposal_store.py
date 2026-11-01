"""Append-only proposal store (Ticket 11): attempts and results.

Lives in the same database file as the event and fact stores. Every
attempt and every result persists in one transaction; re-runs at the same
slot take a suffixed key instead of overwriting. Raw response text and the
gate snapshot stay local and are never printed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

from framework.briefing.context import MetricSnapshot, TimeInterval
from framework.briefing.schemas import Briefing
from framework.proposal.core import ProposalResult
from framework.proposal.schemas import FallbackProposal
from framework.store.fact_store import resolve_fact_db_path
from framework.store.store import canonical_json

DDL = """
CREATE TABLE IF NOT EXISTS proposal_attempts (
    proposal_key TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    run INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    model_requested TEXT NOT NULL,
    model_reported TEXT NOT NULL,
    effort TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    parsed_ok INTEGER NOT NULL,
    blocked INTEGER NOT NULL,
    gate_codes TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens INTEGER,
    finish_reason TEXT,
    cached_tokens INTEGER,
    transport TEXT NOT NULL,
    transport_version TEXT,
    harness_rules_file INTEGER,
    PRIMARY KEY (proposal_key, attempt)
);
CREATE TABLE IF NOT EXISTS proposal_results (
    proposal_key TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    run INTEGER NOT NULL,
    profile_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    slot TEXT NOT NULL,
    kind TEXT NOT NULL,
    briefing_json TEXT,
    fallback_json TEXT,
    snapshot TEXT NOT NULL,
    hour_start TEXT,
    hour_end TEXT,
    reason_codes TEXT NOT NULL,
    cycle_age_s REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS proposal_attempts_no_update
BEFORE UPDATE ON proposal_attempts
BEGIN
    SELECT RAISE(ABORT, 'proposal attempts are append-only');
END;
CREATE TRIGGER IF NOT EXISTS proposal_attempts_no_delete
BEFORE DELETE ON proposal_attempts
BEGIN
    SELECT RAISE(ABORT, 'proposal attempts are append-only');
END;
CREATE TRIGGER IF NOT EXISTS proposal_results_no_update
BEFORE UPDATE ON proposal_results
BEGIN
    SELECT RAISE(ABORT, 'proposal results are append-only');
END;
CREATE TRIGGER IF NOT EXISTS proposal_results_no_delete
BEFORE DELETE ON proposal_results
BEGIN
    SELECT RAISE(ABORT, 'proposal results are append-only');
END;
"""

FIRST_DRAFT_REPORT_SQL = """
WITH a1 AS (
    SELECT proposal_key, model_requested AS model, effort, blocked,
        parsed_ok, gate_codes
    FROM proposal_attempts WHERE attempt = 1
),
reached AS (
    SELECT * FROM a1
    WHERE blocked = 0 AND gate_codes NOT LIKE '%MODEL_UNAVAILABLE%'
),
retried AS (
    SELECT DISTINCT proposal_key FROM proposal_attempts WHERE attempt = 2
)
SELECT 'first_drafts' AS grain, model, effort, '' AS code, COUNT(*) AS n
    FROM reached GROUP BY model, effort
UNION ALL
SELECT 'first_passed', model, effort, '', COUNT(*)
    FROM reached WHERE parsed_ok = 1 AND gate_codes = '[]'
    GROUP BY model, effort
UNION ALL
SELECT 'first_failed', model, effort, '', COUNT(*)
    FROM reached WHERE NOT (parsed_ok = 1 AND gate_codes = '[]')
    GROUP BY model, effort
UNION ALL
SELECT 'unavailable', model, effort, '', COUNT(*)
    FROM a1 WHERE gate_codes LIKE '%MODEL_UNAVAILABLE%'
    GROUP BY model, effort
UNION ALL
SELECT 'retries', a1.model, a1.effort, '', COUNT(*)
    FROM a1 JOIN retried USING (proposal_key)
    GROUP BY a1.model, a1.effort
UNION ALL
SELECT 'retry_passed', a1.model, a1.effort, '', COUNT(*)
    FROM a1 JOIN retried USING (proposal_key)
    JOIN proposal_results r USING (proposal_key)
    WHERE r.kind = 'proposal'
    GROUP BY a1.model, a1.effort
UNION ALL
SELECT 'model_fallbacks', a1.model, a1.effort, '', COUNT(*)
    FROM a1 JOIN proposal_results r USING (proposal_key)
    WHERE r.kind = 'fallback'
    GROUP BY a1.model, a1.effort
UNION ALL
SELECT 'model_noops', a1.model, a1.effort, '', COUNT(*)
    FROM a1 JOIN proposal_results r USING (proposal_key)
    WHERE r.kind = 'noop'
    GROUP BY a1.model, a1.effort
UNION ALL
SELECT 'code', a1.model, a1.effort, json_extract(j.value, '$.code'),
    COUNT(DISTINCT a1.proposal_key)
    FROM reached a1, json_each(a1.gate_codes) AS j
    GROUP BY a1.model, a1.effort, json_extract(j.value, '$.code')
UNION ALL
SELECT 'results', '', '', '', COUNT(*) FROM proposal_results
UNION ALL
SELECT 'proposals', '', '', '', COUNT(*) FROM proposal_results
    WHERE kind = 'proposal'
UNION ALL
SELECT 'fallbacks', '', '', '', COUNT(*) FROM proposal_results
    WHERE kind = 'fallback'
UNION ALL
SELECT 'noops', '', '', '', COUNT(*) FROM proposal_results
    WHERE kind = 'noop'
UNION ALL
SELECT 'noop_reason', '', '', j.value, COUNT(*)
    FROM proposal_results, json_each(proposal_results.reason_codes) AS j
    WHERE kind = 'noop' GROUP BY j.value
"""


@dataclass(frozen=True)
class ModelFirstDraftStats:
    """First-draft denominators per requested model and effort."""

    model: str
    effort: str
    first_drafts: int
    first_draft_passed: int
    first_draft_failed: int
    unavailable: int
    retries: int
    retry_passed: int
    fallbacks: int
    noops: int


@dataclass(frozen=True)
class CodeFirstDraftStats:
    """First drafts carrying one code at least once."""

    model: str
    effort: str
    code: str
    drafts: int


@dataclass(frozen=True)
class FirstDraftReport:
    """The R1 first-draft failure report."""

    models: tuple[ModelFirstDraftStats, ...]
    codes: tuple[CodeFirstDraftStats, ...]
    results: int
    proposals: int
    fallbacks: int
    noops: int
    noops_by_reason: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class StoredResult:
    """One recorded result read back with typed payloads."""

    profile_id: str
    subject_id: str
    cycle_id: str
    run: int
    slot: datetime
    kind: str
    briefing: Briefing | None
    fallback: FallbackProposal | None
    hour: TimeInterval | None
    reason_codes: tuple[str, ...]
    cycle_age_s: float


_SUFFIX_RE = re.compile(r"(.*)-(\d+)$")


def _base_key(key: str) -> str:
    match = _SUFFIX_RE.fullmatch(key)
    if match is not None and not match.group(1).endswith("Z"):
        return key
    if match is not None:
        return match.group(1)
    return key


class ProposalStore:
    """Append-only proposal attempts/results in the event DB file."""

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

    def _allocate_key(self, base: str) -> str:
        rows = self._conn.execute(
            "SELECT proposal_key FROM proposal_results"
        ).fetchall()
        taken = [row[0] for row in rows if _base_key(row[0]) == base]
        if not taken:
            return base
        top = 1
        for key in taken:
            match = _SUFFIX_RE.fullmatch(key)
            if match is not None and match.group(1) == base:
                top = max(top, int(match.group(2)))
        return f"{base}-{top + 1}"

    def record(self, result: ProposalResult, *, snapshot: dict[str, float]) -> str:
        """Record attempts with their result in one transaction."""
        base = (
            f"prop-{result.subject_id}-{result.profile_id}"
            f"-{result.cycle_id}-{result.run}-"
            f"{result.slot.astimezone(UTC):%Y%m%dT%H%M%SZ}"
        )
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            key = self._allocate_key(base)
            for attempt in result.attempts:
                conn.execute(
                    "INSERT INTO proposal_attempts (proposal_key, cycle_id, run,"
                    " profile_id, subject_id, slot, attempt, model_requested,"
                    " model_reported, effort, prompt_hash, raw_response,"
                    " parsed_ok, blocked, gate_codes, latency_ms, prompt_tokens,"
                    " completion_tokens, reasoning_tokens, finish_reason,"
                    " cached_tokens, transport, transport_version,"
                    " harness_rules_file)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                    " ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        result.cycle_id,
                        result.run,
                        result.profile_id,
                        result.subject_id,
                        result.slot.isoformat(),
                        attempt.number,
                        attempt.model_requested,
                        attempt.model_reported,
                        attempt.effort,
                        attempt.prompt_hash,
                        attempt.raw_text,
                        int(attempt.parsed_ok),
                        int(attempt.blocked),
                        canonical_json(
                            [
                                {"code": code, "location": location}
                                for code, location in attempt.codes
                            ]
                        ),
                        attempt.latency_ms,
                        attempt.prompt_tokens,
                        attempt.completion_tokens,
                        attempt.reasoning_tokens,
                        attempt.finish_reason,
                        attempt.cached_tokens,
                        attempt.transport,
                        attempt.transport_version,
                        (
                            None
                            if attempt.harness_rules_file is None
                            else int(attempt.harness_rules_file)
                        ),
                    ),
                )
            conn.execute(
                "INSERT INTO proposal_results (proposal_key, cycle_id, run,"
                " profile_id, subject_id, slot, kind, briefing_json,"
                " fallback_json, snapshot, hour_start, hour_end, reason_codes,"
                " cycle_age_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?)",
                (
                    key,
                    result.cycle_id,
                    result.run,
                    result.profile_id,
                    result.subject_id,
                    result.slot.isoformat(),
                    result.kind,
                    (
                        canonical_json(result.briefing.model_dump(mode="json"))
                        if result.briefing is not None
                        else None
                    ),
                    (
                        canonical_json(result.fallback.model_dump(mode="json"))
                        if result.fallback is not None
                        else None
                    ),
                    canonical_json(snapshot),
                    (
                        result.hour.start.isoformat()
                        if result.hour is not None
                        else None
                    ),
                    (result.hour.end.isoformat() if result.hour is not None else None),
                    canonical_json(list(result.reason_codes)),
                    result.cycle_age_s,
                ),
            )
            conn.execute("COMMIT")
            return key
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def latest_proposal(
        self, subject_id: str, profile_id: str, *, before_slot: datetime
    ) -> tuple[Briefing, MetricSnapshot, datetime] | None:
        """Latest proposal strictly before the slot; fallbacks never qualify."""
        rows = self._conn.execute(
            "SELECT rowid, slot, briefing_json, snapshot FROM proposal_results"
            " WHERE subject_id = ? AND profile_id = ? AND kind = 'proposal'",
            (subject_id, profile_id),
        ).fetchall()
        best: tuple[Any, ...] | None = None
        for rowid, slot_text, briefing_json, snapshot_text in rows:
            slot = datetime.fromisoformat(slot_text)
            if not slot < before_slot:
                continue
            if best is None or (slot, rowid) > (best[0], best[1]):
                best = (slot, rowid, briefing_json, snapshot_text)
        if best is None:
            return None
        slot, _, briefing_json, snapshot_text = best
        return (
            Briefing.model_validate(json.loads(briefing_json)),
            MetricSnapshot(values=json.loads(snapshot_text)),
            slot,
        )

    def last_offered_by_commitment(
        self, subject_id: str, profile_id: str
    ) -> dict[str, datetime]:
        """Latest offered slot per commitment over proposals and fallbacks."""
        rows = self._conn.execute(
            "SELECT rowid, proposal_key, slot, kind, briefing_json, fallback_json"
            " FROM proposal_results WHERE subject_id = ? AND profile_id = ?"
            " AND kind IN ('proposal', 'fallback') ORDER BY rowid",
            (subject_id, profile_id),
        ).fetchall()
        latest: dict[str, tuple[int, str, str, str, str]] = {}
        for rowid, key, slot_text, kind, briefing_json, fallback_json in rows:
            latest[_base_key(key)] = (
                rowid,
                slot_text,
                kind,
                briefing_json,
                fallback_json,
            )
        offered: dict[str, datetime] = {}
        for _, slot_text, kind, briefing_json, fallback_json in latest.values():
            slot = datetime.fromisoformat(slot_text)
            if kind == "proposal":
                briefing = Briefing.model_validate(json.loads(briefing_json))
                commitment_ids = [
                    action.commitment_id
                    for section in briefing.sections
                    for action in section.actions
                ]
            else:
                fallback = FallbackProposal.model_validate(json.loads(fallback_json))
                commitment_ids = [fallback.commitment.id]
            for commitment_id in commitment_ids:
                if commitment_id not in offered or slot > offered[commitment_id]:
                    offered[commitment_id] = slot
        return offered

    def results_for_slot(
        self, subject_id: str, slot: datetime
    ) -> tuple[StoredResult, ...]:
        """Latest recorded row per profile at one slot instant."""
        rows = self._conn.execute(
            "SELECT rowid, proposal_key, cycle_id, run, profile_id, slot, kind,"
            " briefing_json, fallback_json, hour_start, hour_end, reason_codes,"
            " cycle_age_s FROM proposal_results WHERE subject_id = ?",
            (subject_id,),
        ).fetchall()
        latest: dict[str, tuple[Any, ...]] = {}
        for row in rows:
            rowid = row[0]
            row_slot = datetime.fromisoformat(row[5])
            if row_slot != slot:
                continue
            profile_id = row[4]
            if profile_id not in latest or rowid > latest[profile_id][0]:
                latest[profile_id] = row
        results: list[StoredResult] = []
        for profile_id in sorted(latest):
            (
                _,
                _key,
                cycle_id,
                run,
                _profile,
                slot_text,
                kind,
                briefing_json,
                fallback_json,
                hour_start,
                hour_end,
                reason_codes,
                cycle_age_s,
            ) = latest[profile_id]
            hour = (
                TimeInterval(
                    start=datetime.fromisoformat(hour_start),
                    end=datetime.fromisoformat(hour_end),
                )
                if hour_start is not None and hour_end is not None
                else None
            )
            results.append(
                StoredResult(
                    profile_id=profile_id,
                    subject_id=subject_id,
                    cycle_id=cycle_id,
                    run=run,
                    slot=datetime.fromisoformat(slot_text),
                    kind=kind,
                    briefing=(
                        Briefing.model_validate(json.loads(briefing_json))
                        if briefing_json is not None
                        else None
                    ),
                    fallback=(
                        FallbackProposal.model_validate(json.loads(fallback_json))
                        if fallback_json is not None
                        else None
                    ),
                    hour=hour,
                    reason_codes=tuple(json.loads(reason_codes)),
                    cycle_age_s=cycle_age_s,
                )
            )
        return tuple(results)

    def first_draft_report(self) -> FirstDraftReport:
        """The R1 first-draft failure report from named SQL."""
        rows = self._conn.execute(FIRST_DRAFT_REPORT_SQL).fetchall()
        per: dict[tuple[str, str], dict[str, int]] = {}
        codes: dict[tuple[str, str, str], int] = {}
        totals = {"results": 0, "proposals": 0, "fallbacks": 0, "noops": 0}
        noop_reasons: dict[str, int] = {}

        def _entry(model: str, effort: str) -> dict[str, int]:
            key = (model, effort)
            if key not in per:
                per[key] = {
                    "first_drafts": 0,
                    "first_passed": 0,
                    "first_failed": 0,
                    "unavailable": 0,
                    "retries": 0,
                    "retry_passed": 0,
                    "fallbacks": 0,
                    "noops": 0,
                }
            return per[key]

        for grain, model, effort, code, count in rows:
            if grain in (
                "first_drafts",
                "first_passed",
                "first_failed",
                "unavailable",
                "retries",
                "retry_passed",
                "model_fallbacks",
                "model_noops",
            ):
                key = {
                    "first_drafts": "first_drafts",
                    "first_passed": "first_passed",
                    "first_failed": "first_failed",
                    "unavailable": "unavailable",
                    "retries": "retries",
                    "retry_passed": "retry_passed",
                    "model_fallbacks": "fallbacks",
                    "model_noops": "noops",
                }[grain]
                _entry(model, effort)[key] = int(count)
            elif grain == "code":
                codes[(model, effort, code)] = int(count)
            elif grain in totals:
                totals[grain] = int(count)
            elif grain == "noop_reason":
                noop_reasons[code] = int(count)
        return FirstDraftReport(
            models=tuple(
                ModelFirstDraftStats(
                    model=model,
                    effort=effort,
                    first_drafts=entry["first_drafts"],
                    first_draft_passed=entry["first_passed"],
                    first_draft_failed=entry["first_failed"],
                    unavailable=entry["unavailable"],
                    retries=entry["retries"],
                    retry_passed=entry["retry_passed"],
                    fallbacks=entry["fallbacks"],
                    noops=entry["noops"],
                )
                for (model, effort), entry in sorted(per.items())
            ),
            codes=tuple(
                CodeFirstDraftStats(model=model, effort=effort, code=code, drafts=n)
                for (model, effort, code), n in sorted(codes.items())
            ),
            results=totals["results"],
            proposals=totals["proposals"],
            fallbacks=totals["fallbacks"],
            noops=totals["noops"],
            noops_by_reason=tuple(sorted(noop_reasons.items())),
        )
