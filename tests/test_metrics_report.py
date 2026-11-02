"""Slice B, AT-B1 to AT-B8: the metrics report over made-up stores.

Stores are built through the real writers: ProposalStore.record,
SlotLedger.save_slot_cards/save_card_step/save_card_payload/append_step/
append_learner_state, CardLedger.save_card/save_card_message/record_voice_note,
VoiceLedger.update and EventStore.append_event. Direct SQL is used only
where a test must break an identity (AT-B3) or plant a voice slot stamp.

Covers BD1 (the report command and the make target), BD2 (run scope and
the slot-path/re-proposal split by proposal key), BD3 (the opt-in
proposal-key argument of first_draft_report, delivered cards/sides from
the delivery join, fact disputes), BD4 (identities gating exit code),
BD5 (R7 follow-through), BD6 (before/during), BD7 (R8 learner) and BD8
(bindings, in tests/test_metrics_bindings.py).
"""

from __future__ import annotations

import json
import sqlite3
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.context import TimeInterval
from framework.briefing.schemas import Action, Briefing, Claim, Section
from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
from framework.learner.policy import bucket_for, initial_state, state_json
from framework.proposal.core import AttemptOutcome, ProposalResult
from framework.proposal.schemas import FallbackProposal
from framework.rater.delivery import run_slots
from framework.schemas.events import (
    AppFactDisputeData,
    AppTapData,
    CalendarEventCancelledData,
    CalendarEventCreatedData,
    CalendarLabelData,
    Event,
    FeedItemData,
    GitHubPrData,
    GitHubPushData,
    ScreenHourData,
)
from framework.store.proposal_store import ProposalStore
from framework.store.store import EventStore
from framework.telegram.ledger import CardLedger
from framework.telegram.models import Card as TelegramCard

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-metrics-test"

WONDER = "muse-wonder-1.0"
SPARK = "muse-spark-1.3"

ZEBRA = "ZebraQuill made-up claim text"


def _commitment(
    cid: str,
    profile: str,
    kind: str,
    dimension: str,
    evidence: str,
    *,
    tag: str | None = None,
    title: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": cid,
        "profile_id": profile,
        "title": title or f"Made-up commitment {cid}",
        "kind": kind,
        "dimension": dimension,
        "evidence": evidence,
    }
    if tag is not None:
        entry["tag"] = tag
    return entry


DEFAULT_COMMITMENTS = (
    _commitment("cm-made-up-1", "builder", "write", "world_needs", "tap"),
    _commitment("cm-made-up-2", "disconnect", "rest", "love", "tap"),
)


