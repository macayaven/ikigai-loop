"""Ticket 14c: dry-run-first backfill for corrected-card slot rows (K1–K10).

Made-up rows only. The stores are seeded through ``CardLedger``,
``VoiceLedger``, ``SlotLedger`` and ``ProposalStore``, as the voice tests
seed theirs. No network, no model, no real data.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from telegram_fake import no_sockets  # noqa: F401 (autouse fixture)
from test_voice_worker import (
    REST_ID,
    SAT_RECEIVED,
    SUBJECT,
    WRITE2_ID,
    WRITE_ID,
    claim_and_process,
    correction_json,
    make_harness,
    seed_note,
    seed_old_card,
    seed_results,
    seed_slot_rows,
)

WRITE3_ID = "cm-write3"
WRITE3_TITLE = "Chart the synthetic quarter"


def _slot_db(tmp_path: Path, name: str) -> Path:
    """One fresh made-up store file."""
    return tmp_path / name


def _applied_at() -> datetime:
    return SAT_RECEIVED


def _record_proposal(
    db: Path,
    *,
    profile_id: str,
    commitment_id: str,
    title: str,
    start: datetime,
    end: datetime,
    slot: datetime,
    cycle_id: str = "cycle-1",
    run: int = 1,
    kind: str = "write",
    dimension: str = "love",
) -> None:
    """One stored proposal result row for a profile and slot."""
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Action, Briefing, Section
    from framework.proposal.core import ProposalResult
    from framework.store.proposal_store import ProposalStore

    briefing = Briefing(
        id=f"briefing-{profile_id}-{commitment_id}-{cycle_id}",
        profile_id=profile_id,
        subject_id=SUBJECT,
        slot=slot,
        sections=[
            Section(
                type="actions",
                claims=[],
                actions=[
                    Action(
                        id=f"action-{profile_id}-{commitment_id}",
                        commitment_id=commitment_id,
                        kind=kind,  # type: ignore[arg-type]
                        text=title,
                        dimension=dimension,  # type: ignore[arg-type]
                        proposed_start=start,
                        proposed_end=end,
                    )
                ],
            )
        ],
    )
    result = ProposalResult(
        kind="proposal",
        profile_id=profile_id,
        subject_id=SUBJECT,
        cycle_id=cycle_id,
        run=run,
        slot=slot,
        hour=TimeInterval(start=start, end=end),
        briefing=briefing,
        fallback=None,
        reason_codes=(),
        attempts=(),
        cycle_age_s=0.0,
        prompt_hash="seed",
    )
    store = ProposalStore(db)
    try:
        store.record(result, snapshot={})
    finally:
        store.close()


def _corrected_card(
    old: Any, builder_title: str, builder_start: datetime | None = None
) -> Any:
    """A corrected card hand-built like the worker builds it."""
    from framework.telegram.models import Card

    start = builder_start if builder_start is not None else old.proposals[0].start
    end = start + timedelta(minutes=25)
    return Card(
        slot=old.slot,
        since_line=old.since_line,
        proposals=(  # type: ignore[arg-type]
            {
                "letter": "A",
                "kind": "proposal",
                "profile": "Builder",
                "title": builder_title,
                "start": start,
                "end": end,
            },
            {
                "letter": "B",
                "kind": "proposal",
                "profile": "Disconnect",
                "title": old.proposals[1].title,
                "start": old.proposals[1].start,
                "end": old.proposals[1].end,
            },
        ),
        statements=(),
        correction_line="Skip it today.",
        replaces_card_id=old.card_id,
    )


def _dump(db: Path) -> dict[str, Any]:
    """Every row of the tables the backfill may read or write.

    A missing table reads as ``None``; the backfill must never create
    one it has no business touching.
    """
    conn = sqlite3.connect(db)
    try:
        out: dict[str, Any] = {}
        for table in ("slot_cards", "telegram_cards", "voice_notes", "events"):
            try:
                out[table] = conn.execute(
                    f"SELECT * FROM {table} ORDER BY rowid"
                ).fetchall()
            except sqlite3.Error:
                out[table] = None
        return out
    finally:
        conn.close()


def _seed_pair(
    db: Path,
    message_id: int,
    *,
    builder_title: str,
    with_old_rows: bool = True,
    builder_start: datetime | None = None,
    bucket: str | None = None,
    titles: tuple[str, str] | None = None,
) -> tuple[Any, Any]:
    """One old card, its rows, and a linked corrected card; returns both."""
    from framework.telegram.ledger import CardLedger

    ns = SimpleNamespace(db=db, now=SAT_RECEIVED)
    if titles is None:
        old = seed_old_card(ns, message_id=700 + message_id)  # type: ignore[arg-type]
    else:
        old = seed_old_card(ns, message_id=700 + message_id, titles=titles)  # type: ignore[arg-type]
    if with_old_rows:
        if bucket is None:
            seed_slot_rows(ns, old)  # type: ignore[arg-type]
        else:
            seed_slot_rows(ns, old, bucket=bucket)  # type: ignore[arg-type]
    new = _corrected_card(old, builder_title, builder_start)
    cards = CardLedger(db)
    cards.save_card(new)
    from test_voice_worker import seed_chart

    cards.save_chart(new.card_id, seed_chart())
    seed_note(ns, message_id, reply_to=700 + message_id)  # type: ignore[arg-type]
    from framework.voice.ledger import VoiceLedger

    VoiceLedger(db).update(
        message_id,
        transcript="made-up transcript words",
        operation="skip",
        commitment_id=WRITE_ID,
        until_value="today",
        applied_at=_applied_at().isoformat(),
        matched_card_id=old.card_id,
        new_card_id=new.card_id,
    )
    return (old, new)


def test_backfill_matches_worker_rows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backfill writes exactly the rows the fixed worker writes.

    One store runs the note with the row save switched off and is then
    backfilled with ``--apply``; the other runs it with the fix. The two
    corrected cards carry the same content, so the row sets are equal in
    every field.
    """
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice import worker as voice_worker
    from framework.voice.worker import backfill_slot_rows

    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    harness_a = make_harness(
        monkeypatch,
        first,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old_a = seed_old_card(harness_a, message_id=700)
    seed_results(harness_a, old_a)
    seed_slot_rows(harness_a, old_a)
    seed_note(harness_a, 301, reply_to=700)

    def _no_rows(*args: Any, **kwargs: Any) -> None:
        return None

    original = voice_worker._save_corrected_rows
    monkeypatch.setattr(voice_worker, "_save_corrected_rows", _no_rows)
    assert claim_and_process(harness_a) == "applied_card"
    monkeypatch.setattr(voice_worker, "_save_corrected_rows", original)
    from framework.voice.ledger import VoiceLedger

    row_a = VoiceLedger(harness_a.db).load(301)
    assert row_a is not None and row_a.new_card_id is not None
    assert SlotLedger(harness_a.db).slot_cards_for_card(row_a.new_card_id) == ()

    text = backfill_slot_rows(harness_a.db, apply=True)
    assert f"card_id={row_a.new_card_id}" in text
    backfilled = SlotLedger(harness_a.db).slot_cards_for_card(row_a.new_card_id)

    harness_b = make_harness(
        monkeypatch,
        second,
        compile_script=[correction_json("skip", WRITE_ID, "today")],
        transcript=b"skip the write-up today",
    )
    old_b = seed_old_card(harness_b, message_id=700)
    seed_results(harness_b, old_b)
    seed_slot_rows(harness_b, old_b)
    seed_note(harness_b, 301, reply_to=700)
    assert claim_and_process(harness_b) == "applied_card"
    row_b = VoiceLedger(harness_b.db).load(301)
    assert row_b is not None and row_b.new_card_id is not None
    worker_rows = SlotLedger(harness_b.db).slot_cards_for_card(row_b.new_card_id)

    assert tuple(backfilled) == tuple(worker_rows)
    assert worker_rows[0].commitment_id == WRITE2_ID
    assert backfilled[0].as_of == harness_a.now
    assert worker_rows[0].as_of == harness_b.now


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    """A dry run writes nothing but still lists the rows it would write."""
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "dry.db")
    old, new = _seed_pair(db, 401, builder_title="Draft the release notes")
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    before = _dump(db)
    text = backfill_slot_rows(db, apply=False)
    assert _dump(db) == before
    assert f"write card_id={new.card_id} message_id=401 letter=A" in text
    assert f"commitment_id={WRITE2_ID}" in text
    assert "seen=1" in text


