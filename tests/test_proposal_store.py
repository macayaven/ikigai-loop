"""Ticket 11: proposal store reads, writes, and the first-draft report."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from evals.proposal_cases import BASE_ELIGIBLE, GOOD_DRAFT
from framework.briefing.context import TimeInterval
from framework.proposal.core import (
    AttemptOutcome,
    ProposalResult,
)
from framework.proposal.schemas import FallbackProposal
from framework.store.proposal_store import (
    FIRST_DRAFT_REPORT_SQL,
    ProposalStore,
)

MADRID = ZoneInfo("Europe/Madrid")
SLOT = datetime(2026, 10, 31, 15, 7, 0, tzinfo=MADRID)
HOUR = TimeInterval(
    start=datetime(2026, 10, 31, 15, 15, 0, tzinfo=MADRID),
    end=datetime(2026, 10, 31, 16, 15, 0, tzinfo=MADRID),
)
PARSER = BASE_ELIGIBLE[0]
NOTES = BASE_ELIGIBLE[1]


def _attempt(
    number: int = 1,
    *,
    model: str = "muse-wonder-1.0",
    effort: str = "high",
    codes: tuple[tuple[str, str], ...] = (),
    parsed_ok: bool = True,
    blocked: bool = False,
    finish: str | None = "stop",
) -> AttemptOutcome:
    return AttemptOutcome(
        number=number,
        model_requested=model,
        model_reported="scripted-client",
        effort=effort,
        prompt_hash=f"hash-{number}",
        raw_text=GOOD_DRAFT if not blocked else "",
        parsed_ok=parsed_ok,
        blocked=blocked,
        codes=codes,
        latency_ms=100,
        prompt_tokens=11,
        completion_tokens=13,
        reasoning_tokens=None,
        finish_reason=finish,
    )


def _result(
    kind: str,
    *,
    profile: str = "builder",
    subject: str = "subject-1",
    slot: datetime = SLOT,
    attempts: tuple[AttemptOutcome, ...] = (),
    reasons: tuple[str, ...] = (),
) -> ProposalResult:
    briefing = None
    fallback = None
    if kind == "fallback":
        fallback = FallbackProposal(
            kind="fallback",
            profile_id=profile,
            subject_id=subject,
            slot=slot,
            commitment=NOTES,
            proposed_start=HOUR.start,
            proposed_end=HOUR.end,
            reason_codes=reasons,
        )
    return ProposalResult(
        kind=kind,  # type: ignore[arg-type]
        profile_id=profile,
        subject_id=subject,
        cycle_id="cycle-1",
        run=1,
        slot=slot,
        hour=HOUR,
        briefing=briefing,
        fallback=fallback,
        reason_codes=reasons,
        attempts=attempts,
        cycle_age_s=0.0,
        prompt_hash="hash-1" if attempts else "",
    )


def _store(tmp_path: Path) -> ProposalStore:
    return ProposalStore(db_path=tmp_path / "proposal.db")


def test_triggers_abort_update_and_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.record(
            _result(
                "fallback",
                attempts=(_attempt(),),
                reasons=("FALLBACK_X",),
            ),
            snapshot={},
        )
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("UPDATE proposal_results SET kind='x'")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM proposal_results")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("UPDATE proposal_attempts SET effort='x'")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute("DELETE FROM proposal_attempts")
    finally:
        store.close()


def _proposal_briefing_result() -> ProposalResult:
    from evals.proposal_cases import CASES_BY_NAME, run_case

    return run_case(CASES_BY_NAME["P1"])


def test_latest_proposal_round_trip_and_fallback_never_parent(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    try:
        proposal = _proposal_briefing_result()
        key = store.record(proposal, snapshot={"period.last.pushes": 3.0})
        assert key.startswith("prop-subject-1-builder-")
        store.record(
            _result("fallback", attempts=(_attempt(),), reasons=("FALLBACK_X",)),
            snapshot={},
        )
        found = store.latest_proposal(
            "subject-1", "builder", before_slot=SLOT + timedelta(hours=1)
        )
        assert found is not None
        briefing, snapshot, _ = found
        assert briefing.id == proposal.briefing.id  # type: ignore[union-attr]
        assert snapshot.values == {"period.last.pushes": 3.0}
        assert (
            store.latest_proposal("subject-1", "builder", before_slot=proposal.slot)
            is None
        )
        assert store.latest_proposal("subject-2", "builder", before_slot=SLOT) is None
    finally:
        store.close()


def test_same_slot_rerun_suffix_and_latest_wins(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        first = _result("noop", attempts=(), reasons=("NOOP_NO_FREE_HOUR",))
        second = _result("noop", attempts=(), reasons=("NOOP_NO_FREE_HOUR",))
        key1 = store.record(first, snapshot={})
        key2 = store.record(second, snapshot={})
        assert key1 != key2
        assert key2 == f"{key1}-2"
        key3 = store.record(second, snapshot={})
        assert key3 == f"{key1}-3"
    finally:
        store.close()


def test_last_offered_and_results_for_slot(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.record(
            _result(
                "fallback",
                attempts=(_attempt(),),
                reasons=("FALLBACK_X",),
            ),
            snapshot={},
        )
        offered = store.last_offered_by_commitment("subject-1", "builder")
        assert offered == {"cm-builder-notes": SLOT}
        other = store.last_offered_by_commitment("subject-2", "builder")
        assert other == {}
        (stored,) = store.results_for_slot("subject-1", SLOT)
        assert stored.kind == "fallback"
        assert stored.fallback is not None
        assert stored.reason_codes == ("FALLBACK_X",)
        assert stored.hour == HOUR
        assert store.results_for_slot("subject-2", SLOT) == ()
    finally:
        store.close()


def _a15_fixture(store: ProposalStore) -> None:
    wonder = "muse-wonder-1.0"
    spark = "muse-spark-1.3"
    bad_codes = (("L1B_UNKNOWN_FACT", "sections[overall_state].claims[c-x]"),)
    # pass on wonder/high
    store.record(
        _result("proposal", attempts=(_attempt(model=wonder),)),
        snapshot={},
    )
    # bad-then-good on wonder/high
    store.record(
        _result(
            "proposal",
            attempts=(
                _attempt(model=wonder, codes=bad_codes),
                _attempt(number=2, model=wonder),
            ),
        ),
        snapshot={},
    )
    # bad twice fallback on wonder/high
    store.record(
        _result(
            "fallback",
            attempts=(
                _attempt(model=wonder, codes=bad_codes),
                _attempt(number=2, model=wonder, codes=bad_codes),
            ),
            reasons=("FALLBACK_AFTER_GATE_FAILURE", "L1B_UNKNOWN_FACT"),
        ),
        snapshot={},
    )
    # unparseable on spark/low
    store.record(
        _result(
            "fallback",
            attempts=(
                _attempt(
                    model=spark,
                    effort="low",
                    codes=(("DRAFT_UNPARSEABLE", "draft"),),
                    parsed_ok=False,
                ),
            ),
            reasons=("FALLBACK_UNPARSEABLE",),
        ),
        snapshot={},
    )
    # unavailable on spark/low
    store.record(
        _result(
            "fallback",
            attempts=(
                _attempt(
                    model=spark,
                    effort="low",
                    codes=(("MODEL_UNAVAILABLE", "status 500"),),
                    parsed_ok=False,
                ),
            ),
            reasons=("FALLBACK_MODEL_UNAVAILABLE",),
        ),
        snapshot={},
    )
    # blocked noop on spark/low
    store.record(
        _result(
            "noop",
            attempts=(
                _attempt(
                    model=spark,
                    effort="low",
                    codes=(("L1_RAW_VALUE", "prompt"),),
                    parsed_ok=False,
                    blocked=True,
                ),
            ),
            reasons=("NOOP_OUTBOUND_BLOCKED",),
        ),
        snapshot={},
    )
    # no-free-hour noop, no attempts
    store.record(
        _result("noop", attempts=(), reasons=("NOOP_NO_FREE_HOUR",)),
        snapshot={},
    )


def test_first_draft_report_exact_numbers(tmp_path: Path) -> None:
    assert "proposal_attempts" in FIRST_DRAFT_REPORT_SQL
    assert "proposal_results" in FIRST_DRAFT_REPORT_SQL
    assert "json_each" in FIRST_DRAFT_REPORT_SQL
    store = _store(tmp_path)
    try:
        _a15_fixture(store)
        report = store.first_draft_report()
        by_model = {(m.model, m.effort): m for m in report.models}
        wonder = by_model[("muse-wonder-1.0", "high")]
        assert wonder.first_drafts == 3
        assert wonder.first_draft_passed == 1
        assert wonder.first_draft_failed == 2
        assert wonder.unavailable == 0
        assert wonder.retries == 2
        assert wonder.retry_passed == 1
        assert wonder.fallbacks == 1
        assert wonder.noops == 0
        spark = by_model[("muse-spark-1.3", "low")]
        assert spark.first_drafts == 1
        assert spark.first_draft_passed == 0
        assert spark.first_draft_failed == 1
        assert spark.unavailable == 1
        assert spark.retries == 0
        assert spark.retry_passed == 0
        assert spark.fallbacks == 2
        assert spark.noops == 1
        by_code = {(c.model, c.effort, c.code): c.drafts for c in report.codes}
        assert by_code[("muse-wonder-1.0", "high", "L1B_UNKNOWN_FACT")] == 2
        assert by_code[("muse-spark-1.3", "low", "DRAFT_UNPARSEABLE")] == 1
        assert report.results == 7
        assert report.proposals == 2
        assert report.fallbacks == 3
        assert report.noops == 2
        assert dict(report.noops_by_reason) == {
            "NOOP_OUTBOUND_BLOCKED": 1,
            "NOOP_NO_FREE_HOUR": 1,
        }
    finally:
        store.close()


def test_fetch_latest_cycle_offset_crossing(tmp_path: Path) -> None:
    from framework.briefing.context import MetricSnapshot
    from framework.glimmer.facts import (
        FactResult,
        PassResult,
    )
    from framework.store.fact_store import FactStore

    fact_store = FactStore(db_path=tmp_path / "cycles.db")
    try:
        from datetime import timedelta as _td
        from datetime import timezone as _tz

        as_of_a = datetime(2026, 10, 31, 8, 0, 0, tzinfo=_tz(_td(hours=2)))
        as_of_b = datetime(2026, 10, 31, 7, 0, 0, tzinfo=ZoneInfo("UTC"))
        for cycle_id, as_of in (("cycle-a", as_of_a), ("cycle-b", as_of_b)):
            result = FactResult(
                facts=(),
                code_fact_ids=(),
                snapshot=MetricSnapshot(values={}),
                passes=(
                    PassResult(
                        name="personal",
                        attempts=0,
                        raw_valid=True,
                        model_id="",
                        latency_ms=0,
                        finish_reason=None,
                        completion_tokens=None,
                        kept=0,
                        noop_reason="NOOP_NO_FACTS",
                    ),
                    PassResult(
                        name="feed",
                        attempts=0,
                        raw_valid=True,
                        model_id="",
                        latency_ms=0,
                        finish_reason=None,
                        completion_tokens=None,
                        kept=0,
                        noop_reason="NOOP_NO_FACTS",
                    ),
                ),
                responses=(),
                cycle_id=cycle_id,
                subject_id="subject-1",
                as_of=as_of,
                window_start=as_of - timedelta(hours=72),
                prompt_hash="h",
                dropped=(),
                is_noop=True,
                noop_reason="NOOP_NO_FACTS",
            )
            fact_store.record_cycle(result)
        latest = fact_store.fetch_latest_cycle("subject-1")
        assert latest is not None
        assert latest["cycle_id"] == "cycle-b"
        earlier = fact_store.fetch_latest_cycle("subject-1", not_after=as_of_a)
        assert earlier is not None
        assert earlier["cycle_id"] == "cycle-a"
        assert fact_store.fetch_latest_cycle("subject-2") is None
    finally:
        fact_store.close()
