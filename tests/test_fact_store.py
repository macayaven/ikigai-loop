"""Ticket 9: append-only cycle store, run allocation, replay identity."""

from dataclasses import replace
from pathlib import Path

import pytest

from evals.glimmer_cases import AS_OF, SUBJECT_ID, RecordingLLM, base_case
from framework.glimmer.facts import extract_facts
from framework.store.fact_store import FactStore


def _result():
    case = base_case()
    llm = RecordingLLM(personal=case.personal_texts, feed=case.feed_texts)
    return extract_facts(AS_OF, SUBJECT_ID, list(case.events), llm)


def test_latency_only_difference_replays_same_run(tmp_path: Path) -> None:
    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        assert store.record_cycle(result) == 1
        personal, feed = result.passes
        slower = replace(
            result,
            passes=(
                replace(personal, latency_ms=personal.latency_ms + 1800000),
                feed,
            ),
        )
        assert store.record_cycle(slower) == 1
        assert store.runs(result.cycle_id) == [1]
    finally:
        store.close()


def test_differing_response_content_appends_run_2(tmp_path: Path) -> None:
    from framework.glimmer.facts import AttemptRecord

    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        assert store.record_cycle(result) == 1
        (first, *rest) = result.responses
        altered = replace(
            result,
            responses=(
                AttemptRecord(
                    pass_name=first.pass_name,
                    attempt=first.attempt,
                    content=first.content + " ",
                ),
                *rest,
            ),
        )
        assert store.record_cycle(altered) == 2
        assert store.runs(result.cycle_id) == [1, 2]
    finally:
        store.close()


def test_raw_valid_counts_only_passes_that_ran(tmp_path: Path) -> None:
    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        personal, feed = result.passes
        valid_only = replace(
            result,
            passes=(
                replace(personal, raw_valid=True, attempts=1),
                replace(feed, raw_valid=False, attempts=0),
            ),
        )
        run = store.record_cycle(valid_only)
        assert store.fetch_cycle(valid_only.cycle_id, run)["raw_valid"] is True
        skipped = replace(
            result,
            passes=(
                replace(personal, raw_valid=False, attempts=0),
                replace(feed, raw_valid=False, attempts=0),
            ),
        )
        run = store.record_cycle(replace(skipped, prompt_hash="1" * 64))
        assert store.fetch_cycle(skipped.cycle_id, run)["raw_valid"] is False
        mixed = replace(
            result,
            passes=(
                replace(personal, raw_valid=True, attempts=1),
                replace(feed, raw_valid=False, attempts=1),
            ),
        )
        run = store.record_cycle(replace(mixed, prompt_hash="2" * 64))
        assert store.fetch_cycle(mixed.cycle_id, run)["raw_valid"] is False
    finally:
        store.close()


def test_dropped_codes_distinguish_runs(tmp_path: Path) -> None:
    from dataclasses import replace as _replace

    from framework.glimmer.facts import DroppedFact

    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        assert store.record_cycle(result) == 1
        altered = _replace(
            result,
            dropped=(
                *result.dropped,
                DroppedFact(statement_hash="deadbeefcafe", code="FACT_NUMBER_UNBACKED"),
            ),
        )
        assert store.record_cycle(altered) == 2
        assert store.runs(result.cycle_id) == [1, 2]
    finally:
        store.close()


def test_identical_replay_returns_same_run(tmp_path: Path) -> None:
    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        first = store.record_cycle(result)
        assert first == 1
        assert store.record_cycle(_result()) == 1
        assert store.runs(result.cycle_id) == [1]
    finally:
        store.close()


def test_differing_rerun_appends_run_2(tmp_path: Path) -> None:
    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        assert store.record_cycle(result) == 1
        altered = replace(result, prompt_hash="0" * 64)
        assert store.record_cycle(altered) == 2
        assert store.runs(result.cycle_id) == [1, 2]
    finally:
        store.close()


def test_triggers_abort_update_and_delete(tmp_path: Path) -> None:
    import sqlite3

    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        store.record_cycle(result)
        for table in ("cycles", "facts", "cycle_responses"):
            with pytest.raises(sqlite3.IntegrityError):
                store._conn.execute(f"UPDATE {table} SET rowid = rowid")
            with pytest.raises(sqlite3.IntegrityError):
                store._conn.execute(f"DELETE FROM {table}")
    finally:
        store.close()