def test_backfill_apply_writes_listed_rows(tmp_path: Path) -> None:
    """``--apply`` writes the listed rows and nothing else."""
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice.__main__ import main as voice_main

    db = _slot_db(tmp_path, "apply.db")
    old, new = _seed_pair(db, 402, builder_title="Draft the release notes")
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    before = _dump(db)
    assert voice_main(["backfill-slot-rows", "--db", str(db), "--apply"]) == 0
    saved = SlotLedger(db).slot_cards_for_card(new.card_id)
    assert [item.letter for item in saved] == ["A", "B"]
    assert saved[0].commitment_id == WRITE2_ID
    assert saved[0].kind == "proposal"
    assert saved[0].as_of == _applied_at()
    assert saved[0].slot == old.slot
    assert saved[1].commitment_id == REST_ID
    after = _dump(db)
    assert after["telegram_cards"] == before["telegram_cards"]
    assert after["voice_notes"] == before["voice_notes"]
    assert after["events"] == before["events"]
    assert len(after["slot_cards"]) == len(before["slot_cards"]) + 2


def test_backfill_second_apply_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second ``--apply`` writes nothing and zeroes the totals."""
    from framework.voice.__main__ import main as voice_main
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "twice.db")
    old, _new = _seed_pair(db, 403, builder_title="Draft the release notes")
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    backfill_slot_rows(db, apply=True)
    before = _dump(db)
    assert voice_main(["backfill-slot-rows", "--db", str(db), "--apply"]) == 0
    out = capsys.readouterr().out
    assert _dump(db) == before
    assert "to_write_cards=0" in out
    assert "to_write_rows=0" in out


def test_backfill_rowed_card_untouched(tmp_path: Path) -> None:
    """A card that already has rows is never touched or skipped."""
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "rowed.db")
    old, new = _seed_pair(db, 404, builder_title="Draft the release notes")
    before_rows = SlotLedger(db).slot_cards_for_card(old.card_id)
    assert len(before_rows) == 2
    from dataclasses import replace

    SlotLedger(db).save_slot_cards(
        tuple(replace(item, card_id=new.card_id) for item in before_rows)
    )
    before = _dump(db)
    text = backfill_slot_rows(db, apply=True)
    assert _dump(db) == before
    assert f"already_present card_id={new.card_id} message_id=404" in text
    assert "skip " not in text
    assert SlotLedger(db).slot_cards_for_card(new.card_id) == tuple(
        replace(item, card_id=new.card_id) for item in before_rows
    )


def test_backfill_skips_carry_closed_reasons(tmp_path: Path) -> None:
    """Each unrebuildable card is skipped whole, with its reason code."""
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "skips.db")
    old_a, new_a = _seed_pair(
        db,
        501,
        builder_title="Draft the release notes",
        with_old_rows=False,
        titles=("Alpha write-up", "Evening rest"),
    )
    old_b, new_b = _seed_pair(
        db,
        502,
        builder_title="Draft the release notes",
        builder_start=old_a.proposals[0].start + timedelta(hours=1),
        titles=("Beta write-up", "Evening rest"),
    )
    old_c, new_c = _seed_pair(
        db,
        503,
        builder_title="Draft the release notes",
        titles=("Gamma write-up", "Evening rest"),
    )
    for old in (old_a, old_b, old_c):
        _record_proposal(
            db,
            profile_id="builder",
            commitment_id=WRITE_ID,
            title=old.proposals[0].title,
            start=old.proposals[0].start,
            end=old.proposals[0].end,
            slot=old.slot,
        )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old_c.proposals[0].start,
        end=old_c.proposals[0].end,
        slot=old_c.slot,
        cycle_id="cycle-2",
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE3_ID,
        title=WRITE3_TITLE,
        start=old_c.proposals[0].start,
        end=old_c.proposals[0].end,
        slot=old_c.slot,
        cycle_id="cycle-3",
    )
    before = _dump(db)
    text = backfill_slot_rows(db, apply=True)
    assert _dump(db) == before
    assert (
        f"skip card_id={new_a.card_id} message_id=501 reason=NO_REPLACED_ROWS" in text
    )
    assert f"skip card_id={new_b.card_id} message_id=502 reason=MISSING_RESULT" in text
    assert (
        f"skip card_id={new_c.card_id} message_id=503 reason=AMBIGUOUS_RESULT" in text
    )
    assert "skipped_NO_REPLACED_ROWS=1" in text
    assert "skipped_MISSING_RESULT=1" in text
    assert "skipped_AMBIGUOUS_RESULT=1" in text
    for new in (new_a, new_b, new_c):
        assert SlotLedger(db).slot_cards_for_card(new.card_id) == ()


def test_backfill_output_holds_no_titles_or_transcripts(tmp_path: Path) -> None:
    """The printed output holds ids, kinds, codes and counts — nothing said."""
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "quiet.db")
    title = "Zebraplum fantail clerestory"
    old, new = _seed_pair(db, 601, builder_title=title)
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title=title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    from framework.voice.ledger import VoiceLedger

    VoiceLedger(db).update(601, transcript="jabberwock quibber chatter")
    dry = backfill_slot_rows(db, apply=False)
    applied = backfill_slot_rows(db, apply=True)
    for text in (dry, applied):
        assert "Zebraplum" not in text
        assert "fantail" not in text
        assert "jabberwock" not in text
        assert "quibber" not in text
        assert f"card_id={new.card_id}" in text
        assert f"commitment_id={WRITE2_ID}" in text
        assert "seen=1" in text


def test_backfill_tap_counted(tmp_path: Path) -> None:
    """A tap on a backfilled card is counted by ``rebuild_state``."""
    from framework.collectors.common import event_id
    from framework.cycle.orchestrator import rebuild_state
    from framework.cycle.slot_ledger import SlotLedger
    from framework.schemas.events import AppTapData, Event
    from framework.telegram.service import COLLECTOR_VERSION
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "tap.db")
    old, new = _seed_pair(
        db, 602, builder_title="Draft the release notes", bucket="evening"
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    backfill_slot_rows(db, apply=True)
    rows = SlotLedger(db).slot_cards_for_card(new.card_id)
    assert len(rows) == 2
    tap = Event(
        id=event_id("telegram", "tap:backfill"),
        subject_id=SUBJECT,
        source="telegram",
        type="app.tap",
        time=SAT_RECEIVED,
        source_id="tap:backfill",
        data=AppTapData(block_id=new.card_id, target="A"),
        tier="private",
        collected_at=SAT_RECEIVED,
        collector_version=COLLECTOR_VERSION,
    )
    _, skipped = rebuild_state((tap,), rows)
    assert skipped == 0


def test_backfill_needs_no_commitments_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The backfill writes the same rows with the commitments file missing."""
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "nocommit.db")
    old, new = _seed_pair(db, 603, builder_title="Draft the release notes")
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(tmp_path / "missing.json"))
    text = backfill_slot_rows(db, apply=True)
    saved = SlotLedger(db).slot_cards_for_card(new.card_id)
    assert [item.commitment_id for item in saved] == [WRITE2_ID, REST_ID]
    assert f"write card_id={new.card_id} message_id=603 letter=A" in text


def test_backfill_drops_replaced_side_candidate(tmp_path: Path) -> None:
    """The regular card's own result next to one re-proposal is not ambiguous.

    Both rows share kind and hour and name different commitments; the
    candidate that would rebuild the replaced side itself is dropped, so
    the backfill writes the re-proposal's commitment.
    """
    from framework.cycle.slot_ledger import SlotLedger
    from framework.voice.worker import backfill_slot_rows

    db = _slot_db(tmp_path, "drop.db")
    old, new = _seed_pair(db, 604, builder_title="Draft the release notes")
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE_ID,
        title=old.proposals[0].title,
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
    )
    _record_proposal(
        db,
        profile_id="builder",
        commitment_id=WRITE2_ID,
        title="Draft the release notes",
        start=old.proposals[0].start,
        end=old.proposals[0].end,
        slot=old.slot,
        cycle_id="cycle-2",
    )
    text = backfill_slot_rows(db, apply=True)
    saved = SlotLedger(db).slot_cards_for_card(new.card_id)
    assert [item.commitment_id for item in saved] == [WRITE2_ID, REST_ID]
    assert f"write card_id={new.card_id} message_id=604 letter=A" in text
    assert "AMBIGUOUS_RESULT" not in text
