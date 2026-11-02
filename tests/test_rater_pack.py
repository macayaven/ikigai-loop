"""Slice A, AT-A2/A3/A4/A5: the rater pack over made-up stores.

Stores are built through the real writers: ProposalStore.record,
FactStore.record_cycle, SlotLedger.save_card_step/append_step,
CardLedger.save_card/save_chart/save_card_message/record_voice_note and
VoiceLedger.update. Direct SQL is used only to plant a disagreement.
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.context import TimeInterval
from framework.briefing.schemas import Action, Briefing, Claim, MetricRef, Section
from framework.cycle.orchestrator import run_slot
from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
from framework.glimmer.facts import FactResult, PassResult
from framework.proposal.core import AttemptOutcome, ProposalResult
from framework.rater.__main__ import main as rater_main
from framework.schemas.core import Fact, FactWindow
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.telegram.ledger import CardLedger
from framework.telegram.models import (
    Card,
    ChartData,
    ChartSeries,
    TallyItem,
)


def _chart() -> ChartData:
    return ChartData(
        period_labels=("Prior", "Last", "Now"),
        screen=(ChartSeries(label="Code", earlier=1.0, prior=4.75, last=1.75),),
        pushes=ChartSeries(label="Pushes", earlier=1.0, prior=1.0, last=1.0),
        tally=(TallyItem(label="Items", count=2),),
    )


MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-rater-test"
DENY_TERM = "synthetic-denied-term"

_COMMITMENTS = [
    {
        "id": "b-write",
        "profile_id": "builder",
        "title": "Draft the weekly notes",
        "kind": "write",
        "dimension": "world_needs",
        "evidence": "tap",
    },
    {
        "id": "d-rest",
        "profile_id": "disconnect",
        "title": "Rest with music",
        "kind": "rest",
        "dimension": "love",
        "evidence": "no_screen",
    },
]


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    crit = tmp_path / "criteria"
    crit.mkdir(exist_ok=True)
    (crit / "deny-terms.txt").write_text(DENY_TERM + "\n", encoding="utf-8")
    cfile = tmp_path / "commitments.json"
    cfile.write_text(json.dumps(_COMMITMENTS), encoding="utf-8")
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(crit))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(cfile))
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
    return tmp_path / "store.db"


def _claim(
    cid: str,
    text: str,
    facts: tuple[str, ...] = (),
    metrics: tuple[tuple[str, float], ...] = (),
) -> Claim:
    return Claim(
        id=cid,
        text=text,
        fact_ids=list(facts),
        metric_refs=[MetricRef(metric_id=mid, value=value) for mid, value in metrics],
    )


def _briefing(
    bid: str,
    profile: str,
    slot: datetime,
    sections: dict[str, list[Claim]],
) -> Briefing:
    order = ("overall_state", "since_last", "working", "not_working")
    built = [
        Section(type=section, claims=sections[section])  # type: ignore[arg-type]
        for section in order
        if section in sections
    ]
    start = slot + timedelta(minutes=30)
    built.append(
        Section(
            type="actions",  # type: ignore[arg-type]
            claims=[],
            actions=[
                Action(
                    id="act-1",
                    commitment_id="b-write" if profile == "builder" else "d-rest",
                    kind="write" if profile == "builder" else "rest",  # type: ignore[arg-type]
                    text="side title",
                    dimension="love",  # type: ignore[arg-type]
                    proposed_start=start,
                    proposed_end=start + timedelta(hours=1),
                )
            ],
        )
    )
    return Briefing(
        id=bid, profile_id=profile, subject_id=SUBJECT, slot=slot, sections=built
    )


def _attempt(model: str = "muse-wonder-1.0", effort: str = "high") -> AttemptOutcome:
    return AttemptOutcome(
        number=1,
        model_requested=model,
        model_reported=model,
        effort=effort,
        prompt_hash="hash-1",
        raw_text="{}",
        parsed_ok=True,
        blocked=False,
        codes=(),
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


def _record(
    db: Path,
    *,
    slot: datetime,
    profile: str,
    briefing: Briefing,
    cycle_id: str = "cycle-1",
    run: int = 1,
    model: str = "muse-wonder-1.0",
    effort: str = "high",
) -> str:
    start = slot + timedelta(minutes=30)
    store = ProposalStore(db)
    try:
        return store.record(
            ProposalResult(
                kind="proposal",
                profile_id=profile,  # type: ignore[arg-type]
                subject_id=SUBJECT,
                cycle_id=cycle_id,
                run=run,
                slot=slot,
                hour=TimeInterval(start=start, end=start + timedelta(hours=1)),
                briefing=briefing,
                fallback=None,
                reason_codes=(),
                attempts=(_attempt(model, effort),),
                cycle_age_s=0.0,
                prompt_hash="hash-1",
            ),
            snapshot={},
        )
    finally:
        store.close()


def _record_facts(
    db: Path, cycle_id: str, run: int, statements: dict[str, str], as_of: datetime
) -> None:
    window = FactWindow(start=as_of - timedelta(hours=72), end=as_of)
    facts = tuple(
        Fact(
            id=fid,
            subject_id=SUBJECT,
            window=window,
            statement=statement,
            evidence=["evt-made-up-1"],
            tier="public",  # type: ignore[arg-type]
        )
        for fid, statement in statements.items()
    )
    passes = (
        PassResult(
            name="personal",
            attempts=0,
            raw_valid=False,
            model_id="",
            latency_ms=0,
            finish_reason=None,
            completion_tokens=None,
            kept=0,
            noop_reason=None,
        ),
        PassResult(
            name="feed",
            attempts=0,
            raw_valid=False,
            model_id="",
            latency_ms=0,
            finish_reason=None,
            completion_tokens=None,
            kept=0,
            noop_reason=None,
        ),
    )
    result = FactResult(
        facts=facts,
        code_fact_ids=(),
        snapshot=__import__(
            "framework.briefing.context", fromlist=["MetricSnapshot"]
        ).MetricSnapshot(values={}),
        passes=passes,
        responses=(),
        cycle_id=cycle_id,
        subject_id=SUBJECT,
        as_of=as_of,
        window_start=as_of - timedelta(hours=72),
        prompt_hash="ph",
        dropped=(),
        is_noop=False,
        noop_reason=None,
    )
    store = FactStore(db_path=db)
    try:
        store.record_cycle(result)
    finally:
        store.close()


def _card(
    slot: datetime,
    statements: tuple[str, ...],
    *,
    titles: tuple[str, str] = ("Draft the weekly notes", "Rest with music"),
    fallback_b: bool = False,
    replaces: str | None = None,
) -> Card:
    start = slot + timedelta(minutes=30)
    end = start + timedelta(hours=1)
    sides: list[dict[str, object]] = [
        {
            "letter": "A",
            "kind": "proposal",
            "profile": "Builder",
            "title": titles[0],
            "start": start,
            "end": end,
        }
    ]
    if fallback_b:
        sides.append(
            {
                "letter": "B",
                "kind": "fallback",
                "reason_codes": ["NO_ELIGIBLE"],
                "profile": "Disconnect",
                "title": titles[1],
                "start": start,
                "end": end,
            }
        )
    else:
        sides.append(
            {
                "letter": "B",
                "kind": "proposal",
                "profile": "Disconnect",
                "title": titles[1],
                "start": start,
                "end": end,
            }
        )
    return Card(
        slot=slot,
        since_line="Since 15:00: made-up notes.",
        proposals=tuple(sides),  # type: ignore[arg-type]
        statements=statements,
        replaces_card_id=replaces,
    )


def _rows(
    card: Card,
    slot: datetime,
    *,
    kinds: tuple[str, str] = ("proposal", "proposal"),
) -> tuple[SlotCardRow, ...]:
    profiles = ("builder", "disconnect")
    cids = ("b-write", "d-rest")
    return tuple(
        SlotCardRow(
            card_id=card.card_id,
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


_mid = [9000]


def _deliver(
    db: Path,
    card: Card,
    slot: datetime,
    rows: tuple[SlotCardRow, ...],
    *,
    outcome: str = "delivered",
    message: bool = True,
) -> None:
    ledger = SlotLedger(db)
    ledger.save_card_step(
        slot, card.card_id, {}, rows, card.model_dump_json(), "{}", 0.5
    )
    ledger.append_step(slot, "send", outcome, 0.5, card.card_id, {})
    if message:
        _mid[0] += 1
        CardLedger(db).save_card_message(_mid[0], card.card_id)


def _run_pack(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    db: Path,
    out: Path,
    seed: str = "7",
    extra: tuple[str, ...] = (),
) -> tuple[int, str]:
    code = rater_main(
        [
            "pack",
            "--db",
            str(db),
            "--out-dir",
            str(out),
            "--seed",
            seed,
            "--cut",
            "2026-11-04T18:00:00+01:00",
            *extra,
        ]
    )
    return code, capsys.readouterr().out


def _parse(stdout: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)


# -- AT-A2: delivered scope --


def test_undelivered_card_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    SlotLedger(db).save_card_step(
        slot, card.card_id, {}, _rows(card, slot), card.model_dump_json(), "{}", 0.5
    )
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "0"


def test_delivery_disagreement_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    stmts = ("A · Builder", "Pushes were 2 in the last period.")
    # Slot-delivered, no message row.
    slot_card = _card(slot, stmts)
    _deliver(db, slot_card, slot, _rows(slot_card, slot), message=False)
    # Voice-only: payload in telegram_cards, voice row, no message row.
    voice_card = _card(slot, ("A · Builder", "Pushes were 2 in the last period?"))
    voice_card = Card.model_validate(
        {**voice_card.model_dump(mode="json"), "slot": slot.isoformat()}
    )
    ledger = CardLedger(db)
    ledger.save_card(voice_card)
    ledger.save_chart(voice_card.card_id, _chart())
    from framework.telegram.models import VoiceNote
    from framework.voice.ledger import VoiceLedger

    note = VoiceNote(
        message_id=4242,
        date=int(slot.timestamp()),
        file_id="synthetic-file-id",
        file_unique_id="uniq-4242",
        duration_s=4,
        mime_type="audio/ogg",
        file_size=4100,
        reply_to_message_id=None,
    )
    assert ledger.record_voice_note(note, 5001, slot.isoformat()) is True
    VoiceLedger(db).update(4242, new_card_id=voice_card.card_id)
    SlotLedger(db).save_slot_cards(_rows(voice_card, slot))
    # Message row with no send record at all.
    stray = _card(slot, ("A · Builder", "Pushes were 4 in the last period."))
    CardLedger(db).save_card(stray)
    CardLedger(db).save_chart(stray.card_id, _chart())
    CardLedger(db).save_card_message(777001, stray.card_id)
    # Payload with no delivery signal at all.
    lost = _card(slot, ("A · Builder", "Pushes were 5 in the last period."))
    SlotLedger(db).save_card_step(
        slot, lost.card_id, {}, _rows(lost, slot), lost.model_dump_json(), "{}", 0.5
    )
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["delivery_slot_without_message_row"] == "1"
    assert counts["delivery_voice_without_message_row"] == "1"
    assert counts["delivery_message_without_send_record"] == "1"
    assert counts["delivery_unknown_cards"] == "1"


def test_delivery_unknown_card_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(
        db, card, slot, _rows(card, slot), outcome="DELIVERY_UNKNOWN", message=False
    )
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["delivery_unknown_cards"] == "1"
    assert counts["claims_atomic_total"] == "0"


def test_slot_and_voice_paths_both_delivered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    briefing2 = _briefing(
        "brf-2",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 3 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing2, cycle_id="cycle-2")
    _record_facts(db, "cycle-2", 1, {"f1": "Pushes were 3 in the last period."}, slot)
    slot_card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, slot_card, slot, _rows(slot_card, slot))
    voice_card = _card(slot, ("A · Builder", "Pushes were 3 in the last period."))
    ledger = CardLedger(db)
    ledger.save_card(voice_card)
    ledger.save_chart(voice_card.card_id, _chart())
    ledger.save_card_message(61001, voice_card.card_id)
    SlotLedger(db).save_slot_cards(_rows(voice_card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "2"


def test_outside_run_slot_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("16:00")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["delivered_cards_outside_run"] == "1"
    assert counts["claims_atomic_total"] == "0"


def test_slot_cut_includes_at_cut_and_keeps_corrected_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    early = slot_at("13:30")
    late = slot_at("15:30")
    for mark, text in (
        (early, "Pushes were 2 in the last period."),
        (late, "Pushes were 3 in the last period."),
    ):
        briefing = _briefing(
            f"brf-{mark.hour}",
            "builder",
            mark,
            {"overall_state": [_claim("c-a", text, ("f1",))]},
        )
        _record(
            db,
            slot=mark,
            profile="builder",
            briefing=briefing,
            cycle_id=f"cycle-{mark.hour}",
        )
        _record_facts(db, f"cycle-{mark.hour}", 1, {"f1": text}, mark)
        card = _card(mark, ("A · Builder", text))
        _deliver(db, card, mark, _rows(card, mark))
    cut = early.isoformat()
    code, out = _run_pack(
        monkeypatch, capsys, db, tmp_path / "pack", extra=("--cut", cut)
    )
    assert code == 0, out
    counts = _parse(out)
    assert counts["claims_atomic_total"] == "1"
    # Corrected card keeps the old slot, so it sits under the same cut.
    old = _card(early, ("A · Builder", "Pushes were 9 in the last period."))
    corrected = _card(
        early,
        ("A · Builder", "Pushes were 9 in the last period!"),
        replaces=old.card_id,
    )
    assert corrected.slot == early
    assert corrected.slot.isoformat() <= cut


# -- AT-A3: sentence recovery and evidence rendering --


def test_recovery_per_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    builder = _briefing(
        "brf-b",
        "builder",
        slot,
        {
            "overall_state": [
                _claim(
                    "c-overall-1",
                    "Pushes were 2 in the last period.",
                    ("f1",),
                    (("period.last.pushes", 2.0),),
                )
            ],
            "working": [
                _claim("c-working-1", "Code grew in the last window.", ("f2",))
            ],
        },
    )
    disconn = _briefing(
        "brf-d",
        "disconnect",
        slot,
        {
            "overall_state": [
                _claim("c-overall-1", "Rest was quiet in the last window.", ("f3",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=builder)
    _record(db, slot=slot, profile="disconnect", briefing=disconn, cycle_id="cycle-1")
    _record_facts(
        db,
        "cycle-1",
        1,
        {
            "f1": "Pushes were 2 in the last period.",
            "f2": "Code grew in the last window.",
            "f3": "Rest was quiet in the last window.",
        },
        slot,
    )
    from framework.cycle.card_build import build_statements

    stmts = build_statements((("A", "Builder", builder), ("B", "Disconnect", disconn)))
    card = _card(slot, stmts)
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["statements_unmatched"] == "0"
    assert counts["statements_ambiguous"] == "0"
    assert counts["claims_atomic_total"] == "3"


def test_unmatched_side_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    card = _card(
        slot,
        (
            "A · Builder",
            "Pushes were 2 in the last period.",
            "B · Disconnect",
            "Rest was quiet in the last window.",
        ),
    )
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["statements_unmatched"] == "2"
    assert counts["claims_atomic_total"] == "0"


def test_ambiguous_side_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    text = "Pushes were 2 in the last period."
    first = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", text, ("f1",))]}
    )
    second = _briefing(
        "brf-2", "builder", slot, {"overall_state": [_claim("c-a", text, ("f2",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=first, cycle_id="cycle-1")
    _record(db, slot=slot, profile="builder", briefing=second, cycle_id="cycle-2")
    _record_facts(db, "cycle-1", 1, {"f1": text}, slot)
    _record_facts(db, "cycle-2", 1, {"f2": text}, slot)
    card = _card(slot, ("A · Builder", text))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["statements_ambiguous"] == "1"
    assert counts["claims_atomic_total"] == "0"


def test_missing_fact_claim_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f9",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Something else entirely."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["facts_missing"] == "1"
    assert counts["claims_atomic_total"] == "0"


def test_fallback_side_contributes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(
        slot, ("A · Builder", "Pushes were 2 in the last period."), fallback_b=True
    )
    _deliver(db, card, slot, _rows(card, slot, kinds=("proposal", "fallback")))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["statements_unmatched"] == "0"
    assert counts["claims_atomic_total"] == "1"


def test_corrected_card_unchanged_side_rated_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    text = "Pushes were 2 in the last period."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", text, ("f1",))]}
    )
    key = _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": text}, slot)
    old = _card(slot, ("A · Builder", text))
    _deliver(db, old, slot, _rows(old, slot))
    corrected = _card(slot, ("A · Builder", text), replaces=old.card_id)
    _deliver(db, corrected, slot, _rows(corrected, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "1"
    key_path = next((tmp_path / "pack").glob("*.key.json"))
    items = json.loads(key_path.read_text(encoding="utf-8"))["items"]
    assert len(items) == 1
    item = next(iter(items.values()))
    assert item["proposal_key"] == key
    assert item["delivered_cards_shown"] == 2


def test_reproposed_side_recovers_both_cards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    old_text = "Pushes were 2 in the last period."
    new_text = "Pushes were 9 in the last period."
    first = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", old_text, ("f1",))]}
    )
    second = _briefing(
        "brf-2", "builder", slot, {"overall_state": [_claim("c-a", new_text, ("f1",))]}
    )
    first_key = _record(
        db, slot=slot, profile="builder", briefing=first, cycle_id="cycle-1"
    )
    second_key = _record(
        db, slot=slot, profile="builder", briefing=second, cycle_id="cycle-2"
    )
    assert first_key != second_key
    _record_facts(db, "cycle-1", 1, {"f1": old_text}, slot)
    _record_facts(db, "cycle-2", 1, {"f1": new_text}, slot)
    old = _card(slot, ("A · Builder", old_text))
    _deliver(db, old, slot, _rows(old, slot))
    corrected = _card(slot, ("A · Builder", new_text), replaces=old.card_id)
    _deliver(db, corrected, slot, _rows(corrected, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "2"


def test_since_last_signed_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    builder = _briefing(
        "brf-b",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-base", "Code stands ready for the hour.", ("f1",))
            ],
            "since_last": [
                _claim(
                    "c-up",
                    "Code rose since the previous card.",
                    (),
                    (("period.last.screen_hours.Work/Programming", 1.5),),
                ),
                _claim(
                    "c-down",
                    "Pushes fell since the previous card.",
                    (),
                    (("period.last.pushes", -2.0),),
                ),
            ],
        },
    )
    disconn = _briefing(
        "brf-d",
        "disconnect",
        slot,
        {
            "overall_state": [_claim("c-ob", "Rest was quiet.", ("f2",))],
            "since_last": [
                _claim(
                    "c-flat",
                    "Feed held since the previous card.",
                    (),
                    (("feed.item.count", 0.0),),
                ),
            ],
        },
    )
    # build_statements puts the first overall_state claim first, then the rest.
    from framework.cycle.card_build import build_statements

    stmts = build_statements((("A", "Builder", builder), ("B", "Disconnect", disconn)))
    assert len(stmts) == 7
    _record(db, slot=slot, profile="builder", briefing=builder)
    _record(db, slot=slot, profile="disconnect", briefing=disconn)
    _record_facts(
        db,
        "cycle-1",
        1,
        {"f1": "Code stands ready for the hour.", "f2": "Rest was quiet."},
        slot,
    )
    card = _card(slot, stmts)
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "5"
    page = next((tmp_path / "pack").glob("*.html")).read_text(encoding="utf-8")
    assert "+1.5 hours since the previous card" in page
    assert "-2 since the previous card" in page
    assert "0 since the previous card" in page


def test_fact_only_claim_shows_fact_and_no_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    statement = "Paper lists hold tasks and picnic lists hold dates."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", statement, ("f1",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": statement}, slot)
    card = _card(slot, ("A · Builder", statement))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "1"
    page = next((tmp_path / "pack").glob("*.html")).read_text(encoding="utf-8")
    assert statement in page


def test_evidence_rendering_per_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    cases = [
        (
            "period.last.screen_hours.Work/Programming",
            3.5,
            "Programming screen time in the last period: 3.5 hours",
        ),
        (
            "period.prior.tag_hours.iki-family",
            1.0,
            "Calendar time tagged family in the prior period: 1 hours",
        ),
        ("period.last.pushes", 2.0, "Pushes in the last period: 2"),
        ("period.earlier.prs", 4.0, "Pull requests in the earlier period: 4"),
        (
            "calendar.busy_hours",
            2.5,
            "Busy calendar time across the whole three-day window: 2.5 hours",
        ),
        ("feed.item.count", 6.0, "Feed items across the whole three-day window: 6"),
        (
            "period.last.cancelled.iki-deep",
            1.0,
            "Cancelled blocks tagged deep in the last period: 1",
        ),
    ]
    claims = [
        _claim(f"c-{i}", f"Made-up line number {i} here.", ("f1",), ((mid, value),))
        for i, (mid, value, _) in enumerate(cases)
    ]
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": claims[:3], "working": claims[3:]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Made-up backing line."}, slot)
    from framework.cycle.card_build import build_statements

    stmts = build_statements((("A", "Builder", briefing),))
    card = _card(slot, stmts)
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "3"
    page = next((tmp_path / "pack").glob("*.html")).read_text(encoding="utf-8")
    for _, _, line in cases[:3]:
        assert line in page, line
    from framework.rater.pack import collect

    collected = collect(db, cut=None)
    assert collected.atomics, "expected rendered evidence lines"
    for entry in collected.atomics:
        for line in entry.evidence_lines:
            assert line[:1].isupper(), line


def test_unbound_metric_claim_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim(
                    "c-a",
                    "Mystery metric moved today.",
                    (),
                    (("period.last.mystery_metric", 1.0),),
                )
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {}, slot)
    card = _card(slot, ("A · Builder", "Mystery metric moved today."))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["metrics_unbound"] == "1"
    assert counts["claims_atomic_total"] == "0"


# -- AT-A5: private by construction --


def test_private_term_hit_refuses_whole_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    bad = f"Pushes mention {DENY_TERM} in the last period."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", bad, ("f1",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": bad}, slot)
    card = _card(slot, ("A · Builder", bad))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 1
    assert "pack_refused=1" in out
    assert DENY_TERM not in out
    assert bad not in out
    assert list((tmp_path / "pack").glob("*")) == []


def test_unavailable_terms_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(tmp_path / "missing"))
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 1
    assert "pack_refused=1" in out


def test_output_dir_inside_repo_refused_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from framework import rater as rater_pkg

    db = _env(monkeypatch, tmp_path)
    repo_root = Path(rater_pkg.__file__).resolve().parents[2]
    inside = repo_root / "rater-pack-should-never-exist"
    code, _ = _run_pack(monkeypatch, capsys, db, inside)
    assert code == 2
    assert not inside.exists()


def test_page_and_key_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import os
    import stat

    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    outdir = tmp_path / "pack"
    code, out = _run_pack(monkeypatch, capsys, db, outdir)
    assert code == 0, out
    assert stat.S_IMODE(os.stat(outdir).st_mode) == 0o700
    for path in outdir.iterdir():
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_files_owner_only_without_chmod(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import os
    import stat

    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    briefing = _briefing(
        "brf-1",
        "builder",
        slot,
        {
            "overall_state": [
                _claim("c-a", "Pushes were 2 in the last period.", ("f1",))
            ]
        },
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": "Pushes were 2 in the last period."}, slot)
    card = _card(slot, ("A · Builder", "Pushes were 2 in the last period."))
    _deliver(db, card, slot, _rows(card, slot))
    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)
    old_umask = os.umask(0)
    try:
        outdir = tmp_path / "pack"
        code, out = _run_pack(monkeypatch, capsys, db, outdir)
    finally:
        os.umask(old_umask)
    assert code == 0, out
    assert stat.S_IMODE(os.stat(outdir).st_mode) == 0o700
    for path in outdir.iterdir():
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_title_inside_longer_word_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    text = "The tally was already settled in the last period."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", text, ("f1",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": text}, slot)
    card = _card(slot, ("A · Builder", text))
    _deliver(db, card, slot, _rows(card, slot))
    (tmp_path / "commitments.json").write_text(
        json.dumps(
            [
                {
                    "id": "b-read",
                    "profile_id": "builder",
                    "title": "Read",
                    "kind": "write",
                    "dimension": "world_needs",
                    "evidence": "tap",
                },
                {
                    "id": "d-rest",
                    "profile_id": "disconnect",
                    "title": "Rest",
                    "kind": "rest",
                    "dimension": "love",
                    "evidence": "no_screen",
                },
            ]
        ),
        encoding="utf-8",
    )
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    assert _parse(out)["claims_atomic_total"] == "1"


def test_title_as_own_words_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    text = "Pushes were 2 in the last period, a note to Read."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", text, ("f1",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": text}, slot)
    card = _card(slot, ("A · Builder", text))
    _deliver(db, card, slot, _rows(card, slot))
    (tmp_path / "commitments.json").write_text(
        json.dumps(
            [
                {
                    "id": "b-read",
                    "profile_id": "builder",
                    "title": "Read",
                    "kind": "write",
                    "dimension": "world_needs",
                    "evidence": "tap",
                },
                {
                    "id": "d-rest",
                    "profile_id": "disconnect",
                    "title": "Rest",
                    "kind": "rest",
                    "dimension": "love",
                    "evidence": "no_screen",
                },
            ]
        ),
        encoding="utf-8",
    )
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 1
    assert "pack_refused=1" in out
    assert "TITLE_HIT" in out
    assert list((tmp_path / "pack").glob("*")) == []


def test_output_dir_inside_any_git_tree_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    db.touch()
    other = tmp_path / "other-clone"
    other.mkdir()
    (other / ".git").mkdir()
    inside = other / "pack"
    code, _ = _run_pack(monkeypatch, capsys, db, inside)
    assert code == 2
    assert not inside.exists()


def test_corrected_card_counters_counted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    text = "Pushes were 2 and steady in the last window, so this hour goes to rest."
    briefing = _briefing(
        "brf-1", "builder", slot, {"overall_state": [_claim("c-a", text, ("f1",))]}
    )
    _record(db, slot=slot, profile="builder", briefing=briefing)
    _record_facts(db, "cycle-1", 1, {"f1": text}, slot)
    old = _card(slot, ("A · Builder", text))
    _deliver(db, old, slot, _rows(old, slot))
    corrected = _card(slot, ("A · Builder", text), replaces=old.card_id)
    _deliver(db, corrected, slot, _rows(corrected, slot))
    code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert code == 0, out
    counts = _parse(out)
    assert counts["claims_atomic_total"] == "1"
    assert counts["statements_total"] == "2"
    assert counts["statements_distinct"] == "1"
    assert counts["so_clauses_cut"] == "1"
    assert counts["possibly_compound"] == "1"


# -- AT-A4: a real slot through the orchestrator harness, then the pack --


def test_real_slot_harness_then_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from typing import Any

    import framework.cycle as cycle_pkg
    from framework.cycle.orchestrator import FactsChildResult, Seams

    db = _env(monkeypatch, tmp_path)
    for name in ("TELEGRAM_CHAT_ID",):
        monkeypatch.setenv(name, "424242")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    slot = slot_at("15:30")

    texts = {
        "builder": "Pushes were 2 in the last period.",
        "disconnect": "Rest was quiet in the last window.",
    }

    def _spy(**kwargs: Any) -> ProposalResult:
        profile = str(kwargs["profile_id"])
        hour = kwargs["hour"]
        briefing = _briefing(
            f"brf-live-{profile}",
            profile,
            slot,
            {"overall_state": [_claim("c-live", texts[profile], ("f-live",))]},
        )
        assert hour is not None
        result = ProposalResult(
            kind="proposal",
            profile_id=profile,  # type: ignore[arg-type]
            subject_id=SUBJECT,
            cycle_id="cycle-live",
            run=1,
            slot=slot,
            hour=hour,
            briefing=briefing,
            fallback=None,
            reason_codes=(),
            attempts=(_attempt(),),
            cycle_age_s=0.0,
            prompt_hash="",
        )
        store = ProposalStore(db)
        try:
            store.record(result, snapshot={})
        finally:
            store.close()
        return result

    monkeypatch.setattr(cycle_pkg, "propose", _spy)

    class _Telegram:
        def __init__(self) -> None:
            self.message_id = 424242

        def send_photo(
            self,
            chat_id: int,
            photo: bytes,
            caption: str,
            markup: dict[str, Any],
            timeout_s: float = 60.0,
            disable_notification: bool = False,
        ) -> dict[str, Any]:
            self.message_id += 1
            return {"message_id": self.message_id}

    clock_now = {"now": slot}

    def _facts(**kwargs: Any) -> FactsChildResult:
        return FactsChildResult("MODEL_DOWN", None, None)

    def _wonder(terms: Any, deadline: Any) -> Any:
        from types import SimpleNamespace

        return SimpleNamespace(
            transport="synthetic", transport_version=None, harness_rules_file=None
        )

    seams = Seams(
        facts=_facts,
        wonder=_wonder,
        telegram=_Telegram(),
        clock=lambda: clock_now["now"],
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    from framework.store.store import EventStore

    store = EventStore(db_path=db)
    try:
        pass
    finally:
        store.close()
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO cursors (name, cursor, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(name) DO UPDATE SET cursor=excluded.cursor,"
            " updated_at=excluded.updated_at",
            ("calendar-synthetic", "{}", slot.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    code = run_slot(
        slot=slot, subject_id=SUBJECT, db_path=db, no_wait=True, seams=seams
    )
    capsys.readouterr()
    assert code == 0
    _record_facts(
        db,
        "cycle-live",
        1,
        {"f-live": "Backing line for the live slot."},
        slot,
    )
    # The live claims cite f-live, which now exists: rebuild the pack.
    pack_code, out = _run_pack(monkeypatch, capsys, db, tmp_path / "pack")
    assert pack_code == 0, out
    counts = _parse(out)
    assert int(counts["claims_atomic_total"]) >= 1