def test_snapshot_passes_responses_round_trip(tmp_path: Path) -> None:
    store = FactStore(db_path=tmp_path / "facts.db")
    try:
        result = _result()
        run = store.record_cycle(result)
        cycle = store.fetch_cycle(result.cycle_id, run)
        assert cycle["subject_id"] == SUBJECT_ID
        assert cycle["prompt_hash"] == result.prompt_hash
        assert cycle["kept_count"] == len(result.facts)
        assert cycle["dropped_count"] == len(result.dropped)
        assert cycle["snapshot"] == result.snapshot.values
        assert [p["name"] for p in cycle["passes"]] == ["personal", "feed"]
        facts = store.fetch_facts(result.cycle_id, run)
        assert [f["fact_id"] for f in facts] == [f.id for f in result.facts]
        assert [f["statement"] for f in facts] == [f.statement for f in result.facts]
        responses = store.fetch_responses(result.cycle_id, run)
        assert [(r["pass"], r["attempt"]) for r in responses] == [
            (a.pass_name, a.attempt) for a in result.responses
        ]
        assert [r["content"] for r in responses] == [
            a.content for a in result.responses
        ]
    finally:
        store.close()


# Verbatim frozen copy of main's DDL at e126366 (triggers included). The
# previous-schema test below inserts through main's exact column lists,
# never through the new code, so the migration path is tested, not assumed.
_FROZEN_MAIN_DDL = """
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


def _write_previous_schema_db(path: Path, result) -> None:  # type: ignore[no-untyped-def]
    """Insert one run through main's exact column lists (no origin column)."""
    import sqlite3
    from dataclasses import asdict

    from framework.store.store import canonical_json

    conn = sqlite3.connect(path)
    # Main's FactStore and EventStore set WAL on every open; match their files.
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        conn.executescript(_FROZEN_MAIN_DDL)
        personal, feed = result.passes
        ran = [p for p in (personal, feed) if p.attempts > 0]
        raw_valid = bool(ran) and all(p.raw_valid for p in ran)
        conn.execute(
            "INSERT INTO cycles (cycle_id, run, subject_id, as_of, model_id,"
            " prompt_hash, latency_ms, raw_valid, is_noop, noop_reason,"
            " snapshot, passes, dropped_codes, kept_count, dropped_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result.cycle_id,
                1,
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
                    1,
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
                    1,
                    attempt.pass_name,
                    attempt.attempt,
                    attempt.content,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _model_only_result():  # type: ignore[no-untyped-def]
    """Two feed rows and a kept topic: no personal rows, so no code facts."""
    from evals.glimmer_cases import _dt, feed_aliases, feed_batch, feed_event

    items = (
        feed_event(
            eid="evt_origin_a",
            item="item-origin-a",
            day="2026-10-30",
            time=_dt(30, 9),
            title="Synthetic transformer pruning benchmark results",
        ),
        feed_event(
            eid="evt_origin_b",
            item="item-origin-b",
            day="2026-10-30",
            time=_dt(30, 10),
            title="Synthetic container scheduler release notes",
            source="hn",
            score=120.0,
        ),
    )
    feeds = feed_aliases(items)
    llm = RecordingLLM(
        feed=(
            feed_batch(
                {
                    "evidence": [feeds[items[0].id], feeds[items[1].id]],
                    "topic": "model compression methods",
                }
            ),
        )
    )
    return extract_facts(AS_OF, SUBJECT_ID, list(items), llm)


def test_previous_schema_migrates_and_replays(tmp_path: Path) -> None:
    import sqlite3

    from evals.glimmer_cases import _dt, push_event

    result = _model_only_result()
    assert result.code_fact_ids == ()
    db = tmp_path / "previous.db"
    _write_previous_schema_db(db, result)
    store = FactStore(db_path=db)
    try:
        facts = store.fetch_facts(result.cycle_id, 1)
        assert [f["origin"] for f in facts] == ["model"]
        assert [f["statement"] for f in facts] == [f.statement for f in result.facts]
        assert store.runs(result.cycle_id) == [1]
        cycle = store.fetch_cycle(result.cycle_id, 1)
        assert cycle["snapshot"] == result.snapshot.values
        assert cycle["kept_count"] == len(result.facts)
        responses = store.fetch_responses(result.cycle_id, 1)
        assert [(r["pass"], r["attempt"]) for r in responses] == [
            (a.pass_name, a.attempt) for a in result.responses
        ]
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("UPDATE facts SET rowid = rowid")
        push = push_event(eid="evt_origin_push", time=_dt(30, 14))
        from evals.glimmer_cases import personal_batch

        llm = RecordingLLM(personal=(personal_batch(),))
        code_result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
        assert len(code_result.code_fact_ids) == 1
        run = store.record_cycle(code_result)
        origins = [f["origin"] for f in store.fetch_facts(code_result.cycle_id, run)]
        assert origins == ["code"]
    finally:
        store.close()
    reopened = FactStore(db_path=db)
    try:
        assert reopened.runs(result.cycle_id) == [1]
        assert [f["origin"] for f in reopened.fetch_facts(result.cycle_id, 1)] == [
            "model"
        ]
    finally:
        reopened.close()
    replayed = FactStore(db_path=db)
    try:
        assert replayed.record_cycle(result) == 1
        assert replayed.runs(result.cycle_id) == [1]
    finally:
        replayed.close()


def test_concurrent_previous_schema_opens_migrate_once(tmp_path: Path) -> None:
    import sqlite3
    import threading

    result = _model_only_result()
    db = tmp_path / "concurrent.db"
    _write_previous_schema_db(db, result)
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def _open() -> None:
        try:
            barrier.wait(timeout=30)
            store = FactStore(db_path=db)
            try:
                assert store.runs(result.cycle_id) == [1]
            finally:
                store.close()
        except BaseException as exc:  # noqa: BLE001 -- collected and asserted
            errors.append(exc)

    threads = [threading.Thread(target=_open) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(facts)")]
    finally:
        conn.close()
    assert columns.count("origin") == 1


def test_open_migrated_file_needs_no_write_lock(tmp_path: Path) -> None:
    import sqlite3

    result = _model_only_result()
    db = tmp_path / "migrated.db"
    _write_previous_schema_db(db, result)
    migrated = FactStore(db_path=db)
    try:
        assert migrated.runs(result.cycle_id) == [1]
    finally:
        migrated.close()
    holder = sqlite3.connect(db, isolation_level=None)
    try:
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("CREATE TABLE _held (x)")
        # No retry: a migrated file must open while a writer holds the lock.
        store = FactStore(db_path=db)
        try:
            assert store.runs(result.cycle_id) == [1]
        finally:
            store.close()
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_migration_waits_for_a_writer_then_migrates(tmp_path: Path) -> None:
    import sqlite3
    import threading
    import time

    result = _model_only_result()
    db = tmp_path / "migrate-wait.db"
    _write_previous_schema_db(db, result)
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("CREATE TABLE _held (x)")
    errors: list[BaseException] = []

    def _open() -> None:
        try:
            store = FactStore(db_path=db)
            try:
                assert store.runs(result.cycle_id) == [1]
            finally:
                store.close()
        except BaseException as exc:  # noqa: BLE001 -- collected and asserted
            errors.append(exc)

    thread = threading.Thread(target=_open)
    thread.start()
    try:
        # A deferred BEGIN would read first and fail its upgrade to a write
        # at once; BEGIN IMMEDIATE waits for this commit instead.
        time.sleep(0.5)
    finally:
        holder.execute("COMMIT")
        holder.close()
    thread.join(timeout=30)
    assert errors == []
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(facts)")]
    finally:
        conn.close()
    assert columns.count("origin") == 1


def test_second_opener_sees_the_column_the_first_added(tmp_path: Path) -> None:
    import sqlite3
    import threading
    import time

    result = _model_only_result()
    db = tmp_path / "migrate-recheck.db"
    _write_previous_schema_db(db, result)
    holder = sqlite3.connect(db, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("ALTER TABLE facts ADD COLUMN origin TEXT NOT NULL DEFAULT 'model'")
    errors: list[BaseException] = []

    # The first read misses the uncommitted column, so the opener must read
    # again after BEGIN IMMEDIATE or its own ALTER hits duplicate column name.
    def _open() -> None:
        try:
            store = FactStore(db_path=db)
            try:
                assert store.runs(result.cycle_id) == [1]
            finally:
                store.close()
        except BaseException as exc:  # noqa: BLE001 -- collected and asserted
            errors.append(exc)

    thread = threading.Thread(target=_open)
    thread.start()
    try:
        time.sleep(0.5)
    finally:
        holder.execute("COMMIT")
        holder.close()
    thread.join(timeout=30)
    assert errors == []
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(facts)")]
    finally:
        conn.close()
    assert columns.count("origin") == 1


def test_new_cycles_store_origin_code_first(tmp_path: Path) -> None:
    case = base_case()
    llm = RecordingLLM(personal=case.personal_texts, feed=case.feed_texts)
    result = extract_facts(AS_OF, SUBJECT_ID, list(case.events), llm)
    assert len(result.code_fact_ids) == 4
    store = FactStore(db_path=tmp_path / "origin.db")
    try:
        run = store.record_cycle(result)
        origins = [f["origin"] for f in store.fetch_facts(result.cycle_id, run)]
        assert origins == ["code"] * 4 + ["model"] * 3
    finally:
        store.close()