@pytest.fixture(autouse=True)
def _metrics_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SD3: the report reads subject and commitments the way run-slot does."""
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
    path = tmp_path / "commitments.json"
    path.write_text(json.dumps(list(DEFAULT_COMMITMENTS)), encoding="utf-8")
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(path))


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def _attempt(
    number: int = 1,
    *,
    model: str = WONDER,
    effort: str = "high",
    codes: tuple[tuple[str, str], ...] = (),
    parsed_ok: bool = True,
    blocked: bool = False,
) -> AttemptOutcome:
    return AttemptOutcome(
        number=number,
        model_requested=model,
        model_reported=model,
        effort=effort,
        prompt_hash=f"hash-{number}",
        raw_text="{}" if not blocked else "",
        parsed_ok=parsed_ok,
        blocked=blocked,
        codes=codes,
        latency_ms=3,
        prompt_tokens=None,
        completion_tokens=None,
        reasoning_tokens=None,
        finish_reason="stop",
        cached_tokens=None,
        transport="muse",
        transport_version=None,
        harness_rules_file=None,
    )


def _briefing(bid: str, profile: str, slot: datetime, text: str = ZEBRA) -> Briefing:
    start = slot + timedelta(minutes=30)
    return Briefing(
        id=bid,
        profile_id=profile,
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="overall_state",
                claims=[Claim(id="c-1", text=text, fact_ids=[], metric_refs=[])],
                actions=[],
            ),
            Section(
                type="actions",
                claims=[],
                actions=[
                    Action(
                        id="act-1",
                        commitment_id="cm-made-up-1",
                        kind="write",
                        text="side title",
                        dimension="world_needs",
                        proposed_start=start,
                        proposed_end=start + timedelta(hours=1),
                    )
                ],
            ),
        ],
    )


def _record(
    db: Path,
    kind: str,
    *,
    slot: datetime,
    profile: str = "builder",
    model: str = WONDER,
    effort: str = "high",
    attempts: tuple[AttemptOutcome, ...] | None = None,
    reasons: tuple[str, ...] = (),
    cycle_id: str = "cycle-1",
    run: int = 1,
    text: str = ZEBRA,
) -> str:
    if attempts is None:
        attempts = (_attempt(model=model, effort=effort),)
    briefing = None
    fallback = None
    if kind == "proposal":
        briefing = _briefing(f"brf-{cycle_id}-{run}", profile, slot, text)
    elif kind == "fallback":
        start = slot + timedelta(minutes=30)
        from framework.briefing.schemas import Commitment as _Commitment

        fallback = FallbackProposal(
            kind="fallback",
            profile_id=profile,
            subject_id=SUBJECT,
            slot=slot,
            commitment=_Commitment(
                id="cm-made-up-1",
                profile_id=profile,
                title="Made-up commitment title",
                kind="write",
                dimension="world_needs",
                evidence="tap",
            ),
            proposed_start=start,
            proposed_end=start + timedelta(hours=1),
            reason_codes=reasons,
        )
    store = ProposalStore(db_path=db)
    try:
        return store.record(
            ProposalResult(
                kind=kind,  # type: ignore[arg-type]
                profile_id=profile,  # type: ignore[arg-type]
                subject_id=SUBJECT,
                cycle_id=cycle_id,
                run=run,
                slot=slot,
                hour=TimeInterval(
                    start=slot + timedelta(minutes=30),
                    end=slot + timedelta(hours=1, minutes=30),
                ),
                briefing=briefing,
                fallback=fallback,
                reason_codes=reasons,
                attempts=attempts,
                cycle_age_s=0.0,
                prompt_hash="hash-1" if attempts else "",
            ),
            snapshot={},
        )
    finally:
        store.close()


def _rows(
    card_id: str, slot: datetime, kinds: tuple[str, ...] = ("proposal", "proposal")
) -> tuple[SlotCardRow, ...]:
    profiles = ("builder", "disconnect")
    cids = ("cm-made-up-1", "cm-made-up-2")
    return tuple(
        SlotCardRow(
            card_id=card_id,
            letter=letter,
            slot=slot,
            subject_id=SUBJECT,
            as_of=slot,
            bucket="evening",
            profile_id=profile,
            commitment_id=cid,
            kind=kind,
            policy_pick=None,
            policy_alternative=None,
        )
        for letter, profile, cid, kind in zip("AB", profiles, cids, kinds)
    )


def _deliver(
    db: Path,
    card_id: str,
    slot: datetime,
    *,
    kinds: tuple[str, ...] = ("proposal", "proposal"),
    outcome: str = "delivered",
    message: bool = True,
) -> None:
    _mid[0] += 1
    ledger = SlotLedger(db)
    ledger.save_card_step(
        slot, card_id, {}, _rows(card_id, slot, kinds), "{}", "{}", 0.5
    )
    ledger.append_step(slot, "send", outcome, 0.5, card_id, {})
    if message:
        CardLedger(db).save_card_message(_mid[0], card_id)


_mid = [900000]


def _dispute(db: Path, message_id: int, fact_id: str | None = "f-1") -> None:
    moment = slot_at("15:30")
    if fact_id is None:
        data = AppFactDisputeData(
            metric_id="period.last.pushes",
            metric_value=2.0,
            cycle_id="cycle-1",
            card_id="card-made-up-1",
            message_id=message_id,
            reported_by="user",
        )
    else:
        data = AppFactDisputeData(
            fact_id=fact_id,
            card_id="card-made-up-1",
            message_id=message_id,
            reported_by="user",
        )
    store = EventStore(db)
    try:
        assert store.append_event(
            Event(
                id=f"evt-dispute-{message_id}-{fact_id}",
                subject_id=SUBJECT,
                source="telegram",
                type="app.fact_dispute",
                time=moment,
                source_id=f"voice:{message_id}:{fact_id}",
                data=data,
                tier="private",
                collected_at=moment,
                collector_version="voice-test@0.1.0",
            )
        )
    finally:
        store.close()


def _run_report(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    from framework.metrics.__main__ import main as metrics_main

    code = metrics_main(["report", *argv])
    return code, capsys.readouterr().out


def _parse(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)


def test_run_scope_is_thirteen_pinned_slots() -> None:
    slots = run_slots()
    assert len(slots) == 13
    assert slots[0] == datetime(2026, 11, 2, 13, 30, tzinfo=MADRID)
    assert slots[-1] == datetime(2026, 11, 4, 18, 0, tzinfo=MADRID)


# -- AT-B1: scope, forced/unpinned/outside, re-proposals apart --


def test_forced_unpinned_outside_slots_apart_and_out_of_r1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    run_slot = slot_at("15:30")
    _record(db, "proposal", slot=run_slot, profile="builder")
    # A forced start row at a second run slot: its result must not count.
    forced_slot = slot_at("18:00")
    SlotLedger(db).append_step(forced_slot, "start", "ok", 0.5, None, {"forced": "1"})
    _record(db, "proposal", slot=forced_slot, profile="builder")
    # An unpinned Madrid slot with a send row: counted apart, out of R1.
    unpinned = datetime(2026, 11, 2, 14, 0, tzinfo=MADRID)
    SlotLedger(db).append_step(unpinned, "start", "ok", 0.5, None, {})
    _record(db, "proposal", slot=unpinned, profile="builder")
    # An outside-run pinned slot (Nov 4 20:30): counted apart, out of R1.
    outside = datetime(2026, 11, 4, 20, 30, tzinfo=MADRID)
    SlotLedger(db).append_step(outside, "start", "ok", 0.5, None, {})
    _record(db, "proposal", slot=outside, profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["run.slots"] == "13"
    assert fields["scope.slots_forced"] == "1"
    assert fields["scope.slots_unpinned"] == "1"
    assert fields["scope.slots_outside_run"] == "1"
    # Only the one unforced in-run slot-path result reaches R1.
    assert fields["r1.slot.results"] == "1"
    assert fields["r1.reproposal.results"] == "0"
    assert fields["r1.slot.muse-wonder-1.0.high.first_drafts"] == "1"


def test_reproposals_apart_from_slot_path_by_proposal_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    run_slot = slot_at("15:30")
    bad = (("L1B_UNKNOWN_FACT", "sections[overall_state].claims[c-1]"),)
    # Slot path: failed first draft, retried to a proposal.
    _record(
        db,
        "proposal",
        slot=run_slot,
        profile="builder",
        attempts=(
            _attempt(codes=bad),
            _attempt(number=2),
        ),
    )
    # Re-proposal at the same run slot and profile: passed first draft.
    _record(
        db,
        "proposal",
        slot=run_slot,
        profile="builder",
        attempts=(_attempt(),),
        cycle_id="cycle-2",
    )
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["scope.reproposal_results"] == "1"
    assert fields["r1.slot.muse-wonder-1.0.high.first_failed"] == "1"
    assert fields["r1.slot.muse-wonder-1.0.high.first_passed"] == "0"
    assert fields["r1.reproposal.muse-wonder-1.0.high.first_passed"] == "1"
    assert fields["r1.reproposal.muse-wonder-1.0.high.first_failed"] == "0"


def test_voice_corrected_cards_counted_beside_reproposals(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework.telegram.models import VoiceNote
    from framework.voice.ledger import VoiceLedger

    db = tmp_path / "store.db"
    run_slot = slot_at("15:30")
    _record(db, "proposal", slot=run_slot, profile="builder")
    _record(db, "proposal", slot=run_slot, profile="builder", cycle_id="cycle-2")
    note = VoiceNote(
        message_id=4242,
        date=int(run_slot.timestamp()),
        file_id="synthetic-file-id",
        file_unique_id="uniq-4242",
        duration_s=4,
        mime_type="audio/ogg",
        file_size=4100,
        reply_to_message_id=None,
    )
    assert CardLedger(db).record_voice_note(note, 5001, run_slot.isoformat()) is True
    VoiceLedger(db).update(
        4242, new_card_id="card-made-up-2", slot=run_slot.isoformat()
    )
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["scope.reproposal_results"] == "1"
    assert fields["scope.voice_corrected_cards"] == "1"


# -- AT-B2: R1 blocks, no-arg report unchanged, delivered join --


def _mixed_store(db: Path) -> None:
    # Propose-faithful: every failed reached first draft ran its retry, so
    # retries == first_failed holds the way the BD4 identity requires.
    slot = slot_at("15:30")
    bad = (("L1B_UNKNOWN_FACT", "sections[overall_state].claims[c-1]"),)
    # wonder/high: one clean pass.
    _record(db, "proposal", slot=slot, profile="builder")
    # wonder/high disconnect: bad then good, lands as a proposal.
    _record(
        db,
        "proposal",
        slot=slot,
        profile="disconnect",
        attempts=(_attempt(codes=bad), _attempt(number=2)),
    )
    # Each (slot, profile) holds one row so nothing reads as a re-proposal.
    evening = slot_at("18:00")
    next_day = slot_at("15:30", day=3)
    late = slot_at("20:30")
    # spark/low: unparseable, retry fails again, lands as a fallback.
    _record(
        db,
        "fallback",
        slot=evening,
        profile="builder",
        model=SPARK,
        effort="low",
        attempts=(
            _attempt(
                model=SPARK,
                effort="low",
                codes=(("DRAFT_UNPARSEABLE", "draft"),),
                parsed_ok=False,
            ),
            _attempt(
                number=2,
                model=SPARK,
                effort="low",
                codes=bad,
                parsed_ok=False,
            ),
        ),
        reasons=("FALLBACK_AFTER_GATE_FAILURE",),
        cycle_id="cycle-2",
    )
    # spark/low disconnect: unavailable single attempt, lands as a fallback.
    _record(
        db,
        "fallback",
        slot=evening,
        profile="disconnect",
        model=SPARK,
        effort="low",
        attempts=(
            _attempt(
                model=SPARK,
                effort="low",
                codes=(("MODEL_UNAVAILABLE", "status 500"),),
                parsed_ok=False,
            ),
        ),
        reasons=("FALLBACK_MODEL_UNAVAILABLE",),
        cycle_id="cycle-3",
    )
    # spark/low builder second run: blocked noop with an attempt.
    _record(
        db,
        "noop",
        slot=next_day,
        profile="builder",
        model=SPARK,
        effort="low",
        attempts=(
            _attempt(
                model=SPARK,
                effort="low",
                codes=(("L1_RAW_VALUE", "prompt"),),
                parsed_ok=False,
                blocked=True,
            ),
        ),
        reasons=("NOOP_OUTBOUND_BLOCKED",),
        cycle_id="cycle-4",
        run=2,
    )
    # Attemptless noop at the same next-day slot, other profile.
    _record(
        db,
        "noop",
        slot=next_day,
        profile="disconnect",
        model=SPARK,
        effort="low",
        attempts=(),
        reasons=("NOOP_NO_FREE_HOUR",),
        cycle_id="cycle-5",
        run=2,
    )
    # Attemptless fallback at a late run slot: no attempt-1 row to join.
    _record(
        db,
        "fallback",
        slot=late,
        profile="builder",
        model=SPARK,
        effort="low",
        attempts=(),
        reasons=("FALLBACK_NO_EVIDENCE",),
        cycle_id="cycle-6",
        run=2,
    )


def test_two_r1_blocks_with_codes_and_noop_reasons(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _mixed_store(db)
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["r1.slot.muse-wonder-1.0.high.first_drafts"] == "2"
    assert fields["r1.slot.muse-wonder-1.0.high.first_passed"] == "1"
    assert fields["r1.slot.muse-wonder-1.0.high.first_failed"] == "1"
    assert fields["r1.slot.muse-wonder-1.0.high.retries"] == "1"
    assert fields["r1.slot.muse-wonder-1.0.high.retry_passed"] == "1"
    assert fields["r1.slot.muse-spark-1.3.low.unavailable"] == "1"
    assert fields["r1.slot.muse-spark-1.3.low.fallbacks"] == "2"
    assert fields["fallbacks.without_attempt1"] == "1"
    assert fields["r1.slot.code.muse-wonder-1.0.high.L1B_UNKNOWN_FACT"] == "1"
    assert fields["r1.slot.noop_reason.NOOP_OUTBOUND_BLOCKED"] == "1"
    assert fields["r1.slot.noop_reason.NOOP_NO_FREE_HOUR"] == "1"
    # No re-proposals yet: the second block is present but empty.
    assert fields["r1.reproposal.results"] == "0"
    assert fields["r1.slot.results"] == "7"


def test_first_draft_report_no_argument_is_byte_identical(tmp_path: Path) -> None:
    db = tmp_path / "store.db"
    _mixed_store(db)
    store = ProposalStore(db_path=db)
    try:
        default = store.first_draft_report()
        conn = store._conn
        keys = frozenset(
            row[0] for row in conn.execute("SELECT proposal_key FROM proposal_results")
        )
        assert len(keys) == 7
        restricted = store.first_draft_report(proposal_keys=keys)
        assert restricted == default
        assert store.first_draft_report(proposal_keys=None) == default
    finally:
        store.close()


def test_delivered_cards_and_sides_come_from_the_join(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    _record(db, "proposal", slot=slot, profile="builder")
    _deliver(db, "card-made-up-1", slot, kinds=("proposal", "fallback"))
    # Undelivered payload: saved but never sent, counts nowhere as delivered.
    SlotLedger(db).save_card_step(
        slot, "card-made-up-9", {}, _rows("card-made-up-9", slot), "{}", "{}", 0.5
    )
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["delivered.cards"] == "1"
    assert fields["delivered.sides"] == "2"
    assert fields["delivered.sides_proposal"] == "1"
    assert fields["delivered.sides_fallback"] == "1"


# -- AT-B3: identities hold and break --


def _holding_store(db: Path) -> None:
    slot = slot_at("15:30")
    bad = (("L1B_UNKNOWN_FACT", "sections[overall_state].claims[c-1]"),)
    # wonder/high: one clean pass.
    _record(db, "proposal", slot=slot, profile="builder")
    # wonder/high disconnect: failed first draft, retry lands a proposal.
    _record(
        db,
        "proposal",
        slot=slot,
        profile="disconnect",
        attempts=(_attempt(codes=bad), _attempt(number=2)),
    )
    # wonder/high next day: failed first draft, retry comes back unavailable.
    _record(
        db,
        "fallback",
        slot=slot_at("18:00"),
        profile="builder",
        attempts=(
            _attempt(codes=bad),
            _attempt(
                number=2,
                codes=(("MODEL_UNAVAILABLE", "status 500"),),
                parsed_ok=False,
            ),
        ),
        reasons=("FALLBACK_MODEL_UNAVAILABLE",),
        cycle_id="cycle-2",
    )
    # wonder/high day three: failed first draft, retry stopped by the scan.
    _record(
        db,
        "noop",
        slot=slot_at("15:30", day=3),
        profile="builder",
        attempts=(
            _attempt(codes=bad),
            _attempt(
                number=2,
                codes=(("L1_RAW_VALUE", "prompt"),),
                parsed_ok=False,
                blocked=True,
            ),
        ),
        reasons=("NOOP_OUTBOUND_BLOCKED",),
        cycle_id="cycle-3",
    )


def _identity_lines(fields: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in fields.items() if k.startswith("identity.")}


def test_identities_hold_on_a_clean_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _holding_store(db)
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    identities = _identity_lines(fields)
    assert identities, out
    oks = {k: v for k, v in fields.items() if k.endswith(".ok")}
    assert oks, out
    assert set(oks.values()) == {"1"}
    # Both sides of each identity are printed.
    lefts = {k: v for k, v in fields.items() if k.endswith(".left")}
    rights = {k: v for k, v in fields.items() if k.endswith(".right")}
    assert lefts and len(lefts) == len(rights) == len(oks)
    # The retry that came back unavailable is not a pass or a fallback.
    assert fields["retry.unavailable"] == "1"
    assert fields["retry.blocked"] == "1"
    assert fields["retry.fell_back"] == "0"
    assert fields["identity.retry_partition.left"] == "3"
    assert fields["identity.retry_partition.right"] == "3"


def _clone_attempt(conn: sqlite3.Connection, number: int, new_number: int) -> None:
    columns = [row[1] for row in conn.execute("PRAGMA table_info(proposal_attempts)")]
    row = conn.execute(
        "SELECT * FROM proposal_attempts WHERE attempt = ? AND proposal_key"
        " NOT IN (SELECT proposal_key FROM proposal_attempts WHERE attempt = ?)"
        " LIMIT 1",
        (number, new_number),
    ).fetchone()
    assert row is not None
    values = list(row)
    values[columns.index("attempt")] = new_number
    conn.execute(
        f"INSERT INTO proposal_attempts ({', '.join(columns)})"
        f" VALUES ({', '.join(['?'] * len(columns))})",
        values,
    )
    conn.commit()


def _break_with_extra_attempt2(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        _clone_attempt(conn, 1, 2)
    finally:
        conn.close()


def test_identity_breaks_on_attempt2_after_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _holding_store(db)
    _break_with_extra_attempt2(db)
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 1, out
    fields = _parse(out)
    assert fields["identity.retries_eq_failed.muse-wonder-1.0.high.ok"] == "0"
    assert (
        fields["identity.retries_eq_failed.muse-wonder-1.0.high.left"]
        != fields["identity.retries_eq_failed.muse-wonder-1.0.high.right"]
    )


def test_identity_breaks_on_third_attempt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _holding_store(db)
    conn = sqlite3.connect(db)
    try:
        _clone_attempt(conn, 2, 3)
    finally:
        conn.close()
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 1, out
    fields = _parse(out)
    assert fields["identity.attempts_per_key_le_2.ok"] == "0"


# -- AT-B4: fact disputes --


def test_fact_disputes_counted_with_distinct_notes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    _dispute(db, 11, "f-1")
    _dispute(db, 12, None)
    _dispute(db, 12, "f-9")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["disputes.fact_dispute_events"] == "3"
    assert fields["disputes.fact_dispute_notes"] == "2"


# -- AT-B8: the command, the make target, counts only --


def test_report_prints_counts_only_and_marks_next_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    _record(db, "proposal", slot=slot, profile="builder", text=ZEBRA)
    _dispute(db, 21, "f-1")
    _deliver(db, "card-made-up-1", slot)
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    assert ZEBRA not in out
    assert "cm-made-up-1" not in out
    assert "Made-up commitment title" not in out
    assert "card-made-up-1" not in out
    assert "Pushes were" not in out
    fields = _parse(out)
    assert "report.sections_pending" not in fields
    assert fields["run.slots"] == "13"


def test_json_guard_inside_tree_refuses_and_outside_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    repo_root = Path(__file__).resolve().parents[1]
    code, _ = _run_report(
        capsys, "--db", str(db), "--json", str(repo_root / "tmp-metrics-inside.json")
    )
    assert code == 2
    assert not (repo_root / "tmp-metrics-inside.json").exists()
    target = tmp_path / "report.json"
    code, _ = _run_report(capsys, "--db", str(db), "--json", str(target))
    assert code == 0
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["delivered.cards"] == "0"
    assert "report.sections_pending" not in payload


def test_scope_always_prints_as_of_and_evidence_cut(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["scope.as_of"] != ""
    assert fields["scope.evidence_cut"] != ""
    code, out = _run_report(capsys, "--db", str(db), "--as-of", EARLY_AS_OF)
    assert code == 0, out
    fields = _parse(out)
    assert fields["scope.as_of"] == EARLY_AS_OF
    assert fields["scope.evidence_cut"] == EARLY_AS_OF


def test_json_guard_inside_any_git_tree_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    other = tmp_path / "other-clone"
    other.mkdir()
    (other / ".git").mkdir()
    inside = other / "report.json"
    code, _ = _run_report(capsys, "--db", str(db), "--json", str(inside))
    assert code == 2
    assert not inside.exists()


def test_json_guard_reuses_rater_git_tree_rule() -> None:
    import framework.metrics.__main__ as metrics_main
    from framework.rater import delivery as rater_delivery

    assert metrics_main.inside_git_tree is rater_delivery.inside_git_tree


def test_make_metrics_target_exists() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "Makefile").read_text(encoding="utf-8")
    assert "metrics:" in text
    assert "framework.metrics report" in text
    assert "METRICS_ARGS" in text


def test_missing_db_is_a_usage_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = _run_report(capsys, "--db", str(tmp_path / "absent.db"))
    assert code == 2


# -- Slice B second half: SD3 env, BD5 R7, BD6 before/during, BD7 R8 --

LATE_AS_OF = "2026-11-05T00:00:00+01:00"
EARLY_AS_OF = "2026-11-03T12:00:00+01:00"

R7_COMMITMENTS = (
    _commitment(
        "cm-b-ship",
        "builder",
        "build",
        "good_at",
        "github_push",
        title="Made-up ship commitment",
    ),
    _commitment(
        "cm-d-rest",
        "disconnect",
        "rest",
        "love",
        "no_screen",
        title="Made-up rest commitment",
    ),
    _commitment(
        "cm-b-cal",
        "builder",
        "build",
        "good_at",
        "calendar_tag",
        tag="iki-family",
        title="Made-up family build",
    ),
    _commitment(
        "cm-b-tap",
        "builder",
        "write",
        "world_needs",
        "tap",
        title="Made-up write commitment",
    ),
)


def _use_commitments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entries: object = R7_COMMITMENTS
) -> None:
    path = tmp_path / "r7-commitments.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(path))


def _two_goal_card(
    slot: datetime,
    start: datetime,
    end: datetime,
    *,
    cids: tuple[str, str] = ("cm-b-tap", "cm-made-up-2"),
    titles: tuple[str, str] = ("Made-up builder hour", "Made-up disconnect hour"),
    statements: tuple[str, ...] = (),
    replaces: str | None = None,
) -> TelegramCard:
    sides = tuple(
        {
            "letter": letter,
            "kind": "proposal",
            "profile": profile,
            "title": title,
            "start": start,
            "end": end,
        }
        for letter, profile, title in zip("AB", ("Builder", "Disconnect"), titles)
    )
    return TelegramCard(
        slot=slot,
        since_line="Since made-up.",
        proposals=sides,  # type: ignore[arg-type]
        statements=statements,
        replaces_card_id=replaces,
    )


def _seed_card(
    db: Path,
    card: TelegramCard,
    *,
    cids: tuple[str, str] = ("cm-b-tap", "cm-made-up-2"),
    delivered: bool = True,
) -> None:
    _mid[0] += 1
    bucket = bucket_for(card.slot.astimezone(MADRID).timetz())
    sides = tuple(
        SlotCardRow(
            card_id=card.card_id,
            letter=side.letter,
            slot=card.slot,
            subject_id=SUBJECT,
            as_of=card.slot,
            bucket=bucket,
            profile_id=profile,
            commitment_id=cid,
            kind=side.kind,
            policy_pick=cid,
            policy_alternative=other,
        )
        for side, profile, cid, other in zip(
            card.proposals,
            ("builder", "disconnect"),
            cids,
            (cids[1], cids[0]),
        )
    )
    ledger = SlotLedger(db)
    ledger.save_slot_cards(sides)
    ledger.save_card_payload(card.card_id, card.model_dump_json(), "{}")
    CardLedger(db).save_card(card)
    if delivered:
        ledger.append_step(card.slot, "send", "delivered", 0.5, card.card_id, {})
        CardLedger(db).save_card_message(_mid[0], card.card_id)


def _tap(db: Path, card_id: str, target: str, when: datetime, eid: str) -> None:
    EventStore(db).append_event(
        Event(
            id=eid,
            subject_id=SUBJECT,
            source="telegram",
            type="app.tap",
            time=when,
            source_id=f"tap-{eid}",
            data=AppTapData(block_id=card_id, target=target),
            tier="private",
            collected_at=when,
            collector_version="telegram-test@0.1.0",
        )
    )


def _r7_run(
    capsys: pytest.CaptureFixture[str], db: Path, *extra: str
) -> dict[str, str]:
    code, out = _run_report(capsys, "--db", str(db), "--as-of", LATE_AS_OF, *extra)
    assert code == 0, out
    return _parse(out)


def test_missing_subject_id_refuses_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IKIGAI_SUBJECT_ID")
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 2
    assert "ZebraQuill" not in out


def test_missing_commitments_file_refuses_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("IKIGAI_COMMITMENTS_FILE")
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 2
    assert "ZebraQuill" not in out


def test_unreadable_commitments_refuses_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(tmp_path / "absent.json"))
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 1
    assert "ZebraQuill" not in out


# -- AT-B5: R7 per evidence class --


def _screen(
    db: Path,
    eid: str,
    device: Literal["mac", "iphone"],
    hour: datetime,
    minutes: dict[str, float],
    *,
    version: str = "activitywatch@0.2.0",
) -> None:
    EventStore(db).append_event(
        Event(
            id=eid,
            subject_id=SUBJECT,
            source="activitywatch",
            type="screen.hour",
            time=hour,
            source_id=f"{device}:{hour.isoformat()}:{eid}",
            data=ScreenHourData(device=device, minutes_by_category=minutes),
            tier="private",
            collected_at=hour,
            collector_version=version,
        )
    )


def _push(
    db: Path, eid: str, when: datetime, repo: str, *, opened_pr: bool = False
) -> None:
    if opened_pr:
        EventStore(db).append_event(
            Event(
                id=eid,
                subject_id=SUBJECT,
                source="github",
                type="github.pr",
                time=when,
                source_id=f"pr-{eid}",
                data=GitHubPrData(repo=repo, counts={"opened": 1}),
                tier="public",
                collected_at=when,
                collector_version="github-test@0.1.0",
            )
        )
    else:
        EventStore(db).append_event(
            Event(
                id=eid,
                subject_id=SUBJECT,
                source="github",
                type="github.push",
                time=when,
                source_id=f"push-{eid}",
                data=GitHubPushData(repo=repo, counts={"commits": 1}),
                tier="public",
                collected_at=when,
                collector_version="github-test@0.1.0",
            )
        )


def _calendar(
    db: Path,
    eid: str,
    uid: str,
    start: datetime,
    end: datetime,
    *,
    cancelled: bool = False,
    tags: tuple[str, ...] = ("iki-family",),
    collected: datetime | None = None,
) -> str:
    stamp = "stamp-1"
    source_id = f"{uid}@rid-1@{stamp}" + ("#cancelled" if cancelled else "")
    etype = "calendar.event.cancelled" if cancelled else "calendar.event.created"
    EventStore(db).append_event(
        Event(
            id=eid,
            subject_id=SUBJECT,
            source="calendar-personal",
            type=etype,  # type: ignore[arg-type]
            time=start,
            source_id=source_id,
            data=(
                CalendarEventCancelledData(
                    start=start,
                    end=end,
                    busy=True,
                    category="personal",
                    tags=list(tags),
                    is_new=False,
                )
                if cancelled
                else CalendarEventCreatedData(
                    start=start,
                    end=end,
                    busy=True,
                    category="personal",
                    tags=list(tags),
                    is_new=False,
                )
            ),
            tier="private",
            collected_at=collected or start,
            collector_version="calendar-test@0.1.0",
        )
    )
    return eid


def test_r7_github_push_completed_and_this_repo_never_counts(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-ship", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-ship", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _push(db, "evt-push-1", start + timedelta(minutes=30), "other/repo")
    _push(db, "evt-push-2", start + timedelta(minutes=45), "macayaven/ikigai-loop")
    fields = _r7_run(capsys, db)
    assert fields["r7.github_push.accepted"] == "1"
    assert fields["r7.github_push.completed"] == "1"
    assert fields["r7.github_push.not_completed"] == "0"
    assert fields["r7.github_push.unknown"] == "0"
    assert fields["r7.github_push.completed_note"] == "consistent with completion"


def test_r7_this_repo_push_alone_never_completes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-ship", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-ship", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _push(db, "evt-push-1", start + timedelta(minutes=30), "macayaven/ikigai-loop")
    fields = _r7_run(capsys, db)
    assert fields["r7.github_push.completed"] == "0"
    assert fields["r7.github_push.not_completed"] == "1"


def test_r7_opened_pr_without_push_is_branch_push_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-ship", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-ship", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _push(db, "evt-pr-1", start + timedelta(minutes=30), "other/repo", opened_pr=True)
    fields = _r7_run(capsys, db)
    assert fields["r7.github_push.unknown"] == "1"
    assert fields["r7.github_push.unknown.branch_push_possible"] == "1"
    assert fields["r7.github_push.completed"] == "0"


def test_r7_no_screen_completed_names_observed_devices(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("18:00")
    start = datetime(2026, 11, 2, 19, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 20, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-made-up-1", "cm-d-rest"))
    _seed_card(db, card, cids=("cm-made-up-1", "cm-d-rest"))
    _tap(db, card.card_id, "B", slot + timedelta(hours=1), "evt-tap-1")
    first = datetime(2026, 11, 2, 18, 0, tzinfo=ZoneInfo("UTC"))
    later = datetime(2026, 11, 2, 19, 0, tzinfo=ZoneInfo("UTC"))
    for device in ("mac", "iphone"):
        _screen(db, f"evt-{device}-1", device, first, {"code": 0.0})
        _screen(db, f"evt-{device}-2", device, later, {"code": 0.0})
    fields = _r7_run(capsys, db)
    assert fields["r7.no_screen.accepted"] == "1"
    assert fields["r7.no_screen.completed"] == "1"
    assert fields["r7.no_screen.unknown"] == "0"
    assert "mac" in fields["r7.no_screen.completed_note"]
    assert "iphone" in fields["r7.no_screen.completed_note"]


def test_r7_no_screen_activity_is_not_completed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("18:00")
    start = datetime(2026, 11, 2, 19, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 20, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-made-up-1", "cm-d-rest"))
    _seed_card(db, card, cids=("cm-made-up-1", "cm-d-rest"))
    _tap(db, card.card_id, "B", slot + timedelta(hours=1), "evt-tap-1")
    first = datetime(2026, 11, 2, 18, 0, tzinfo=ZoneInfo("UTC"))
    later = datetime(2026, 11, 2, 19, 0, tzinfo=ZoneInfo("UTC"))
    _screen(db, "evt-mac-1", "mac", first, {"code": 30.0})
    _screen(db, "evt-mac-2", "mac", later, {"code": 0.0})
    _screen(db, "evt-iphone-1", "iphone", first, {"code": 0.0})
    _screen(db, "evt-iphone-2", "iphone", later, {"code": 0.0})
    fields = _r7_run(capsys, db)
    assert fields["r7.no_screen.not_completed"] == "1"
    assert fields["r7.no_screen.system_only_hours"] == "0"


def test_r7_no_screen_unobserved_device_is_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("18:00")
    start = datetime(2026, 11, 2, 19, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 20, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-made-up-1", "cm-d-rest"))
    _seed_card(db, card, cids=("cm-made-up-1", "cm-d-rest"))
    _tap(db, card.card_id, "B", slot + timedelta(hours=1), "evt-tap-1")
    first = datetime(2026, 11, 2, 18, 0, tzinfo=ZoneInfo("UTC"))
    later = datetime(2026, 11, 2, 19, 0, tzinfo=ZoneInfo("UTC"))
    _screen(db, "evt-mac-1", "mac", first, {"code": 0.0})
    _screen(db, "evt-mac-2", "mac", later, {"code": 0.0})
    fields = _r7_run(capsys, db)
    assert fields["r7.no_screen.unknown"] == "1"
    assert fields["r7.no_screen.unknown.device_unobserved"] == "1"
    assert fields["r7.no_screen.not_completed"] == "0"


def test_r7_no_screen_system_only_still_not_completed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("18:00")
    start = datetime(2026, 11, 2, 19, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 20, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-made-up-1", "cm-d-rest"))
    _seed_card(db, card, cids=("cm-made-up-1", "cm-d-rest"))
    _tap(db, card.card_id, "B", slot + timedelta(hours=1), "evt-tap-1")
    first = datetime(2026, 11, 2, 18, 0, tzinfo=ZoneInfo("UTC"))
    later = datetime(2026, 11, 2, 19, 0, tzinfo=ZoneInfo("UTC"))
    for device in ("mac", "iphone"):
        _screen(db, f"evt-{device}-1", device, first, {"system": 10.0})
        _screen(db, f"evt-{device}-2", device, later, {"system": 0.0})
    fields = _r7_run(capsys, db)
    assert fields["r7.no_screen.not_completed"] == "1"
    assert fields["r7.no_screen.system_only_hours"] == "1"


def test_r7_calendar_tag_overlap_completes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-cal", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-cal", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _calendar(db, "evt-cal-1", "uid-1", start, end)
    fields = _r7_run(capsys, db)
    assert fields["r7.calendar_tag.accepted"] == "1"
    assert fields["r7.calendar_tag.completed"] == "1"


def test_r7_cancelled_only_tag_never_completes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-cal", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-cal", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _calendar(db, "evt-cal-1", "uid-1", start, end, cancelled=True)
    fields = _r7_run(capsys, db)
    assert fields["r7.calendar_tag.completed"] == "0"
    assert fields["r7.calendar_tag.not_completed"] == "1"


def test_r7_label_overlay_tags_and_tap_accepted_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-cal", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-cal", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _calendar(db, "evt-cal-1", "uid-1", start, end, tags=())
    EventStore(db).append_event(
        Event(
            id="evt-label-1",
            subject_id=SUBJECT,
            source="calendar-label",
            type="calendar.label",
            time=start,
            source_id="label-evt-cal-1",
            data=CalendarLabelData(
                target_event_id="evt-cal-1",
                label="iki-family",
                label_source="local_model",
                model_id="local-test@0.1.0",
                valid=True,
            ),
            tier="private",
            collected_at=start,
            collector_version="label-test@0.1.0",
        )
    )
    fields = _r7_run(capsys, db)
    assert fields["r7.calendar_tag.completed"] == "1"


def test_r7_tap_commitment_is_accepted_only(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end)
    _seed_card(db, card)
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    fields = _r7_run(capsys, db)
    assert fields["r7.tap.accepted"] == "1"
    assert fields["r7.tap.completed"] == "0"
    assert fields["r7.tap.not_completed"] == "0"
    assert fields["r7.tap.unknown"] == "0"


def test_r7_window_past_cut_is_right_censored(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("18:00", day=4)
    start = datetime(2026, 11, 4, 18, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 4, 19, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end, cids=("cm-b-ship", "cm-made-up-2"))
    _seed_card(db, card, cids=("cm-b-ship", "cm-made-up-2"))
    _tap(db, card.card_id, "A", start + timedelta(minutes=90), "evt-tap-1")
    _push(db, "evt-push-1", start + timedelta(minutes=30), "other/repo")
    fields = _r7_run(capsys, db)
    assert fields["r7.github_push.unknown"] == "1"
    assert fields["r7.github_push.unknown.right_censored"] == "1"
    assert fields["r7.github_push.completed"] == "0"


def test_r7_accepted_chain_with_unknown_commitment_is_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end)
    _seed_card(db, card, cids=("cm-made-up-unknown", "cm-made-up-2"))
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    fields = _r7_run(capsys, db)
    assert fields["r7.accepted_commitment_unknown"] == "1"
    assert fields["r7.tap.accepted"] == "0"


def test_r7_accepted_chain_with_unreadable_hour_is_counted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    _deliver(db, "card-made-up-hour", slot)
    _tap(db, "card-made-up-hour", "A", slot + timedelta(hours=2), "evt-tap-1")
    fields = _r7_run(capsys, db)
    assert fields["r7.accepted_hour_unknown"] == "1"
    assert fields["r7.tap.accepted"] == "0"


def test_r7_corrected_chain_counts_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    old = _two_goal_card(slot, start, end, cids=("cm-b-ship", "cm-made-up-2"))
    _seed_card(db, old, cids=("cm-b-ship", "cm-made-up-2"))
    new = _two_goal_card(
        slot, start, end, cids=("cm-b-ship", "cm-made-up-2"), replaces=old.card_id
    )
    _seed_card(db, new, cids=("cm-b-ship", "cm-made-up-2"))
    _tap(db, new.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    _push(db, "evt-push-1", start + timedelta(minutes=30), "other/repo")
    fields = _r7_run(capsys, db)
    assert fields["r7.github_push.accepted"] == "1"
    assert fields["r7.github_push.completed"] == "1"


def test_r7_json_keeps_verdicts_separate(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_commitments(tmp_path, monkeypatch)
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    start = datetime(2026, 11, 2, 16, 0, tzinfo=MADRID)
    end = datetime(2026, 11, 2, 17, 0, tzinfo=MADRID)
    card = _two_goal_card(slot, start, end)
    _seed_card(db, card)
    _tap(db, card.card_id, "A", slot + timedelta(hours=2), "evt-tap-1")
    target = tmp_path / "report.json"
    code, _ = _run_report(
        capsys, "--db", str(db), "--as-of", LATE_AS_OF, "--json", str(target)
    )
    assert code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    for cls in ("github_push", "no_screen", "calendar_tag", "tap"):
        for verdict in ("accepted", "completed", "not_completed", "unknown"):
            assert f"r7.{cls}.{verdict}" in payload


# -- AT-B5: the before/during table --


def test_before_during_extent_and_labels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:

    db = tmp_path / "store.db"
    utc = UTC
    EventStore(db).append_event(
        Event(
            id="evt-feed-early",
            subject_id=SUBJECT,
            source="build-feed",
            type="feed.item",
            time=datetime(2026, 10, 25, 9, 0, tzinfo=utc),
            source_id="feed-early",
            data=FeedItemData(
                title="Made-up item",
                url="https://example.invalid/x",
                source="hf",
                score=1.0,
            ),
            tier="public",
            collected_at=datetime(2026, 10, 25, 9, 0, tzinfo=utc),
            collector_version="feed-test@0.1.0",
        )
    )
    _screen(
        db,
        "evt-scr-1",
        "mac",
        datetime(2026, 10, 30, 10, 0, tzinfo=utc),
        {"code": 60.0},
        version="activitywatch@0.1.0",
    )
    _push(db, "evt-push-1", datetime(2026, 10, 31, 12, 0, tzinfo=utc), "other/repo")
    _push(
        db,
        "evt-push-2",
        datetime(2026, 11, 2, 14, 0, tzinfo=utc),
        "macayaven/ikigai-loop",
    )
    _screen(
        db,
        "evt-scr-2",
        "mac",
        datetime(2026, 11, 2, 14, 0, tzinfo=utc),
        {"code": 0.0},
        version="activitywatch@0.2.0",
    )
    code, out = _run_report(capsys, "--db", str(db), "--as-of", EARLY_AS_OF)
    assert code == 0, out
    fields = _parse(out)
    assert (
        fields["beforeduring.periods"] == "before_4,before_3,before_2,before_1,during_0"
    )
    assert fields["beforeduring.during_0.hours"] == "23"
    assert fields["beforeduring.before_4.hours"] == "24"
    assert fields["beforeduring.before_2.pushes_other_repos"] == "1"
    assert fields["beforeduring.during_0.pushes_this_repo"] == "1"
    assert fields["beforeduring.during_0.pushes_other_repos"] == "0"
    assert fields["beforeduring.before_4.screen_activity_hours"] == "1"
    assert fields["beforeduring.before_4.screen_unknown_hours"] == "23"
    assert fields["beforeduring.before_4.screen_free_clock_hours"] == "0"
    assert fields["beforeduring.first_observed_mac"] == "2026-10-30T10:00:00+00:00"
    assert fields["beforeduring.first_observed_iphone"] == "none"
    assert (
        fields["beforeduring.screen_rows_by_collector_version.activitywatch@0.1.0"]
        == "1"
    )
    assert (
        fields["beforeduring.screen_rows_by_collector_version.activitywatch@0.2.0"]
        == "1"
    )


def test_before_during_ends_at_the_whole_hour_before_as_of(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    code, out = _run_report(
        capsys, "--db", str(db), "--as-of", "2026-11-02T15:36:00+01:00"
    )
    assert code == 0, out
    fields = _parse(out)
    assert fields["beforeduring.periods"] == "during_0"
    assert fields["beforeduring.during_0.hours"] == "2"


# -- AT-B6: R8 rebuild, scores, diff, forecast, recovery --


def _two_goal_db(db: Path, slot: datetime, eid_prefix: str) -> TelegramCard:
    start = slot + timedelta(minutes=30)
    end = start + timedelta(hours=1)
    card = _two_goal_card(slot, start, end)
    _seed_card(db, card)
    return card


def test_r8_rebuild_matches_stored_state(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    SlotLedger(db).append_learner_state(slot_at("15:30"), state_json(initial_state()))
    fields = _r7_run(capsys, db)
    assert fields["r8.learner_state_mismatch"] == "0"
    assert fields["r8.learner_rulings_skipped"] == "0"


def test_r8_rebuild_mismatch_and_skipped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    card = _two_goal_db(db, slot_at("15:30"), "x")
    _tap(db, card.card_id, "A", slot_at("15:30") + timedelta(hours=2), "evt-tap-1")
    _tap(db, "card-made-up-unknown", "A", slot_at("15:30"), "evt-tap-2")
    stored_slot = slot_at("18:00")
    SlotLedger(db).append_step(
        stored_slot,
        "start",
        "ok",
        0.5,
        None,
        {"as_of": (stored_slot - timedelta(minutes=30)).isoformat()},
    )
    SlotLedger(db).append_learner_state(stored_slot, state_json(initial_state()))
    fields = _r7_run(capsys, db)
    assert fields["r8.learner_state_mismatch"] == "1"
    assert fields["r8.learner_rulings_skipped"] == "1"


def _prefix_state(db: Path, stored_slot: datetime, start_as_of: datetime):  # type: ignore[no-untyped-def]
    """The like-with-like state: cards before the slot, taps up to as_of."""
    from framework.cycle.orchestrator import rebuild_state, replaces_map

    ledger = SlotLedger(db)
    rows = tuple(row for row in ledger.all_slot_cards() if row.slot < stored_slot)
    store = EventStore(db)
    try:
        taps = sorted(
            (
                event
                for event in store.events_between(
                    SUBJECT,
                    datetime(2026, 1, 1, tzinfo=UTC),
                    datetime(2027, 1, 1, tzinfo=UTC),
                )
                if event.type == "app.tap"
            ),
            key=lambda event: (event.time, event.id),
        )
    finally:
        store.close()
    prefix = [event for event in taps if event.time <= start_as_of]
    state, _ = rebuild_state(prefix, rows, replaces_map(db, rows))
    return state


def test_r8_tap_after_stored_state_shows_no_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    card = _two_goal_db(db, slot_at("15:30"), "x")
    _tap(db, card.card_id, "A", slot_at("15:30") + timedelta(minutes=30), "evt-tap-1")
    stored_slot = slot_at("18:00")
    start_as_of = stored_slot - timedelta(minutes=30)
    SlotLedger(db).append_step(
        stored_slot, "start", "ok", 0.5, None, {"as_of": start_as_of.isoformat()}
    )
    SlotLedger(db).append_learner_state(
        stored_slot, state_json(_prefix_state(db, stored_slot, start_as_of))
    )
    # A tap after the stored state's slot: the full replay folds it in,
    # but the like-with-like comparison still matches.
    _tap(db, card.card_id, "A", stored_slot + timedelta(hours=1), "evt-tap-2")
    fields = _r7_run(capsys, db)
    assert fields["r8.learner_state_mismatch"] == "0"
    assert fields["r8.learner_state_pending_taps"] == "1"
    assert fields["r8.learner_rulings_skipped"] == "0"


def test_r8_stored_state_that_really_differs_shows_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    card = _two_goal_db(db, slot_at("15:30"), "x")
    _tap(db, card.card_id, "A", slot_at("15:30") + timedelta(minutes=30), "evt-tap-1")
    stored_slot = slot_at("18:00")
    SlotLedger(db).append_step(
        stored_slot,
        "start",
        "ok",
        0.5,
        None,
        {"as_of": (stored_slot - timedelta(minutes=30)).isoformat()},
    )
    SlotLedger(db).append_learner_state(stored_slot, state_json(initial_state()))
    fields = _r7_run(capsys, db)
    assert fields["r8.learner_state_mismatch"] == "1"
    assert fields["r8.learner_state_pending_taps"] == "0"


def test_r8_scores_primary_brier_and_clipping_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    card = _two_goal_db(db, slot_at("15:30"), "x")
    _tap(db, card.card_id, "A", slot_at("15:30") + timedelta(hours=2), "evt-tap-1")
    other = _two_goal_db(db, slot_at("15:30", day=3), "y")
    _tap(
        db,
        other.card_id,
        "A",
        slot_at("15:30", day=3) + timedelta(hours=2),
        "evt-tap-2",
    )
    fields = _r7_run(capsys, db)
    assert fields["r8.scores.n"] == "2"
    learner = float(fields["r8.scores.learner.brier"])
    half = float(fields["r8.scores.always_half.brier"])
    pooled = float(fields["r8.scores.pooled_rate.brier"])
    assert learner < half
    assert pooled < half
    for predictor in ("learner", "always_half", "majority", "pooled_rate"):
        assert float(fields[f"r8.scores.{predictor}.log_loss"]) >= 0.0
    assert "0.01" in fields["r8.scoring_note"]
    assert "0.99" in fields["r8.scoring_note"]


def test_r8_policy_diff_counts_top_level_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    card = _two_goal_db(db, slot_at("15:30"), "x")
    _tap(db, card.card_id, "A", slot_at("15:30") + timedelta(hours=2), "evt-tap-1")
    fields = _r7_run(capsys, db)
    assert int(fields["r8.policy_diff.buckets"]) > 0
    assert int(fields["r8.policy_diff.commitments"]) > 0
    assert int(fields["r8.policy_diff.duplicates"]) == 0


def test_r8_forecast_actual_neither_untapped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    winner_a = _two_goal_db(db, slot, "a")
    _tap(db, winner_a.card_id, "A", slot + timedelta(hours=2), "evt-tap-a")
    winner_b = _two_goal_db(db, slot_at("20:30"), "b")
    _tap(db, winner_b.card_id, "B", slot + timedelta(hours=3), "evt-tap-b")
    neither = _two_goal_db(db, slot_at("22:30"), "c")
    _tap(db, neither.card_id, "neither", slot + timedelta(hours=4), "evt-tap-c")
    _two_goal_db(db, slot_at("15:30", day=3), "d")
    fields = _r7_run(capsys, db)
    assert fields["r8.forecast.15:30.builder"] == "8"
    assert fields["r8.forecast.15:30.n"] == "10"
    assert fields["r8.actual.15:30.builder"] == "1"
    assert fields["r8.actual.15:30.disconnect"] == "0"
    assert fields["r8.actual.15:30.n"] == "1"
    assert fields["r8.actual.20:30.disconnect"] == "1"
    assert fields["r8.actual.22:30.neither"] == "1"
    assert fields["r8.actual.15:30.untapped"] == "1"
    assert fields["r8.actual.22:30.builder"] == "0"


def test_r8_forecast_counts_fallback_side_as_offered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    _deliver(db, "card-made-up-fallback", slot, kinds=("proposal", "fallback"))
    _tap(db, "card-made-up-fallback", "A", slot + timedelta(hours=2), "evt-tap-a")
    fields = _r7_run(capsys, db)
    assert fields["r8.actual.15:30.builder"] == "1"
    assert fields["r8.actual.15:30.n"] == "1"


def test_r8_recovery_grid_labels_and_assumption(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    fields = _r7_run(capsys, db)
    assert fields["recovery.per_bucket.n_cards"] == "2,3"
    assert fields["recovery.pooled_constant_preference.n_cards"] == "7"
    assert fields["recovery.optimistic.n_cards"] == "13"
    assert "Bernoulli" in fields["recovery.assumption"]
    assert fields["recovery.per_bucket.p0.5.correct_side"] != ""
    assert fields["recovery.optimistic.p0.9.coverage"] != ""


# -- AT-B7: Deviation 5 counts, never a ratio --


def test_deviation_5_zero_failure_model_prints_counts_no_ratio(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    _record(db, "proposal", slot=slot_at("15:30"), profile="builder")
    _record(db, "proposal", slot=slot_at("18:00"), profile="disconnect")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["r1.slot.muse-wonder-1.0.high.first_failed"] == "0"
    assert fields["r1.slot.muse-wonder-1.0.high.first_drafts"] == "2"
    assert "ratio" not in out


# -- AT-B8: the command with the new sections --


def test_report_counts_only_with_new_sections(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "store.db"
    slot = slot_at("15:30")
    _record(db, "proposal", slot=slot, profile="builder", text=ZEBRA)
    _dispute(db, 21, "f-1")
    _deliver(db, "card-made-up-1", slot)
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    assert ZEBRA not in out
    assert "cm-made-up-1" not in out
    assert "Made-up commitment" not in out
    assert "card-made-up-1" not in out
    assert "Pushes were" not in out
    assert "ratio" not in out
    fields = _parse(out)
    assert "report.sections_pending" not in fields
    for key in (
        "r7.tap.accepted",
        "r8.scores.n",
        "r8.policy_diff.buckets",
        "beforeduring.periods",
        "recovery.assumption",
    ):
        assert key in fields, key


def test_1130_run_scope_still_thirteen_without_dated_slot() -> None:
    """Pinning: the registered run stays 13 instants with no Nov 3 11:30."""
    slots = run_slots()
    assert len(slots) == 13
    assert datetime(2026, 11, 3, 11, 30, tzinfo=MADRID) not in slots


def test_1130_ledger_slot_counts_outside_not_unpinned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ledger start row at Nov 3 11:30 counts as outside the run."""
    db = tmp_path / "store.db"
    slot = datetime(2026, 11, 3, 11, 30, tzinfo=MADRID)
    SlotLedger(db).append_step(slot, "start", "ok", 0.5, None, {})
    _record(db, "proposal", slot=slot, profile="builder")
    code, out = _run_report(capsys, "--db", str(db))
    assert code == 0, out
    fields = _parse(out)
    assert fields["scope.slots_outside_run"] == "1"
    assert fields["scope.slots_unpinned"] == "0"
