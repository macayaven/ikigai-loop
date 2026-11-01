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
