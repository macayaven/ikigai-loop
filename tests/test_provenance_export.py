"""Ticket 22: export tests. Made-up data only, loopback never touched here.

Each test names the removal that makes it fail in its docstring.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.schemas import Briefing
from framework.cycle.card_build import build_statements
from framework.provenance.export import _connect, main
from framework.provenance.schemas import OTHER_CODE, ProvenanceLine

MADRID = ZoneInfo("Europe/Madrid")
UTC = ZoneInfo("UTC")
SUBJECT = "subject-a"

SLOT1 = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
SLOT2 = datetime(2026, 11, 2, 18, 0, tzinfo=MADRID)
SLOT1_UTC = "2026-11-02T14:30:00+00:00"
SLOT1_LOCAL = "2026-11-02T15:30:00+01:00"
SLOT2_UTC = "2026-11-02T17:00:00+00:00"
SLOT2_LOCAL = "2026-11-02T18:00:00+01:00"


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _briefing_json(
    profile: str,
    slot_local: str,
    claims: list[dict[str, Any]],
    *,
    briefing_id: str = "brf-1",
) -> str:
    briefing = Briefing.model_validate(
        {
            "id": briefing_id,
            "profile_id": profile,
            "subject_id": SUBJECT,
            "slot": slot_local,
            "sections": [
                {"type": "overall_state", "claims": claims},
                {"type": "actions", "claims": []},
            ],
        }
    )
    return json.dumps(briefing.model_dump(mode="json"), sort_keys=True)


def _claim(
    cid: str,
    text: str,
    facts: list[str] | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": cid,
        "text": text,
        "fact_ids": facts or [],
        "metric_refs": [{"metric_id": mid, "value": 1.0} for mid in (metrics or [])],
    }


def _passes_json(
    personal_attempts: int = 1,
    feed_attempts: int = 1,
    *,
    personal_model: str = "glimmer-30b",
    feed_model: str = "glimmer-30b",
) -> str:
    return json.dumps(
        [
            {
                "name": "personal",
                "attempts": personal_attempts,
                "raw_valid": True,
                "model_id": personal_model,
                "latency_ms": 111,
                "finish_reason": "stop",
                "completion_tokens": 21,
                "kept": 1 if personal_attempts else 0,
                "noop_reason": None if personal_attempts else "NOOP_NO_PERSONAL_EVENTS",
            },
            {
                "name": "feed",
                "attempts": feed_attempts,
                "raw_valid": True,
                "model_id": feed_model,
                "latency_ms": 222,
                "finish_reason": "stop",
                "completion_tokens": 33,
                "kept": 1 if feed_attempts else 0,
                "noop_reason": None if feed_attempts else "NOOP_NO_FEED_ITEMS",
            },
        ]
    )


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=DELETE")
    return conn


def _base_tables(db: Path) -> None:
    """Real DDL from the real constructors on a temp path."""
    from framework.cycle.slot_ledger import DDL as SLOT_DDL
    from framework.cycle.slot_ledger import SlotLedger
    from framework.store.fact_store import DDL as FACT_DDL
    from framework.store.fact_store import FactStore
    from framework.store.proposal_store import DDL as PROPOSAL_DDL
    from framework.store.proposal_store import ProposalStore
    from framework.store.store import DDL as STORE_DDL
    from framework.store.store import EventStore
    from framework.telegram.ledger import LEDGER_DDL, VOICE_NOTES_DDL

    EventStore(db_path=db).close()
    FactStore(db_path=db).close()
    ProposalStore(db_path=db).close()
    SlotLedger(db)  # owns the ledger DDL; construction alone writes nothing
    conn = sqlite3.connect(db)
    try:
        # The same DDL strings the constructors run on first use.
        conn.executescript(STORE_DDL)
        conn.executescript(FACT_DDL)
        conn.executescript(PROPOSAL_DDL)
        conn.executescript(SLOT_DDL)
        conn.executescript(LEDGER_DDL)
        conn.executescript(VOICE_NOTES_DDL)
        conn.commit()
    finally:
        conn.close()


def _text_columns(conn: sqlite3.Connection) -> dict[str, list[str]]:
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    found: dict[str, list[str]] = {}
    for table in tables:
        cols = [
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            if str(row[2]).upper() == "TEXT"
        ]
        found[table] = cols
    return found


# Canary shapes: low-entropy plain words, so gitleaks has nothing to flag.
FREE = "quiet canary meadow"
WORD = "quiescent"
CODE = "ZEFFYR"
TS = "2049-06-07T08:09:10+02:00"
# Join keys carry the same canary on both sides of the join: they join on
# equal text and never print, so counts stay non-zero while nothing escapes.
CARD1 = "quiet canary card one"
CARD2 = "quiet canary card two"
KEY1A = "quiet canary key alpha"
KEY1B = "quiet canary key beta"
KEY2 = "quiet canary key gamma"
CYCLE1 = "quiet canary cycle one"
CYCLE2 = "quiet canary cycle two"
FACT1 = "quiet canary fact one"
FACT2 = "quiet canary fact two"
FACT2B = "quiet canary fact three"
CLAIM1 = "quiet canary claim one"
CLAIM2 = "quiet canary claim two"
METRIC1 = "quiet canary metric one"
ACTION1 = "quiet canary action one"
COMMIT1 = "quiet canary commitment one"

# Only the slot columns stay exempt, because they must parse as instants.
# Every other column that can carry one gets a canary: join keys are fine
# as canaries, because they join on equal text and never print.
EXEMPT: dict[str, str] = {
    "slot_ledger.slot": "slot instant join, must parse",
    "slot_cards.slot": "slot instant join, must parse",
    "proposal_results.slot": "slot instant join, must parse",
    "local_start_retries.slot": "slot instant join, must parse",
    "voice_notes.slot": "slot instant join, must parse",
}


def _canary_shapes() -> list[str]:
    return [FREE, WORD, CODE, TS]


def _canary_briefing(profile: str, slot_local: str, fact_a: str, fact_b: str) -> str:
    """A valid briefing whose leaves carry canaries: claim ids and text,
    one action's text and commitment id, fact ids and one metric id."""
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID).isoformat()
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID).isoformat()
    briefing = Briefing.model_validate(
        {
            "id": "quiet canary briefing one",
            "profile_id": profile,
            "subject_id": SUBJECT,
            "slot": slot_local,
            "sections": [
                {
                    "type": "overall_state",
                    "claims": [
                        {
                            "id": CLAIM1,
                            "text": f"First claim on {FREE}.",
                            "fact_ids": [fact_a],
                            "metric_refs": [{"metric_id": METRIC1, "value": 1.0}],
                        },
                        {
                            "id": CLAIM2,
                            "text": f"Second claim on {FREE}.",
                            "fact_ids": [fact_b],
                        },
                    ],
                },
                {
                    "type": "actions",
                    "claims": [],
                    "actions": [
                        {
                            "id": ACTION1,
                            "commitment_id": COMMIT1,
                            "kind": "build",
                            "text": f"Act on {FREE}.",
                            "dimension": "love",
                            "proposed_start": start,
                            "proposed_end": end,
                        }
                    ],
                },
            ],
        }
    )
    return json.dumps(briefing.model_dump(mode="json"), sort_keys=True)


def _seed_canary_db(db: Path) -> list[str]:
    """Two made-up slots with a canary in every non-exempt TEXT column.

    Slot 1 drives the real flow with real closed words; slot 2 carries
    canaries in the closed columns too, which must map to the fixed
    words. Returns every canary planted, so the test can assert none
    escapes.
    """
    _base_tables(db)
    conn = _open(db)
    planted = [
        FREE,
        WORD,
        CODE,
        TS,
        CARD1,
        CARD2,
        KEY1A,
        KEY1B,
        KEY2,
        CYCLE1,
        CYCLE2,
        FACT1,
        FACT2,
        FACT2B,
        CLAIM1,
        CLAIM2,
        METRIC1,
        ACTION1,
        COMMIT1,
    ]
    try:
        detail1 = f"as_of={TS} cycle={CYCLE1} start={FREE} end={FREE} message_id={FREE}"
        briefing1 = _canary_briefing("builder", SLOT1_LOCAL, FACT1, FACT2)
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'start', 'ok', 0.1, NULL, ?)",
            (SLOT1_UTC, detail1),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'facts_model', 'ok', 0.2, NULL, ?)",
            (SLOT1_UTC, detail1),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'card', 'ok', 0.3, ?, ?)",
            (SLOT1_UTC, CARD1, detail1),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'send_intent', 'intent', 0.4, ?, ?)",
            (SLOT1_UTC, CARD1, detail1),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'send', 'delivered', 0.5, ?, ?)",
            (SLOT1_UTC, CARD1, detail1),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'done', 'delivered', 0.6, ?, ?)",
            (SLOT1_UTC, CARD1, detail1),
        )
        for letter, profile in (("A", "builder"), ("B", "disconnect")):
            conn.execute(
                "INSERT INTO slot_cards (card_id, letter, slot, subject_id,"
                " as_of, bucket, profile_id, commitment_id, kind, policy_pick,"
                " policy_alternative) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    CARD1,
                    letter,
                    SLOT1_UTC,
                    FREE,
                    TS,
                    FREE,
                    profile,
                    FREE,
                    "proposal",
                    FREE,
                    FREE,
                ),
            )
        conn.execute(
            "INSERT INTO slot_card_payloads (card_id, card_json, chart_json)"
            " VALUES (?, ?, ?)",
            (FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO learner_states (slot, state_json) VALUES (?, ?)",
            (FREE, FREE),
        )
        conn.execute(
            "INSERT INTO local_start_retries (slot, profile, try, reason,"
            " latency_ms, exit_code, stderr) VALUES (?, 'builder', 1, ?, 5,"
            " NULL, ?)",
            (SLOT1_UTC, FREE, FREE),
        )
        for key, profile in ((KEY1A, "builder"), (KEY1B, "disconnect")):
            conn.execute(
                "INSERT INTO proposal_results (proposal_key, cycle_id, run,"
                " profile_id, subject_id, slot, kind, briefing_json,"
                " fallback_json, snapshot, hour_start, hour_end, reason_codes,"
                " cycle_age_s) VALUES (?, ?, 1, ?, ?, ?, 'proposal', ?, ?, ?,"
                " ?, ?, ?, 1.0)",
                (
                    key,
                    CYCLE1,
                    profile,
                    FREE,
                    SLOT1_LOCAL,
                    briefing1,
                    FREE,
                    FREE,
                    TS,
                    TS,
                    json.dumps([CODE]),
                ),
            )
        gate_codes = json.dumps([{"code": CODE, "location": FREE}])
        for key, profile in ((KEY1A, "builder"), (KEY1B, "disconnect")):
            conn.execute(
                "INSERT INTO proposal_attempts (proposal_key, cycle_id, run,"
                " profile_id, subject_id, slot, attempt, model_requested,"
                " model_reported, effort, prompt_hash, raw_response, parsed_ok,"
                " blocked, gate_codes, latency_ms, prompt_tokens,"
                " completion_tokens, reasoning_tokens, finish_reason,"
                " cached_tokens, transport, transport_version,"
                " harness_rules_file) VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?,"
                " 'low', ?, ?, 1, 0, ?, 4242, 11, 22, 33, 'stop', 0, 'muse',"
                " 'Muse Code 1.4.14 (1.4.14-R7309.1)', NULL)",
                (
                    key,
                    CYCLE1,
                    profile,
                    FREE,
                    FREE,
                    f"/tmp/{FREE}/wonder-1",
                    f"/tmp/{FREE}/wonder-1",
                    FREE,
                    FREE,
                    gate_codes,
                ),
            )
        passes = json.dumps(
            [
                {
                    "name": "personal",
                    "attempts": 1,
                    "raw_valid": True,
                    "model_id": f"/tmp/{FREE}/glimmer-30b",
                    "latency_ms": 777,
                    "finish_reason": "stop",
                    "completion_tokens": 44,
                    "kept": 2,
                    "noop_reason": None,
                },
                {
                    "name": "feed",
                    "attempts": 0,
                    "raw_valid": False,
                    "model_id": "",
                    "latency_ms": 0,
                    "finish_reason": None,
                    "completion_tokens": None,
                    "kept": 0,
                    "noop_reason": "NOOP_FEED_SKIPPED",
                },
            ]
        )
        conn.execute(
            "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
            " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason,"
            " snapshot, passes, dropped_codes, kept_count, dropped_count)"
            " VALUES (?, 1, ?, ?, ?, ?, 9, 1, 0, ?, ?, ?, ?, 2, 0)",
            (
                CYCLE1,
                FREE,
                TS,
                FREE,
                FREE,
                FREE,
                FREE,
                passes,
                json.dumps([CODE]),
            ),
        )
        for fid, origin in ((FACT1, "model"), (FACT2, "code")):
            conn.execute(
                "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
                " window_start, window_end, statement, evidence, tier, origin)"
                " VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'public', ?)",
                (
                    CYCLE1,
                    fid,
                    FREE,
                    TS,
                    TS,
                    f"Statement on {FREE}.",
                    FREE,
                    origin,
                ),
            )
        # Slot 2: the same file carries canaries in the closed columns as
        # well, and they must map to the fixed words.
        detail2 = f"as_of={TS} cycle={CYCLE2} start={FREE} end={FREE} message_id={FREE}"
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, ?, ?, 0.1, NULL, ?)",
            (SLOT2_UTC, WORD, CODE, detail2),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, 'card', ?, 0.2, ?, ?)",
            (SLOT2_UTC, CODE, CARD2, detail2),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, ?, ?, 0.3, ?, ?)",
            (SLOT2_UTC, WORD, CODE, CARD2, detail2),
        )
        conn.execute(
            "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id,"
            " detail) VALUES (?, ?, ?, 0.4, ?, ?)",
            (SLOT2_UTC, WORD, CODE, CARD2, detail2),
        )
        conn.execute(
            "INSERT INTO slot_cards (card_id, letter, slot, subject_id,"
            " as_of, bucket, profile_id, commitment_id, kind, policy_pick,"
            " policy_alternative) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (CARD2, WORD, SLOT2_UTC, FREE, TS, FREE, WORD, FREE, WORD, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO local_start_retries (slot, profile, try, reason,"
            " latency_ms, exit_code, stderr) VALUES (?, ?, 1, ?, 5, NULL, ?)",
            (SLOT2_UTC, WORD, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO proposal_results (proposal_key, cycle_id, run,"
            " profile_id, subject_id, slot, kind, briefing_json, fallback_json,"
            " snapshot, hour_start, hour_end, reason_codes, cycle_age_s)"
            " VALUES (?, ?, 1, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, 1.0)",
            (
                KEY2,
                CYCLE2,
                WORD,
                FREE,
                SLOT2_LOCAL,
                WORD,
                FREE,
                FREE,
                TS,
                TS,
                json.dumps([CODE]),
            ),
        )
        gate2 = json.dumps([{"code": CODE, "location": FREE}])
        conn.execute(
            "INSERT INTO proposal_attempts (proposal_key, cycle_id, run,"
            " profile_id, subject_id, slot, attempt, model_requested,"
            " model_reported, effort, prompt_hash, raw_response, parsed_ok,"
            " blocked, gate_codes, latency_ms, prompt_tokens,"
            " completion_tokens, reasoning_tokens, finish_reason,"
            " cached_tokens, transport, transport_version,"
            " harness_rules_file) VALUES (?, ?, 1, ?, ?, ?, 1, ?, ?, ?, ?, ?,"
            " 1, 0, ?, 5151, 11, 22, 33, ?, 0, ?, ?, NULL)",
            (
                KEY2,
                CYCLE2,
                WORD,
                FREE,
                FREE,
                f"/tmp/{FREE}/wonder-1",
                f"/tmp/{FREE}/wonder-1",
                WORD,
                FREE,
                FREE,
                gate2,
                WORD,
                WORD,
                WORD,
            ),
        )
        passes2 = json.dumps(
            [
                {
                    "name": WORD,
                    "attempts": 1,
                    "raw_valid": True,
                    "model_id": f"/tmp/{FREE}/glimmer-30b",
                    "latency_ms": 5151,
                    "finish_reason": WORD,
                    "completion_tokens": 44,
                    "kept": 2,
                    "noop_reason": None,
                },
                {
                    "name": WORD,
                    "attempts": 0,
                    "raw_valid": False,
                    "model_id": "",
                    "latency_ms": 0,
                    "finish_reason": WORD,
                    "completion_tokens": None,
                    "kept": 0,
                    "noop_reason": CODE,
                },
            ]
        )
        conn.execute(
            "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
            " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason,"
            " snapshot, passes, dropped_codes, kept_count, dropped_count)"
            " VALUES (?, 1, ?, ?, ?, ?, 9, 1, 0, ?, ?, ?, ?, 2, 0)",
            (
                CYCLE2,
                FREE,
                TS,
                FREE,
                FREE,
                CODE,
                FREE,
                passes2,
                json.dumps([CODE]),
            ),
        )
        conn.execute(
            "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
            " window_start, window_end, statement, evidence, tier, origin)"
            " VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
            (CYCLE2, FACT2B, FREE, TS, TS, f"Statement on {FREE}.", FREE, WORD, WORD),
        )
        # Tables the export never reads still prove they are not selected.
        conn.execute(
            "INSERT INTO cycle_responses (cycle_id, run, pass, attempt, content)"
            " VALUES (?, 1, ?, 1, ?)",
            (CYCLE1, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO events (id, subject_id, source, type, time, source_id,"
            " data, tier, collected_at, collector_version) VALUES (?, ?, ?, ?,"
            " ?, ?, ?, ?, ?, ?)",
            (FREE, FREE, FREE, FREE, FREE, FREE, FREE, FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO cursors (name, cursor, updated_at) VALUES (?, ?, ?)",
            (FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO batch_hashes (day, subject_id, hash, event_count,"
            " computed_at) VALUES (?, ?, ?, 1, ?)",
            (FREE, FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO conflicts (detected_at, source, source_id,"
            " stored_json, incoming_json) VALUES (?, ?, ?, ?, ?)",
            (FREE, FREE, FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO telegram_cards (card_id, card_json, created_at)"
            " VALUES (?, ?, ?)",
            (FREE, FREE, FREE),
        )
        conn.execute(
            "INSERT INTO telegram_voice_arrivals (message_id, received_at,"
            " duration_s) VALUES (7, ?, 3)",
            (FREE,),
        )
        conn.execute(
            "INSERT INTO voice_notes (message_id, file_id, file_unique_id,"
            " mime_type, received_at, status, next_attempt_at,"
            " first_claimed_at, applied_at, slot, matched_card_id,"
            " transcript, operation, commitment_id, until_value, question,"
            " validation_codes, new_card_id, outcome, step_seconds, total_s,"
            " compile_model, compile_effort, muse_version) VALUES (11, ?, ?,"
            " ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?)",
            (
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                SLOT1_UTC,
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                FREE,
                CARD1,
                FREE,
                FREE,
                1.5,
                FREE,
                FREE,
                FREE,
            ),
        )
        conn.execute(
            "INSERT INTO voice_notes (message_id, slot, status, operation)"
            " VALUES (12, ?, ?, 'done')",
            (SLOT2_UTC, FREE),
        )
        conn.execute(
            "INSERT INTO telegram_card_messages (message_id, card_id,"
            " sent_at) VALUES (9, ?, ?)",
            (FREE, FREE),
        )
        conn.execute(
            "INSERT INTO telegram_card_charts (card_id, chart_json,"
            " created_at) VALUES (?, ?, ?)",
            (FREE, FREE, FREE),
        )
        conn.commit()
    finally:
        conn.close()
    # The meta-check stays: every non-exempt TEXT column holds a canary.
    assert len(EXEMPT) <= 8, EXEMPT
    check = _open(db)
    try:
        live = _text_columns(check)
        for table, names in live.items():
            for column in names:
                key = f"{table}.{column}"
                if key in EXEMPT:
                    continue
                rows = check.execute(f'SELECT "{column}" FROM "{table}"').fetchall()
                texts = [str(row[0]) for row in rows if row[0] is not None]
                assert any(
                    canary.lower() in text.lower()
                    for canary in planted
                    for text in texts
                ), key
    finally:
        check.close()
    return planted


def _run(
    db: Path,
    *extra: str,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    code = main(["--db", str(db), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def _lines(stdout: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return [dict(row) for row in rows]


def test_canary_no_private_text_escapes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing the allowlist (selecting a canary column) makes it fail."""
    db = tmp_path / "canary.db"
    planted = _seed_canary_db(db)
    assert planted
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    assert set(rows) == {SLOT1_LOCAL, SLOT2_LOCAL}
    first = rows[SLOT1_LOCAL]
    # The line proves the export read those rows: attempt and pass latency
    # plus non-zero cited counts survive, while no canary escapes.
    assert first["sides"][0]["attempts"][0]["latency_ms"] == 4242
    assert first["sides"][0]["cycle"]["passes"][0]["latency_ms"] == 777
    assert first["sides"][0]["metrics_cited"] == 1
    assert first["facts_cited"] == {"code": 1, "model": 1, "unknown": 0}
    assert first["sides"][0]["cycle"]["passes"][0]["noop_reason"] == "none"
    # The closed voice note reads as one entry with a mapped operation;
    # the open slot-2 note stays out.
    assert first["voice_notes"] == [
        {"operation": "unknown", "new_card_sent": True, "latency_ms": 1500}
    ]
    assert rows[SLOT2_LOCAL]["voice_notes"] == []
    second = rows[SLOT2_LOCAL]
    # The closed-column canaries map to the fixed words.
    assert second["delivery"] == "not_sent"
    assert second["final_code"] == OTHER_CODE
    side = second["sides"][0]
    assert side["letter"] == "unknown"
    assert side["profile"] == "unknown"
    assert side["kind"] == "unknown"
    assert side["reason_codes"] == [OTHER_CODE]
    assert side["attempts"][0]["effort"] == "unknown"
    assert side["attempts"][0]["transport"] == "unknown"
    assert side["attempts"][0]["muse_version"] == "unknown"
    assert side["cycle"]["dropped_codes"] == [OTHER_CODE]
    personal, feed = side["cycle"]["passes"]
    assert personal["name"] == "unknown"
    assert personal["finish_reason"] == "unknown"
    assert personal["noop_reason"] == "none"
    assert feed["noop_reason"] == OTHER_CODE
    blob = stdout + stderr
    lowered = blob.lower()
    for canary in planted:
        assert canary.lower() not in lowered, canary
    assert TS not in blob
    assert "1.4.14" in stdout  # the harmless version basename survives
    # Every timestamp-looking string equals the line's slot, date and time.
    import re

    for row in rows.values():
        slot = datetime.fromisoformat(str(row["slot"]))
        text = json.dumps(row)
        for found in re.findall(r"\d{4}-\d{2}-\d{2}", text):
            assert found == slot.date().isoformat(), found
        for found in re.findall(r"\b\d{2}:\d{2}:\d{2}\b", text):
            assert found == slot.time().isoformat(), found
    target = tmp_path / "out.jsonl"
    code, _, stderr = _run(db, "--out", str(target), capsys=capsys)
    assert code == 0, stderr
    body = target.read_text()
    assert _lines(body) == _lines(stdout)
    for canary in planted:
        assert canary.lower() not in body.lower(), canary
    assert TS not in body


def _mini_db(db: Path) -> sqlite3.Connection:
    _base_tables(db)
    return _open(db)


def _ledger(
    conn: sqlite3.Connection,
    slot_utc: str,
    step: str,
    outcome: str,
    card: str | None = None,
    detail: str = "",
) -> None:
    conn.execute(
        "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id, detail)"
        " VALUES (?, ?, ?, 0.1, ?, ?)",
        (slot_utc, step, outcome, card, detail),
    )


def _side_row(
    conn: sqlite3.Connection,
    card: str,
    letter: str,
    slot_utc: str,
    profile: str,
    kind: str,
) -> None:
    conn.execute(
        "INSERT INTO slot_cards (card_id, letter, slot, subject_id, as_of,"
        " bucket, profile_id, commitment_id, kind, policy_pick,"
        " policy_alternative) VALUES (?, ?, ?, ?, ?, NULL, ?, 'c-1', ?, NULL,"
        " NULL)",
        (card, letter, slot_utc, SUBJECT, slot_utc, profile, kind),
    )


def _result(
    conn: sqlite3.Connection,
    key: str,
    cycle: str,
    run: int,
    profile: str,
    slot_local: str,
    kind: str,
    briefing: str | None,
    codes: list[str],
) -> None:
    conn.execute(
        "INSERT INTO proposal_results (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, kind, briefing_json, fallback_json, snapshot,"
        " hour_start, hour_end, reason_codes, cycle_age_s) VALUES (?, ?, ?, ?,"
        " ?, ?, ?, ?, NULL, '{}', NULL, NULL, ?, 1.0)",
        (
            key,
            cycle,
            run,
            profile,
            SUBJECT,
            slot_local,
            kind,
            briefing,
            json.dumps(codes),
        ),
    )


def _attempt(
    conn: sqlite3.Connection,
    key: str,
    *,
    requested: str = "wonder-1",
    reported: str = "wonder-1",
    transport: str = "muse",
    version: str | None = "Muse Code 1.4.14 (1.4.14-R7309.1)",
    effort: str = "low",
    latency: int = 9,
    prompt_tokens: int | None = 3,
    completion_tokens: int | None = 5,
    reasoning_tokens: int | None = 7,
    cached_tokens: int | None = 0,
    finish: str | None = "stop",
    codes: list[dict[str, str]] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO proposal_attempts (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, attempt, model_requested, model_reported, effort,"
        " prompt_hash, raw_response, parsed_ok, blocked, gate_codes, latency_ms,"
        " prompt_tokens, completion_tokens, reasoning_tokens, finish_reason,"
        " cached_tokens, transport, transport_version, harness_rules_file)"
        " VALUES (?, 'cycle-1', 1, 'builder', ?, ?, 1, ?, ?, ?, 'ph', 'raw', 1,"
        " 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (
            key,
            SUBJECT,
            SLOT1_LOCAL,
            requested,
            reported,
            effort,
            json.dumps(codes or []),
            latency,
            prompt_tokens,
            completion_tokens,
            reasoning_tokens,
            finish,
            cached_tokens,
            transport,
            version,
        ),
    )


def _cycle(
    conn: sqlite3.Connection,
    cycle: str,
    run: int,
    passes: str,
    dropped: list[str] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
        " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason, snapshot,"
        " passes, dropped_codes, kept_count, dropped_count) VALUES (?, ?, 's',"
        " 'a', 'm', 'p', 1, 1, 0, NULL, '{}', ?, ?, 1, 0)",
        (cycle, run, passes, json.dumps(dropped or [])),
    )


def _fact(
    conn: sqlite3.Connection,
    cycle: str,
    run: int,
    fid: str,
    origin: str,
    tier: str = "public",
) -> None:
    conn.execute(
        "INSERT INTO facts (cycle_id, run, fact_id, subject_id, window_start,"
        " window_end, statement, evidence, tier, origin) VALUES (?, ?, ?, 's',"
        " 'a', 'b', 'st', '[]', ?, ?)",
        (cycle, run, fid, tier, origin),
    )


def _card_slot(
    conn: sqlite3.Connection,
    *,
    slot_utc: str = SLOT1_UTC,
    slot_local: str = SLOT1_LOCAL,
    delivery: str = "delivered",
    card: str = "card-1",
    briefing: str | None = None,
    passes: str | None = None,
) -> None:
    """One delivered two-sided card over a model cycle citing f1/f2."""
    _ledger(conn, slot_utc, "start", "ok")
    _ledger(conn, slot_utc, "facts_model", "ok", None, "cycle=cycle-1")
    _ledger(conn, slot_utc, "card", "ok", card, "codes=-")
    if delivery != "not_sent":
        _ledger(conn, slot_utc, "send_intent", "intent", card, "message_id=11")
        if delivery != "intent_open":
            _ledger(conn, slot_utc, "send", delivery, card, "message_id=11")
    _ledger(conn, slot_utc, "done", delivery, card)
    for letter, profile in (("A", "builder"), ("B", "disconnect")):
        _side_row(conn, card, letter, slot_utc, profile, "proposal")
    body = briefing or _briefing_json(
        "builder",
        slot_local,
        [_claim("c1", "First claim.", ["f1"]), _claim("c2", "Second.", ["f2"])],
    )
    for key, profile in (("key-1", "builder"), ("key-2", "disconnect")):
        _result(conn, key, "cycle-1", 1, profile, slot_local, "proposal", body, [])
        _attempt(conn, key)
    _cycle(conn, "cycle-1", 1, passes or _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "model")
    _fact(conn, "cycle-1", 1, "f2", "code")


def _seed_zero(
    db: Path, *, null_tokens: bool = False, bad_briefing: bool = False
) -> None:
    conn = _mini_db(db)
    # Code-only cycle: no pass ran, so origin is code and model is a real 0.
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Code claim.", ["f9"])])
    if bad_briefing:
        body = "not json"
    _result(conn, "key-1", "cycle-9", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _attempt(conn, "key-1")
    _cycle(conn, "cycle-9", 1, _passes_json(0, 0))
    _fact(conn, "cycle-9", 1, "f9", "code")
    # Model cycle citing only code facts: origin model, model cited is 0,
    # and model was available.
    _ledger(conn, SLOT2_UTC, "start", "ok")
    _ledger(conn, SLOT2_UTC, "card", "ok", "card-2", "codes=-")
    _ledger(conn, SLOT2_UTC, "done", "delivered", "card-2")
    _side_row(conn, "card-2", "A", SLOT2_UTC, "builder", "proposal")
    body2 = _briefing_json(
        "builder", SLOT2_LOCAL, [_claim("c1", "Code claim.", ["f8"])]
    )
    _result(conn, "key-9", "cycle-8", 1, "builder", SLOT2_LOCAL, "proposal", body2, [])
    if null_tokens:
        _attempt(
            conn,
            "key-9",
            prompt_tokens=None,
            completion_tokens=None,
            reasoning_tokens=None,
            cached_tokens=None,
        )
    else:
        _attempt(conn, "key-9")
    _cycle(conn, "cycle-8", 1, _passes_json(1, 0))
    _fact(conn, "cycle-8", 1, "f8", "code")
    _fact(conn, "cycle-8", 1, "f7", "model")
    conn.commit()
    conn.close()


def test_honest_zero_and_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing 0 for missing counts (or vice versa) makes it fail."""
    db = tmp_path / "zero.db"
    _seed_zero(db)
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    code_only = rows[SLOT1_LOCAL]
    assert code_only["cycle_origin"] == "code"
    assert code_only["facts_cited"] == {"code": 1, "model": 0, "unknown": 0}
    assert code_only["sides"][0]["facts_cited"]["model"] == 0
    model_side = rows[SLOT2_LOCAL]
    assert model_side["cycle_origin"] == "model"
    assert model_side["facts_cited"] == {"code": 1, "model": 0, "unknown": 0}
    assert model_side["sides"][0]["cycle"]["facts_available"]["model"] == 1
    # NULL tokens print unknown, never 0.
    assert model_side["sides"][0]["attempts"] != "unknown"
    for attempt in model_side["sides"][0]["attempts"]:
        assert attempt["prompt_tokens"] == 3
    null_db = tmp_path / "nulltokens.db"
    _seed_zero(null_db, null_tokens=True)
    code, stdout, stderr = _run(null_db, capsys=capsys)
    assert code == 0, stderr
    got = {row["slot"]: row for row in _lines(stdout)}
    attempt = got[SLOT2_LOCAL]["sides"][0]["attempts"][0]
    assert attempt["prompt_tokens"] == "unknown"
    assert attempt["completion_tokens"] == "unknown"
    assert attempt["reasoning_tokens"] == "unknown"
    assert attempt["cached_tokens"] == "unknown"
    # A missing facts table, a missing origin column and an unparseable
    # briefing each give unknown, never 0.
    for db2, op in (
        ("nofacts.db", "drop"),
        ("noorigin.db", "col"),
        ("badbrief.db", "brief"),
    ):
        target = tmp_path / db2
        if op == "brief":
            # The results table is append-only, so the bad briefing is
            # seeded from scratch instead of updated in place.
            _seed_zero(target, bad_briefing=True)
            code, stdout, stderr = _run(target, capsys=capsys)
            assert code == 0, stderr
            got = {row["slot"]: row for row in _lines(stdout)}
            first = got[SLOT1_LOCAL]["sides"][0]
            assert first["facts_cited"] == {
                "code": "unknown",
                "model": "unknown",
                "unknown": "unknown",
            }, op
            assert got[SLOT1_LOCAL]["facts_cited"] == {
                "code": "unknown",
                "model": "unknown",
                "unknown": "unknown",
            }, op
            continue
        src = sqlite3.connect(db)
        dst = sqlite3.connect(target)
        src.backup(dst)
        dst.close()
        src.close()
        fix = sqlite3.connect(target)
        if op == "drop":
            fix.execute("DROP TABLE facts")
        elif op == "col":
            fix.execute("ALTER TABLE facts RENAME TO facts_old")
            fix.execute(
                "CREATE TABLE facts (cycle_id TEXT NOT NULL, run INTEGER NOT"
                " NULL, fact_id TEXT NOT NULL, subject_id TEXT NOT NULL,"
                " window_start TEXT NOT NULL, window_end TEXT NOT NULL,"
                " statement TEXT NOT NULL, evidence TEXT NOT NULL, tier TEXT"
                " NOT NULL, PRIMARY KEY (cycle_id, run, fact_id))"
            )
            fix.execute(
                "INSERT INTO facts (cycle_id, run, fact_id, subject_id,"
                " window_start, window_end, statement, evidence, tier) SELECT"
                " cycle_id, run, fact_id, subject_id, window_start, window_end,"
                " statement, evidence, tier FROM facts_old"
            )
        fix.commit()
        fix.close()
        code, stdout, stderr = _run(target, capsys=capsys)
        assert code == 0, stderr
        got = {row["slot"]: row for row in _lines(stdout)}
        first = got[SLOT1_LOCAL]["sides"][0]
        assert first["facts_cited"] == {
            "code": "unknown",
            "model": "unknown",
            "unknown": "unknown",
        }, op
        assert got[SLOT1_LOCAL]["facts_cited"] == {
            "code": "unknown",
            "model": "unknown",
            "unknown": "unknown",
        }, op


def test_table_of_cards_origins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing the unknown-on-missing rule (printing 0) makes it fail."""
    db = tmp_path / "cards.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    _side_row(conn, "card-1", "B", SLOT1_UTC, "disconnect", "proposal")
    # Both sides cite f1; f1 also exists in another cycle under the same id.
    body = _briefing_json(
        "builder", SLOT1_LOCAL, [_claim("c1", "Shared.", ["f1", "fmissing"])]
    )
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _result(
        conn, "key-2", "cycle-1", 1, "disconnect", SLOT1_LOCAL, "proposal", body, []
    )
    _cycle(conn, "cycle-1", 1, _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "model")
    _cycle(conn, "cycle-2", 1, _passes_json())
    _fact(conn, "cycle-2", 1, "f1", "model")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    # fmissing has no row in the cycle: it counts unknown 1 per side and
    # once at card level; the word unknown is for unreadable sides only.
    assert row["sides"][0]["facts_cited"]["unknown"] == 1
    assert row["facts_cited"] == {"code": 0, "model": 1, "unknown": 1}
    # Same fact id in another cycle counts again only when actually cited
    # from that cycle; here it is not, so f1 counts once, not twice.
    assert row["cycle_origin"] == "model"


def test_table_of_cards_shared_and_fourth_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Shared facts count once per side and once per card; 4th claims hide."""
    db = tmp_path / "shared.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    _side_row(conn, "card-1", "B", SLOT1_UTC, "disconnect", "proposal")
    body = _briefing_json(
        "builder",
        SLOT1_LOCAL,
        [
            _claim("c1", "One.", ["f1", "f1"]),
            _claim("c2", "Two.", ["f2"]),
            _claim("c3", "Three.", []),
            _claim("c4", "Four.", ["f3"]),
        ],
    )
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _result(
        conn, "key-2", "cycle-1", 1, "disconnect", SLOT1_LOCAL, "proposal", body, []
    )
    _cycle(conn, "cycle-1", 1, _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "model")
    _fact(conn, "cycle-1", 1, "f2", "code")
    _fact(conn, "cycle-1", 1, "f3", "model")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    # f1 twice on a side counts once per side; f3 on the 4th claim is hidden.
    assert row["sides"][0]["facts_cited"] == {"code": 1, "model": 1, "unknown": 0}
    assert row["facts_cited"] == {"code": 1, "model": 1, "unknown": 0}
    assert row["sides"][0]["metrics_cited"] == 0


def test_not_on_card_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Entries carry only profile, kind, reason_codes and count nothing."""
    db = tmp_path / "sided.db"
    conn = _mini_db(db)
    # One-sided card: builder shows, disconnect noops.
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", ["f1"])])
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _attempt(conn, "key-1")
    _result(
        conn,
        "key-2",
        "no-cycle",
        0,
        "disconnect",
        SLOT1_LOCAL,
        "noop",
        None,
        ["NOOP_NO_FREE_HOUR"],
    )
    _cycle(conn, "cycle-1", 1, _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "model")
    # A no-card slot: both profiles noop.
    _ledger(conn, SLOT2_UTC, "start", "ok")
    _ledger(conn, SLOT2_UTC, "done", "NOOP_MIXED", None)
    for key, profile in (("key-3", "builder"), ("key-4", "disconnect")):
        _result(
            conn,
            key,
            "no-cycle",
            0,
            profile,
            SLOT2_LOCAL,
            "noop",
            None,
            ["NOOP_NO_FACTS"],
        )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    one_sided = rows[SLOT1_LOCAL]
    assert [side["profile"] for side in one_sided["sides"]] == ["builder"]
    (entry,) = one_sided["not_on_card"]
    assert entry == {
        "profile": "disconnect",
        "kind": "noop",
        "reason_codes": ["NOOP_NO_FREE_HOUR"],
    }
    assert one_sided["facts_cited"] == {"code": 0, "model": 1, "unknown": 0}
    no_card = rows[SLOT2_LOCAL]
    assert no_card["sides"] == []
    assert no_card["delivery"] == "no_card"
    assert no_card["facts_cited"] == {"code": 0, "model": 0, "unknown": 0}
    assert no_card["cycle_origin"] == "none"
    assert {item["profile"] for item in no_card["not_on_card"]} == {
        "builder",
        "disconnect",
    }


def test_latest_card_row_decides_including_null(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A trailing NULL card row means no card; the older id is superseded."""
    db = tmp_path / "fresh.db"
    conn = _mini_db(db)
    # A first run builds card-1 but its send fails; a --fresh run ends in
    # a card row with a NULL id and a noop.
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "send_intent", "intent", "card-1", "message_id=11")
    _ledger(conn, SLOT1_UTC, "send", "SEND_NOT_SENT", "card-1", "message_id=11")
    _ledger(conn, SLOT1_UTC, "card", "ok", None, "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "SEND_NOT_SENT", None)
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    _result(
        conn,
        "key-1",
        "no-cycle",
        0,
        "builder",
        SLOT1_LOCAL,
        "noop",
        None,
        ["NOOP_NO_FREE_HOUR"],
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["delivery"] == "no_card"
    assert row["sides"] == []
    assert row["superseded_cards"] == 1
    assert row["facts_cited"] == {"code": 0, "model": 0, "unknown": 0}
    assert row["cycle_origin"] == "none"
    (entry,) = row["not_on_card"]
    assert entry == {
        "profile": "builder",
        "kind": "noop",
        "reason_codes": ["NOOP_NO_FREE_HOUR"],
    }


def test_card_without_side_rows_is_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A delivered card with no side rows prints unknown, never false zeros."""
    for variant in ("rows-gone", "table-missing"):
        db = tmp_path / f"sides-{variant}.db"
        conn = _mini_db(db)
        # The side rows are gone: the ledger still names the delivered
        # card, but no row (or no table) backs it. slot_cards is
        # append-only, so the rows-gone file is seeded without them.
        _ledger(conn, SLOT1_UTC, "start", "ok")
        _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
        _ledger(conn, SLOT1_UTC, "send_intent", "intent", "card-1", "message_id=11")
        _ledger(conn, SLOT1_UTC, "send", "delivered", "card-1", "message_id=11")
        _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
        if variant == "table-missing":
            conn.execute("DROP TABLE slot_cards")
        conn.commit()
        conn.close()
        code, stdout, stderr = _run(db, capsys=capsys)
        assert code == 0, stderr
        (row,) = _lines(stdout)
        assert row["delivery"] == "delivered", variant
        assert row["sides"] == [], variant
        assert row["facts_cited"] == {
            "code": "unknown",
            "model": "unknown",
            "unknown": "unknown",
        }, variant
        assert row["cycle_origin"] == "unknown", variant


def test_pass_and_attempt_unknowns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing pass numbers, non-dict passes and bad attempt fields: unknown."""
    db = tmp_path / "passunknown.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", [])])
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    conn.execute(
        "INSERT INTO proposal_attempts (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, attempt, model_requested, model_reported, effort,"
        " prompt_hash, raw_response, parsed_ok, blocked, gate_codes, latency_ms,"
        " prompt_tokens, completion_tokens, reasoning_tokens, finish_reason,"
        " cached_tokens, transport, transport_version, harness_rules_file)"
        " VALUES ('key-1', 'cycle-1', 1, 'builder', ?, ?, 1, 'wonder-1',"
        " 'wonder-1', 'low', 'ph', 'raw', 'bogus', 'bogus', '[]', 'slow', 3, 5,"
        " 7, 'stop', 0, 'muse', 'Muse Code 1.4.14', NULL)",
        (SUBJECT, SLOT1_LOCAL),
    )
    passes = json.dumps([{"name": "personal"}, "junk"])
    _cycle(conn, "cycle-1", 1, passes)
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    side = row["sides"][0]
    assert side["cycle"]["origin"] == "unknown"
    first, second = side["cycle"]["passes"]
    assert first["attempts"] == "unknown"
    assert first["latency_ms"] == "unknown"
    assert first["kept"] == "unknown"
    assert first["noop_reason"] == "unknown"
    assert second["attempts"] == "unknown"
    assert side["cycle"]["dropped_codes"] == []
    (attempt,) = side["attempts"]
    assert attempt["latency_ms"] == "unknown"
    assert attempt["parsed_ok"] == "unknown"
    assert attempt["blocked"] == "unknown"
    # A list that holds entries with real zeros only is still code.
    db2 = tmp_path / "passzeros.db"
    conn = _mini_db(db2)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    _result(conn, "key-1", "cycle-9", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _cycle(conn, "cycle-9", 1, _passes_json(0, 0))
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db2, capsys=capsys)
    assert code == 0, stderr
    (row2,) = _lines(stdout)
    assert row2["sides"][0]["cycle"]["origin"] == "code"


def test_noop_reason_none_vs_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A JSON null noop is none; a missing key is unknown."""
    db = tmp_path / "noop.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", [])])
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    passes = json.dumps(
        [
            {
                "name": "personal",
                "attempts": 0,
                "model_id": "",
                "latency_ms": 0,
                "completion_tokens": 0,
                "finish_reason": "stop",
                "kept": 0,
                "noop_reason": None,
            },
            {
                "name": "feed",
                "attempts": 0,
                "model_id": "",
                "latency_ms": 0,
                "completion_tokens": 0,
                "finish_reason": "stop",
                "kept": 0,
            },
        ]
    )
    _cycle(conn, "cycle-1", 1, passes)
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    personal, feed = row["sides"][0]["cycle"]["passes"]
    assert personal["noop_reason"] == "none"
    assert feed["noop_reason"] == "unknown"


def test_local_retries_unknown_when_table_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing retries table prints unknown, never a false zero."""
    db = tmp_path / "retries.db"
    conn = _mini_db(db)
    _card_slot(conn)
    conn.execute(
        "INSERT INTO local_start_retries (slot, profile, try, reason, latency_ms,"
        " exit_code, stderr) VALUES (?, 'builder', 1, 'r', 5, NULL, 'r-err')",
        (SLOT1_UTC,),
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["sides"][0]["local_retries"] == 1
    missing = tmp_path / "noretries.db"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(missing)
    src.backup(dst)
    dst.close()
    src.close()
    fix = sqlite3.connect(missing)
    fix.execute("DROP TABLE local_start_retries")
    fix.commit()
    fix.close()
    code, stdout, stderr = _run(missing, capsys=capsys)
    assert code == 0, stderr
    (row2,) = _lines(stdout)
    assert row2["sides"][0]["local_retries"] == "unknown"


def test_unknown_lists_and_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unparseable lists print unknown; deep JSON and odd types never traceback."""
    db = tmp_path / "lists.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", [])])
    deep = "[" * 20000 + "]" * 20000
    # proposal_results is append-only, so the deep value goes in the row
    # itself, not an update.
    conn.execute(
        "INSERT INTO proposal_results (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, kind, briefing_json, fallback_json, snapshot,"
        " hour_start, hour_end, reason_codes, cycle_age_s) VALUES ('key-1',"
        " 'cycle-1', 1, 'builder', ?, ?, 'proposal', ?, NULL, '{}', NULL, NULL,"
        " ?, 1.0)",
        (SUBJECT, SLOT1_LOCAL, body, deep),
    )
    conn.execute(
        "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
        " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason, snapshot,"
        " passes, dropped_codes, kept_count, dropped_count) VALUES ('cycle-1',"
        " 1, 's', 'a', 'm', 'p', 1, 1, 0, NULL, '{}', ?, '\"just a string\"',"
        " 1, 0)",
        (deep,),
    )
    conn.execute(
        "INSERT INTO proposal_attempts (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, attempt, model_requested, model_reported, effort,"
        " prompt_hash, raw_response, parsed_ok, blocked, gate_codes, latency_ms,"
        " prompt_tokens, completion_tokens, reasoning_tokens, finish_reason,"
        " cached_tokens, transport, transport_version, harness_rules_file)"
        " VALUES ('key-1', 'cycle-1', 1, 'builder', ?, ?, 1, 'wonder-1',"
        " 'wonder-1', 'low', 'ph', 'raw', 1, 0, ?, 9, 3, 5, 7, 'stop', 0,"
        " 'muse', 'Muse Code 1.4.14', NULL)",
        (SUBJECT, SLOT1_LOCAL, b"\x00\x01blob"),
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    assert "Traceback" not in stderr
    (row,) = _lines(stdout)
    side = row["sides"][0]
    assert side["reason_codes"] == "unknown"
    assert side["cycle"]["passes"] == "unknown"
    assert side["cycle"]["dropped_codes"] == "unknown"
    assert side["attempts"][0]["gate_codes"] == "unknown"
    # Wrong types in TEXT columns map, never crash: an int kind is unknown.
    odd = tmp_path / "odd.db"
    conn = _mini_db(odd)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", 5)  # type: ignore[arg-type]
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _cycle(conn, "cycle-1", 1, _passes_json())
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(odd, capsys=capsys)
    assert code == 0, stderr
    assert "Traceback" not in stderr
    (odd_row,) = _lines(stdout)
    assert odd_row["sides"][0]["kind"] == "unknown"
    # Any other exception prints its class name as a closed code, exit 1.
    import framework.provenance.export as _export_mod

    def _boom(path: Path) -> tuple[list[str], dict[str, int]]:
        raise RuntimeError("boom")

    monkeypatch.setattr(_export_mod, "build_lines", _boom)
    code = main(["--db", str(tmp_path / "x.db")])
    out = capsys.readouterr()
    assert code == 1
    assert "code=RuntimeError" in out.err
    assert "Traceback" not in out.out + out.err
    assert out.out == ""


def test_schema_shapes_reject_bad_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each model rejects a bad slot, code, final code and finish reason."""
    import pytest as _pytest
    from pydantic import ValidationError

    from framework.provenance.schemas import ProvenanceLine

    db = tmp_path / "shapes2.db"
    conn = _mini_db(db)
    _card_slot(conn)
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (good,) = _lines(stdout)
    for path, bad in (
        (("slot",), "2026-11-02 15:30:00"),
        (("slot",), "2026-11-02T15:30:00Z"),
        (("final_code",), "zzz-bad"),
        (("final_code",), "WEIRD Lower"),
    ):
        mutated = json.loads(json.dumps(good))
        mutated[path[0]] = bad
        with _pytest.raises(ValidationError):
            ProvenanceLine.model_validate(mutated)
    side = json.loads(json.dumps(good))["sides"][0]
    side["reason_codes"] = ["zzz-bad"]
    with _pytest.raises(ValidationError):
        ProvenanceLine.model_validate({**good, "sides": [side]})
    attempt = dict(side["attempts"][0])
    attempt["gate_codes"] = ["zzz-bad"]
    with _pytest.raises(ValidationError):
        ProvenanceLine.model_validate(
            {**good, "sides": [{**side, "attempts": [attempt]}]}
        )
    cycle = dict(side["cycle"])
    cycle_pass = dict(cycle["passes"][0])
    cycle_pass["finish_reason"] = "whisper"
    with _pytest.raises(ValidationError):
        ProvenanceLine.model_validate(
            {**good, "sides": [{**side, "cycle": {**cycle, "passes": [cycle_pass]}}]}
        )


def test_edge_rows_no_card_and_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing rows and tables print unknown or real zeros, never guesses."""
    db = tmp_path / "edge.db"
    conn = _mini_db(db)
    # Slot 1: card side whose proposal row is missing; no start row either.
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    # Slot 2: no-cycle fallback side with attempts stored nowhere nearby.
    _ledger(conn, SLOT2_UTC, "start", "ok")
    _ledger(conn, SLOT2_UTC, "card", "ok", "card-2", "codes=-")
    _ledger(conn, SLOT2_UTC, "done", "SEND_NOT_SENT", "card-2")
    _side_row(conn, "card-2", "A", SLOT2_UTC, "builder", "fallback")
    _result(conn, "key-9", "no-cycle", 0, "builder", SLOT2_LOCAL, "fallback", None, [])
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    orphan = rows[SLOT1_LOCAL]
    assert orphan["forced"] == "unknown"
    assert orphan["sides"][0]["attempts"] == "unknown"
    assert orphan["sides"][0]["reason_codes"] == "unknown"
    assert orphan["sides"][0]["cycle"]["origin"] == "unknown"
    fallback = rows[SLOT2_LOCAL]
    side = fallback["sides"][0]
    assert side["cycle"]["origin"] == "none"
    assert side["cycle"]["facts_available"] == {"code": 0, "model": 0, "unknown": 0}
    assert side["cycle"]["passes"] == []
    assert side["facts_cited"] == {"code": 0, "model": 0, "unknown": 0}
    assert fallback["delivery"] == "not_sent"
    assert fallback["final_code"] == "SEND_NOT_SENT"
    # Several start rows are forced if any says so.
    target = tmp_path / "forced.db"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(target)
    src.backup(dst)
    dst.close()
    src.close()
    fix = sqlite3.connect(target)
    fix.execute(
        "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id, detail)"
        " VALUES (?, 'start', 'ok', 0.1, NULL, 'forced=1')",
        (SLOT1_UTC,),
    )
    fix.execute(
        "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id, detail)"
        " VALUES (?, 'start', 'ok', 0.1, NULL, 'as_of=x')",
        (SLOT1_UTC,),
    )
    fix.commit()
    fix.close()
    code, stdout, stderr = _run(target, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    assert rows[SLOT1_LOCAL]["forced"] is True
    assert rows[SLOT2_LOCAL]["forced"] is False
    # A missing attempts table still gives the word unknown.
    target2 = tmp_path / "noattempts.db"
    src = sqlite3.connect(db)
    dst = sqlite3.connect(target2)
    src.backup(dst)
    dst.close()
    src.close()
    fix = sqlite3.connect(target2)
    fix.execute("DROP TABLE proposal_attempts")
    fix.commit()
    fix.close()
    code, stdout, stderr = _run(target2, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    assert rows[SLOT2_LOCAL]["sides"][0]["attempts"] == "unknown"


FAMILY_CODES = [
    "L0_SAMPLE",
    "L1_SAMPLE",
    "L1B_SAMPLE",
    "NOOP_SAMPLE",
    "FACT_SAMPLE",
    "CODE_SAMPLE",
    "FALLBACK_SAMPLE",
    "MODEL_SAMPLE",
    "PROPOSAL_SAMPLE",
    "DRAFT_SAMPLE",
    "PARENT_SAMPLE",
    "CYCLE_SAMPLE",
    "NO_CYCLE",
    "SLOT_SAMPLE",
    "SEND_SAMPLE",
    "DELIVERY_SAMPLE",
    "CHART_SAMPLE",
    "PREFLIGHT_SAMPLE",
    "TERMS_SAMPLE",
    "STALE_SAMPLE",
    "COMMITMENT_SAMPLE",
    "COMMITMENTS_SAMPLE",
    "FACTS_SAMPLE",
    "DISCONNECT_SAMPLE",
    "LEARNER_SAMPLE",
    "CALENDAR_SAMPLE",
    "BUCKET_SAMPLE",
    "CORRECTION_SAMPLE",
    "CONTRIBUTOR_SAMPLE",
]


def test_code_families_survive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One code per family survives; outside every family is the placeholder."""
    db = tmp_path / "codes.db"
    conn = _mini_db(db)
    conn.execute(
        "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id, detail)"
        " VALUES (?, 'done', 'STALE_SAMPLE', 0.1, NULL, '')",
        (SLOT1_UTC,),
    )
    conn.execute(
        "INSERT INTO proposal_results (proposal_key, cycle_id, run, profile_id,"
        " subject_id, slot, kind, briefing_json, fallback_json, snapshot,"
        " hour_start, hour_end, reason_codes, cycle_age_s) VALUES ('key-1',"
        " 'no-cycle', 0, 'builder', ?, ?, 'noop', NULL, NULL, '{}', NULL, NULL,"
        " ?, 1.0)",
        (SUBJECT, SLOT1_LOCAL, json.dumps([*FAMILY_CODES, "zzz-bad"])),
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["final_code"] == "STALE_SAMPLE"
    (entry,) = row["not_on_card"]
    for sample in FAMILY_CODES:
        assert sample in entry["reason_codes"], sample
    assert OTHER_CODE in entry["reason_codes"]
    assert "zzz-bad" not in entry["reason_codes"]


def test_closed_fields_mapping(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each out-of-shape closed value maps to its exact expected word."""
    from framework.provenance.schemas import (
        clean_code,
        clean_effort,
        clean_finish_reason,
        clean_kind,
        clean_letter,
        clean_model_id,
        clean_pass_name,
        clean_profile,
        clean_transport,
        clean_version,
    )

    assert clean_profile("root") == "unknown"
    assert clean_kind("draft") == "unknown"
    assert clean_letter("C") == "unknown"
    assert clean_transport("grpc") == "unknown"
    assert clean_effort("ultra") == "unknown"
    assert clean_finish_reason("STOP") == "unknown"
    assert clean_finish_reason("stop") == "stop"
    assert clean_pass_name("other") == "unknown"
    assert clean_code("zzz-bad") == OTHER_CODE
    assert clean_code("L1_ADVICE") == "L1_ADVICE"
    assert clean_version("nothing here") == "unknown"
    assert clean_version("Muse Code 1.4.14 (1.4.14-R7309.1)") == "1.4.14"
    assert clean_model_id("") == "unknown"
    assert clean_model_id("unreported") == "unknown"
    assert clean_model_id("/tmp/weights/wonder-1") == "wonder-1"
    # A trailing separator means a directory, so unknown, not a basename.
    assert clean_model_id("C:\\models\\wonder-1\\") == "unknown"
    assert clean_model_id("https://host/x/wonder-1?tag=a") == "wonder-1"
    assert clean_model_id("model name with spaces") == "unknown"
    assert clean_model_id("user@host/wonder-1") == "wonder-1"
    # The basename rule stays strict for the runtime user.
    import getpass

    user = getpass.getuser()
    assert clean_model_id(f"/home/{user}") == "unknown"
    assert clean_model_id(user) == "unknown"
    # End to end: a planted out-of-shape row maps, never leaks.
    db = tmp_path / "shapes.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "facts_model", "TimeoutError")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "weird outcome here", "card-1")
    _side_row(conn, "card-1", "Z", SLOT1_UTC, "root", "draft")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", [])])
    _result(conn, "key-1", "cycle-1", 1, "root", SLOT1_LOCAL, "draft", body, [])
    _attempt(
        conn,
        "key-1",
        requested="/tmp/models/won der-1",
        reported="",
        transport="grpc",
        version="nothing here",
        effort="ultra",
        finish="STOP",
    )
    _cycle(conn, "cycle-1", 1, _passes_json())
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["facts_model_step"] == OTHER_CODE
    assert row["final_code"] == OTHER_CODE
    side = row["sides"][0]
    assert side["letter"] == "unknown"
    assert side["profile"] == "unknown"
    assert side["kind"] == "unknown"
    (attempt,) = side["attempts"]
    assert attempt["transport"] == "unknown"
    assert attempt["effort"] == "unknown"
    assert attempt["muse_version"] == "unknown"
    assert attempt["model_requested"] == "unknown"
    assert attempt["model_reported"] == "unknown"
    assert "finish_reason" not in attempt
    assert "tmp" not in stdout and "grpc" not in stdout


def test_selection_matches_build_statements(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing the 3-claim cap from the export selection makes it fail."""
    from framework.provenance.export import select_claim_texts

    briefing = Briefing.model_validate(
        {
            "id": "brf-sel",
            "profile_id": "builder",
            "subject_id": SUBJECT,
            "slot": SLOT1_LOCAL,
            "sections": [
                {
                    "type": "working",
                    "claims": [
                        {"id": "n1", "text": "Note one.", "fact_ids": ["fx"]},
                        {"id": "n2", "text": "Note two.", "fact_ids": ["fy"]},
                    ],
                },
                {
                    "type": "overall_state",
                    "claims": [
                        {"id": "o1", "text": "Overall one.", "fact_ids": ["f1"]},
                        {"id": "o2", "text": "Overall two.", "fact_ids": ["f2"]},
                    ],
                },
                {"type": "actions", "claims": []},
            ],
        }
    )
    pieces = build_statements([("A", "Builder", briefing)])
    assert select_claim_texts(briefing) == list(pieces[1:])
    assert select_claim_texts(briefing) == ["Overall one.", "Note one.", "Note two."]
    # End to end: only the selected claims count.
    db = tmp_path / "sel.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = json.dumps(briefing.model_dump(mode="json"), sort_keys=True)
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _cycle(conn, "cycle-1", 1, _passes_json())
    for fid, origin in (
        ("f1", "model"),
        ("fx", "model"),
        ("fy", "code"),
        ("f2", "code"),
    ):
        _fact(conn, "cycle-1", 1, fid, origin)
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["sides"][0]["facts_cited"] == {"code": 1, "model": 2, "unknown": 0}


def test_real_writer_slot_roundtrip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The export reads what the real run_slot writes, down to one real cited fact."""
    import json as _json

    from framework.cycle.orchestrator import Seams, run_slot
    from framework.cycle.slot_ledger import SlotLedger
    from framework.proposal.core import ProposalResult
    from framework.store.store import EventStore

    subject = "subject-a"
    slot = datetime(2026, 11, 2, 15, 30, tzinfo=MADRID)
    db = tmp_path / "cycle.db"
    terms = tmp_path / "terms"
    terms.mkdir(exist_ok=True)
    (terms / "deny-terms.txt").write_text("zzforbiddenzz\n")
    commitments = tmp_path / "commitments.json"
    commitments.write_text(
        _json.dumps(
            [
                {
                    "id": "b-1",
                    "profile_id": "builder",
                    "title": "Morning pages draft",
                    "kind": "build",
                    "dimension": "love",
                    "evidence": "github_push",
                },
                {
                    "id": "d-1",
                    "profile_id": "disconnect",
                    "title": "Short walk outside",
                    "kind": "build",
                    "dimension": "love",
                    "evidence": "github_push",
                },
            ]
        )
    )
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(terms))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(commitments))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    from framework.cycle.orchestrator import FactsChildResult

    class _Clock:
        def __init__(self, now: datetime) -> None:
            self.now = now

        def __call__(self) -> datetime:
            return self.now

    class _Facts:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def __call__(self, **kwargs: Any) -> FactsChildResult:
            self.calls.append(dict(kwargs))
            return FactsChildResult("MODEL_DOWN", None, None)

    from framework.briefing.schemas import Briefing as _Briefing

    class _Spy:
        def __init__(self) -> None:
            self.calls = 0
            self.cited: list[str | None] = []

        def __call__(self, **kwargs: Any) -> ProposalResult:
            self.calls += 1
            profile = str(kwargs["profile_id"])
            eligible = kwargs["eligible"]
            hour = kwargs["hour"]
            shown = eligible[0].id
            start = slot.replace(hour=16, minute=0)
            end = slot.replace(hour=17, minute=0)
            # One real code fact id from the context the real code passes in.
            fact_ids = sorted(kwargs["context"].facts.keys())
            cited = str(fact_ids[0]) if fact_ids else None
            self.cited.append(cited)
            briefing = _Briefing.model_validate(
                {
                    "id": f"brf-{shown}",
                    "profile_id": profile,
                    "subject_id": subject,
                    "slot": slot.isoformat(),
                    "sections": [
                        {
                            "type": "overall_state",
                            "claims": [
                                {
                                    "id": "c1",
                                    "text": "First claim text here.",
                                    "fact_ids": [cited] if cited is not None else [],
                                }
                            ],
                        },
                        {
                            "type": "actions",
                            "claims": [],
                            "actions": [
                                {
                                    "id": "act-1",
                                    "commitment_id": shown,
                                    "kind": "build",
                                    "text": "Model action wording",
                                    "dimension": "love",
                                    "proposed_start": start.isoformat(),
                                    "proposed_end": end.isoformat(),
                                }
                            ],
                        },
                    ],
                }
            )
            return ProposalResult(
                kind="proposal",
                profile_id=profile,  # type: ignore[arg-type]
                subject_id=kwargs["subject_id"],
                cycle_id=kwargs["cycle_id"],
                run=kwargs["run"],
                slot=kwargs["slot"],
                hour=hour,
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(),
                cycle_age_s=0.0,
                prompt_hash="",
            )

    class _Telegram:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def send_photo(
            self,
            chat_id: int,
            photo: bytes,
            caption: str,
            markup: dict[str, Any],
            timeout_s: float = 60.0,
            disable_notification: bool = False,
        ) -> dict[str, Any]:
            self.calls.append({"chat_id": chat_id, "photo_len": len(photo)})
            return {"message_id": 11}

    # The clock sits before the facts deadline, so the real code calls the
    # model facts child, which is down, and records MODEL_DOWN.
    clock = _Clock(slot - timedelta(minutes=20))
    home = tmp_path / "home"
    seams = Seams(
        facts=_Facts(),
        wonder=lambda terms_arg, deadline: None,  # type: ignore[return-value]
        telegram=_Telegram(),
        clock=clock,
        sleep=lambda s: None,
        home=home,
        ledger_sleep=lambda s: None,
    )
    store = EventStore(db_path=db)
    try:
        # Made-up rows so the real code cycle mints real code facts.
        from framework.schemas.events import Event as _Event

        pushes = [
            _Event.model_validate(
                {
                    "id": f"push-{index}",
                    "subject_id": subject,
                    "source": "github",
                    "type": "github.push",
                    "time": slot.replace(hour=12, minute=index).isoformat(),
                    "source_id": f"github.push-push-{index}",
                    "data": {
                        "type": "github.push",
                        "repo": "madeup/repo",
                        "counts": {"commits": 1},
                    },
                    "tier": "public",
                    "collected_at": slot.replace(
                        hour=12, minute=index, second=30
                    ).isoformat(),
                    "collector_version": "synthetic@0.1.0",
                }
            )
            for index in range(3)
        ]
        assert store.append_events(pushes) == len(pushes)
    finally:
        store.close()
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO cursors (name, cursor, updated_at) VALUES (?, '{}', ?)",
        ("calendar-synthetic", slot.isoformat()),
    )
    conn.commit()
    conn.close()
    spy = _Spy()
    monkeypatch.setattr("framework.cycle.propose", spy)
    exit_code = run_slot(
        slot=slot,
        subject_id=subject,
        db_path=db,
        no_wait=True,
        seams=seams,
    )
    capsys.readouterr()
    assert exit_code == 0
    assert spy.calls == 2
    card_id = SlotLedger(db).latest_card_id(slot)
    assert card_id is not None
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["slot"] == slot.isoformat()
    assert row["delivery"] == "delivered"
    assert [side["letter"] for side in row["sides"]] == ["A", "B"]
    # The local model is down in this test, so the origin is exactly code
    # and the step that says so is MODEL_DOWN, not a wider word.
    assert spy.cited and all(spy.cited)
    assert row["cycle_origin"] == "code"
    assert row["facts_model_step"] == "MODEL_DOWN"
    # Both sides cite the same real code fact id, so it counts once at
    # card level, as code, with model at exactly 0.
    assert row["facts_cited"] == {"code": 1, "model": 0, "unknown": 0}
    for side in row["sides"]:
        assert side["facts_cited"] == {"code": 1, "model": 0, "unknown": 0}
    ProvenanceLine.model_validate(row)


def _snapshot(db: Path) -> tuple[bytes, list[str]]:
    data = db.read_bytes()
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        master = conn.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    finally:
        conn.close()
    return data, [str(row[0]) for row in master]


def test_readonly_bytes_and_master_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing the read-only URI or the guard makes it fail."""
    db = tmp_path / "ro.db"
    conn = _mini_db(db)
    _card_slot(conn)
    conn.commit()
    conn.close()
    before = _snapshot(db)
    code, _, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    assert _snapshot(db) == before
    # A write through the connection the export's own code opens raises.
    locked = _connect(db)
    try:
        with pytest.raises(sqlite3.OperationalError):
            locked.execute("CREATE TABLE probe (id INTEGER)")
    finally:
        locked.close()
    assert _snapshot(db) == before


def test_stability_identical_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same database, same bytes across runs and across out files."""
    db = tmp_path / "stable.db"
    conn = _mini_db(db)
    _card_slot(conn)
    conn.commit()
    conn.close()
    code, first, _ = _run(db, capsys=capsys)
    assert code == 0
    code, second, _ = _run(db, capsys=capsys)
    assert code == 0
    assert first == second
    assert first.endswith("\n")
    # Reading order, never sorted: slot comes first on head -1.
    assert next(iter(json.loads(first.splitlines()[0]).keys())) == "slot"
    assert first.splitlines()[0].startswith('{"slot":')


def test_guard_slot_loss_and_target_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dropping a slot from the target, or a bad target, refuses exit 2."""
    db = tmp_path / "guard.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _ledger(conn, SLOT2_UTC, "start", "ok")
    _ledger(conn, SLOT2_UTC, "done", "NOOP_MIXED", None)
    conn.commit()
    conn.close()
    target = tmp_path / "log.jsonl"
    code, _, stderr = _run(db, "--out", str(target), capsys=capsys)
    assert code == 0, stderr
    saved = target.read_bytes()
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode & 0o044 == 0o044 and mode != 0o600
    # A new export that lacks a slot the target holds refuses untouched.
    db2 = tmp_path / "guard2.db"
    conn = _mini_db(db2)
    _card_slot(conn)
    conn.commit()
    conn.close()
    code, _, stderr = _run(db2, "--out", str(target), capsys=capsys)
    assert code == 2
    assert "SLOT_LOST" in stderr
    assert target.read_bytes() == saved
    # An existing target that cannot be parsed line by line refuses too.
    target.write_text("not json\n")
    code, _, stderr = _run(db, "--out", str(target), capsys=capsys)
    assert code == 2
    assert "TARGET_UNPARSEABLE" in stderr
    assert target.read_text() == "not json\n"
    # A missing file exits 2 and creates nothing; a failed line writes nothing.
    missing = tmp_path / "absent.db"
    code, _, stderr = _run(missing, capsys=capsys)
    assert code == 2
    assert not missing.exists()
    bad = tmp_path / "bad.db"
    conn = _mini_db(bad)
    conn.execute(
        "INSERT INTO slot_ledger (slot, step, outcome, seconds, card_id, detail)"
        " VALUES ('not-a-time', 'done', 'delivered', 0.1, NULL, '')"
    )
    conn.commit()
    conn.close()
    gone = tmp_path / "never.jsonl"
    code, stdout, _ = _run(bad, "--out", str(gone), capsys=capsys)
    assert code == 1
    assert stdout == ""
    assert not gone.exists()
    # A file with no ledger tables exits 0 with zero lines, gaining no tables.
    empty = tmp_path / "empty.db"
    holder = sqlite3.connect(empty)
    holder.execute("CREATE TABLE other (id INTEGER)")
    holder.commit()
    holder.close()
    code, stdout, stderr = _run(empty, capsys=capsys)
    assert code == 0, stderr
    assert stdout == ""
    holder = sqlite3.connect(empty)
    try:
        names = [
            row[0]
            for row in holder.execute("SELECT name FROM sqlite_master").fetchall()
        ]
    finally:
        holder.close()
    assert "slot_ledger" not in names
    # A path with a space and a hash works.
    spaced = tmp_path / "dir with #hash" / "sp ace.db"
    spaced.parent.mkdir(parents=True)
    src = sqlite3.connect(db)
    dst = sqlite3.connect(spaced)
    src.backup(dst)
    dst.close()
    src.close()
    code, stdout, stderr = _run(spaced, capsys=capsys)
    assert code == 0, stderr
    assert len(_lines(stdout)) == 2


def test_isolation_no_outside_imports() -> None:
    """Any import of framework.provenance outside it makes it fail."""
    import ast

    root = Path(__file__).resolve().parent.parent / "framework"
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "framework/provenance" in path.as_posix().replace("\\", "/"):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "framework.provenance"
            ):
                offenders.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("framework.provenance"):
                        offenders.append(f"{path}:{node.lineno}")
    assert offenders == []


def test_sensitive_tier_not_counted_as_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counting a sensitive tier in facts_available makes it fail."""
    db = tmp_path / "sensitive.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _fact(conn, "cycle-1", 1, "f3", "model", tier="sensitive")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    # cycle-1 already holds one code and one model public fact; the
    # sensitive model fact must not move the model count.
    assert row["sides"][0]["cycle"]["facts_available"] == {
        "code": 1,
        "model": 1,
        "unknown": 0,
    }


def test_facts_join_uses_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Joining facts without run makes it fail."""
    db = tmp_path / "runjoin.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", ["f1"])])
    _result(conn, "key-1", "cycle-1", 2, "builder", SLOT1_LOCAL, "proposal", body, [])
    _attempt(conn, "key-1")
    _cycle(conn, "cycle-1", 1, _passes_json(0, 0))
    _cycle(conn, "cycle-1", 2, _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "code")
    _fact(conn, "cycle-1", 2, "f1", "model")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    # The side runs on run 2, so the run 2 model row counts, not run 1's code.
    side = row["sides"][0]
    assert side["facts_cited"] == {"code": 0, "model": 1, "unknown": 0}
    assert side["cycle"]["facts_available"] == {"code": 0, "model": 1, "unknown": 0}


def test_delivery_reads_latest_card_sends(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reading the slot's send rows instead of the card's makes it fail."""
    db = tmp_path / "persend.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "send_intent", "intent", "card-1", "message_id=11")
    _ledger(conn, SLOT1_UTC, "send", "delivered", "card-1", "message_id=11")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-2", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "SEND_NOT_SENT", "card-2")
    _side_row(conn, "card-2", "A", SLOT1_UTC, "builder", "noop")
    _result(
        conn,
        "key-9",
        "no-cycle",
        0,
        "builder",
        SLOT1_LOCAL,
        "noop",
        None,
        ["NOOP_NO_FREE_HOUR"],
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    # The latest card never sent, though the older card did.
    assert row["delivery"] == "not_sent"
    assert row["superseded_cards"] == 1


def test_watchdog_rows_ignored_for_final_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counting watchdog rows for final_code makes it fail."""
    db = tmp_path / "watchdog.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _ledger(conn, SLOT1_UTC, "watchdog", "SEND_NOT_SENT", "card-1", "probe=1")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["delivery"] == "delivered"
    assert row["final_code"] == "delivered"


def test_gate_codes_read_code_not_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reading gate codes from location instead of code makes it fail."""
    db = tmp_path / "gateloc.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", [])])
    _result(conn, "key-1", "cycle-1", 1, "builder", SLOT1_LOCAL, "proposal", body, [])
    _attempt(conn, "key-1", codes=[{"code": "L1_SAMPLE", "location": "zzz-bad"}])
    _cycle(conn, "cycle-1", 1, _passes_json())
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    assert row["sides"][0]["attempts"][0]["gate_codes"] == ["L1_SAMPLE"]


def test_latest_result_row_wins(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Letting the oldest result at a slot win makes it fail."""
    db = tmp_path / "latestwins.db"
    conn = _mini_db(db)
    _ledger(conn, SLOT1_UTC, "start", "ok")
    _ledger(conn, SLOT1_UTC, "card", "ok", "card-1", "codes=-")
    _ledger(conn, SLOT1_UTC, "done", "delivered", "card-1")
    _side_row(conn, "card-1", "A", SLOT1_UTC, "builder", "proposal")
    body = _briefing_json("builder", SLOT1_LOCAL, [_claim("c1", "Shown.", ["f1"])])
    _result(
        conn,
        "key-old",
        "cycle-1",
        1,
        "builder",
        SLOT1_LOCAL,
        "proposal",
        body,
        ["L1_SAMPLE"],
    )
    _attempt(conn, "key-old", latency=1111)
    _result(
        conn,
        "key-new",
        "cycle-2",
        1,
        "builder",
        SLOT1_LOCAL,
        "proposal",
        body,
        ["L1B_SAMPLE"],
    )
    _attempt(conn, "key-new", latency=2222)
    _cycle(conn, "cycle-1", 1, _passes_json())
    _fact(conn, "cycle-1", 1, "f1", "code")
    _cycle(conn, "cycle-2", 1, _passes_json())
    _fact(conn, "cycle-2", 1, "f1", "model")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    side = row["sides"][0]
    assert side["reason_codes"] == ["L1B_SAMPLE"]
    assert side["attempts"][0]["latency_ms"] == 2222
    assert side["facts_cited"] == {"code": 0, "model": 1, "unknown": 0}


def test_ok_and_none_final_code_is_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing a last ledger row of ok or none as a final code makes it fail."""
    db = tmp_path / "oknone.db"
    conn = _mini_db(db)
    for slot_utc, outcome in ((SLOT1_UTC, "ok"), (SLOT2_UTC, "none")):
        _ledger(conn, slot_utc, "start", "ok")
        _ledger(conn, slot_utc, "card", "ok", "card-1", "codes=-")
        _ledger(conn, slot_utc, "done", outcome, "card-1")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    rows = {row["slot"]: row for row in _lines(stdout)}
    assert rows[SLOT1_LOCAL]["final_code"] == "unknown"
    assert rows[SLOT2_LOCAL]["final_code"] == "unknown"


def test_timeout_retries_closed_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Summing timeout_retries over every propose row makes it fail."""
    db = tmp_path / "retried.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _ledger(conn, SLOT1_UTC, "propose_builder", "proposal", None, "timeout_retries=1")
    _ledger(conn, SLOT1_UTC, "propose_disconnect", "proposal", None, "cycle=cycle-1")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    by_profile = {side["profile"]: side for side in row["sides"]}
    # A retried side prints its count beside local_retries.
    assert by_profile["builder"]["timeout_retries"] == 1
    # A row with no such key adds nothing, because older code never retried.
    assert by_profile["disconnect"]["timeout_retries"] == 0
    ProvenanceLine.model_validate(row)


def test_timeout_retries_sum_over_two_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Counting one propose row instead of summing both makes it fail."""
    db = tmp_path / "resumed.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _ledger(conn, SLOT1_UTC, "propose_builder", "proposal", None, "timeout_retries=1")
    _ledger(conn, SLOT1_UTC, "propose_builder", "proposal", None, "timeout_retries=2")
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    by_profile = {side["profile"]: side for side in row["sides"]}
    # A resumed or fresh run adds up over every propose row of the side.
    assert by_profile["builder"]["timeout_retries"] == 3
    ProvenanceLine.model_validate(row)


def test_timeout_retries_canary_is_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing a canary timeout_retries value instead of unknown makes it fail."""
    db = tmp_path / "canaryretry.db"
    conn = _mini_db(db)
    _card_slot(conn)
    _ledger(
        conn,
        SLOT1_UTC,
        "propose_builder",
        "proposal",
        None,
        "timeout_retries=quiescent",
    )
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    by_profile = {side["profile"]: side for side in row["sides"]}
    # A value that is not a non-negative whole number gives unknown.
    assert by_profile["builder"]["timeout_retries"] == "unknown"
    blob = stdout + stderr
    assert "quiescent" not in blob
    ProvenanceLine.model_validate(row)


def test_timeout_retries_unknown_with_no_row(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Printing 0 with no propose row instead of unknown makes it fail."""
    db = tmp_path / "norow.db"
    conn = _mini_db(db)
    _card_slot(conn)
    conn.commit()
    conn.close()
    code, stdout, stderr = _run(db, capsys=capsys)
    assert code == 0, stderr
    (row,) = _lines(stdout)
    for side in row["sides"]:
        # A side with no propose row at all prints unknown.
        assert side["timeout_retries"] == "unknown"
    ProvenanceLine.model_validate(row)
