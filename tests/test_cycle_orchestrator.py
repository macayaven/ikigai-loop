"""Ticket 13 slices 2 and 3: slots, the run and the watchdog (made-up data)."""

import dataclasses
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.schemas import Briefing, Commitment
from framework.cycle import __main__ as cycle_main
from framework.cycle.orchestrator import (
    MODEL_PARAMS,
    SLOT_LIMITS,
    SLOT_TIMES,
    STALE_AFTER_S,
    DeadlineWonderClient,
    EligibilityState,
    FactsChildResult,
    Seams,
    check_slot,
    classify_slot,
    disconnect_send_blocked,
    eligible_commitments,
    rank_and_block,
    rebuild_state,
    run_slot,
    slot_from_today,
    slot_profiles,
    validate_slot,
)
from framework.cycle.slot_ledger import SlotCardRow, SlotLedger
from framework.learner.policy import bucket_for, initial_state, state_json
from framework.learner.schemas import PolicyState
from framework.proposal.core import (
    MetaUnavailableError,
    ProposalResult,
)
from framework.schemas.events import Event
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.store.store import EventStore

MADRID = ZoneInfo("Europe/Madrid")


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def commitment(cid: str, profile: str, kind: str = "build") -> Commitment:
    return Commitment.model_validate(
        {
            "id": cid,
            "profile_id": profile,
            "title": f"Title {cid}",
            "kind": kind,
            "dimension": "love",
            "evidence": "github_push",
        }
    )


def state(
    sent: int = 0,
    hour: datetime | None = None,
    slot: datetime | None = None,
) -> EligibilityState:
    moment = slot or slot_at("15:30")
    return EligibilityState(
        disconnect_sent_today=sent,
        now_local=moment,
        hour_start_local=hour,
    )


def tap(eid: str, card_id: str, target: str, moment: datetime) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "telegram",
            "type": "app.tap",
            "time": moment.isoformat(),
            "source_id": f"{card_id}:{target}",
            "data": {"type": "app.tap", "block_id": card_id, "target": target},
            "tier": "private",
            "collected_at": moment.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def card_rows(
    card_id: str,
    slot: datetime,
    two: bool = True,
    pick: str | None = "b-1",
    bucket: str | None = "evening",
    disconnect_pick: str | None = "d-1",
) -> tuple[SlotCardRow, ...]:
    builder = SlotCardRow(
        card_id=card_id,
        letter="A",
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket=bucket,
        profile_id="builder",
        commitment_id="b-1",
        kind="proposal",
        policy_pick=pick,
        policy_alternative=None,
    )
    if not two:
        return (builder,)
    return (
        builder,
        SlotCardRow(
            card_id=card_id,
            letter="B",
            slot=slot,
            subject_id="subject-a",
            as_of=slot,
            bucket=bucket,
            profile_id="disconnect",
            commitment_id="d-1",
            kind="proposal",
            policy_pick=disconnect_pick,
            policy_alternative=None,
        ),
    )


# -- slots --


def test_pinned_slot_times() -> None:
    assert [(t.hour, t.minute) for t in SLOT_TIMES] == [
        (13, 30),
        (15, 30),
        (18, 0),
        (20, 30),
        (22, 30),
    ]
    assert SLOT_LIMITS.timezone == "Europe/Madrid"
    assert (SLOT_LIMITS.allowed_start.hour, SLOT_LIMITS.allowed_start.minute) == (
        13,
        0,
    )
    assert (SLOT_LIMITS.allowed_end.hour, SLOT_LIMITS.allowed_end.minute) == (
        23,
        30,
    )
    assert MODEL_PARAMS.first_model == "muse-wonder-1.0"
    assert STALE_AFTER_S == pytest.approx(12 * 3600.0)


def test_slot_profiles_builder_always_disconnect_on_three() -> None:
    assert slot_profiles(slot_at("13:30")) == ("builder",)
    assert slot_profiles(slot_at("15:30")) == ("builder", "disconnect")
    assert slot_profiles(slot_at("18:00")) == ("builder",)
    assert slot_profiles(slot_at("20:30")) == ("builder", "disconnect")
    assert slot_profiles(slot_at("22:30")) == ("builder", "disconnect")


def test_slot_profiles_never_disconnect_at_or_after_cutoff() -> None:
    assert slot_profiles(slot_at("23:00")) == ("builder",)
    assert slot_profiles(slot_at("23:30")) == ("builder",)


def test_validate_slot_pins_five_refuses_sixth_and_bad_offset() -> None:
    for hm in ("13:30", "15:30", "18:00", "20:30", "22:30"):
        assert validate_slot(slot_at(hm)) is None
    assert validate_slot(slot_at("16:00")) == "SLOT_NOT_PINNED"
    naive = datetime(2026, 11, 2, 15, 30)
    assert validate_slot(naive) == "SLOT_NOT_PINNED"
    wrong_offset = datetime.fromisoformat("2026-11-02T15:30:00+02:00")
    assert validate_slot(wrong_offset) == "SLOT_NOT_PINNED"


# -- eligibility --


def test_eligibility_returns_all_of_profile_in_file_order() -> None:
    rows = (
        commitment("b-2", "builder", "music"),
        commitment("b-1", "builder"),
        commitment("d-1", "disconnect", "rest"),
    )
    got = eligible_commitments(
        rows,
        profile_id="builder",
        slot_local=slot_at("15:30"),
        state=state(),
    )
    assert [c.id for c in got] == ["b-2", "b-1"]


def test_eligibility_disconnect_before_night_keeps_all() -> None:
    rows = (
        commitment("d-1", "disconnect"),
        commitment("d-2", "disconnect", "music"),
    )
    got = eligible_commitments(
        rows,
        profile_id="disconnect",
        slot_local=slot_at("15:30"),
        state=state(),
    )
    assert [c.id for c in got] == ["d-1", "d-2"]


def test_eligibility_from_21h_keeps_only_music_rest() -> None:
    rows = (
        commitment("d-1", "disconnect"),
        commitment("d-2", "disconnect", "music"),
        commitment("d-3", "disconnect", "rest"),
    )
    got = eligible_commitments(
        rows,
        profile_id="disconnect",
        slot_local=slot_at("21:30"),
        state=state(),
    )
    assert [c.id for c in got] == ["d-2", "d-3"]


def test_eligibility_at_21h_by_slot_boundary() -> None:
    rows = (commitment("d-1", "disconnect"),)
    assert (
        eligible_commitments(
            rows,
            profile_id="disconnect",
            slot_local=slot_at("20:59"),
            state=state(),
        )
        == rows
    )
    assert (
        eligible_commitments(
            rows,
            profile_id="disconnect",
            slot_local=slot_at("21:00"),
            state=state(),
        )
        == ()
    )


def test_eligibility_2030_slot_with_2115_hour_keeps_music_rest() -> None:
    rows = (
        commitment("d-1", "disconnect"),
        commitment("d-2", "disconnect", "music"),
        commitment("d-3", "disconnect", "rest"),
    )
    got = eligible_commitments(
        rows,
        profile_id="disconnect",
        slot_local=slot_at("20:30"),
        state=state(hour=slot_at("21:15")),
    )
    assert [c.id for c in got] == ["d-2", "d-3"]


def test_eligibility_hour_before_cutoff_keeps_all() -> None:
    rows = (commitment("d-1", "disconnect"),)
    got = eligible_commitments(
        rows,
        profile_id="disconnect",
        slot_local=slot_at("20:30"),
        state=state(hour=slot_at("20:45")),
    )
    assert got == rows


def test_eligibility_disconnect_empty_at_and_after_23h() -> None:
    rows = (commitment("d-1", "disconnect", "music"),)
    for hm in ("23:00", "23:30"):
        got = eligible_commitments(
            rows,
            profile_id="disconnect",
            slot_local=slot_at(hm),
            state=state(slot=slot_at(hm)),
        )
        assert got == ()


def test_eligibility_builder_unaffected_by_night_rules() -> None:
    rows = (commitment("b-1", "builder"),)
    got = eligible_commitments(
        rows,
        profile_id="builder",
        slot_local=slot_at("23:00"),
        state=state(slot=slot_at("23:00")),
    )
    assert got == rows


# -- disconnect send-time lock --


def test_disconnect_send_blocked_at_and_after_2300() -> None:
    assert disconnect_send_blocked(True, slot_at("22:59")) is False
    assert disconnect_send_blocked(True, slot_at("23:00")) is True
    assert disconnect_send_blocked(True, slot_at("23:05")) is True
    assert disconnect_send_blocked(False, slot_at("23:05")) is False
    assert disconnect_send_blocked(True, slot_at("22:50")) is False


# -- learner --


def test_rebuild_is_deterministic() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    taps = (tap("t1", "card-a", "A", moment),)
    rows = card_rows("card-a", slot)
    first, skipped_first = rebuild_state(taps, rows)
    second, skipped_second = rebuild_state(taps, rows)
    assert state_json(first) == state_json(second)
    assert (skipped_first, skipped_second) == (0, 0)


def test_rebuild_feeds_wrong_and_why_and_reads_letter_order() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    taps = (
        tap("t1", "card-a", "wrong", moment),
        tap("t2", "card-a", "why", moment + timedelta(seconds=1)),
    )
    rows = card_rows("card-a", slot)
    flipped = (rows[1], rows[0])
    rebuilt, skipped = rebuild_state(taps, flipped)
    assert skipped == 0
    assert rebuilt.buckets["evening"].wrong == 1
    assert rebuilt.buckets["evening"].why == 1
    assert rebuilt.pick_log[0].label == "A"
    assert rebuilt.pick_log[0].profile_id == "builder"


def test_rebuild_uses_observe_not_bare_update() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    rebuilt, _ = rebuild_state(
        (tap("t1", "card-a", "A", moment),), card_rows("card-a", slot)
    )
    assert len(rebuilt.score_log) > 0
    assert rebuilt.commitments["b-1"].taken == 1


def test_rebuild_skips_null_pick_cards_and_counts() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    rebuilt, skipped = rebuild_state(
        (tap("t1", "card-a", "A", moment),),
        card_rows("card-a", slot, pick=None, disconnect_pick=None),
    )
    assert skipped == 1
    assert rebuilt.rulings_seen == 0


def test_rebuild_skips_unknown_card_and_bad_target_and_counts() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    rows = card_rows("card-a", slot, two=False)
    rebuilt, skipped = rebuild_state(
        (
            tap("t1", "card-missing", "A", moment),
            tap("t2", "card-a", "B", moment + timedelta(seconds=1)),
        ),
        rows,
    )
    assert skipped == 2
    assert rebuilt.rulings_seen == 0


def test_rebuild_skips_bucket_outside_taps() -> None:
    with pytest.raises(ValueError):
        bucket_for(slot_at("23:30").timetz())
    with pytest.raises(ValueError):
        bucket_for(slot_at("09:00").timetz())
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    rebuilt, skipped = rebuild_state(
        (tap("t1", "card-a", "A", moment),),
        card_rows("card-a", slot, bucket=None),
    )
    assert skipped == 1
    assert rebuilt.rulings_seen == 0


def test_rebuild_untapped_cards_add_no_ruling() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    rebuilt, skipped = rebuild_state(
        (tap("t1", "card-a", "A", moment),),
        card_rows("card-a", slot) + card_rows("card-b", slot),
    )
    assert skipped == 0
    assert rebuilt.rulings_seen == 1
    assert set(rebuilt.commitments) == {"b-1", "d-1"}
    assert "card-b" not in rebuilt.cards


def test_rebuild_state_replays_taps_in_handled_at_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import framework.cycle.orchestrator as orchestrator_module

    slot = slot_at("18:00")
    late = tap("t9", "card-a", "A", slot + timedelta(minutes=9))
    early = tap("t1", "card-a", "B", slot + timedelta(minutes=1))
    seen: list[str] = []
    real_observe = orchestrator_module.observe

    def _recording(state: Any, ruling: Any) -> Any:
        seen.append(ruling.target)
        return real_observe(state, ruling)

    monkeypatch.setattr(orchestrator_module, "observe", _recording)
    rebuilt, skipped = rebuild_state((late, early), card_rows("card-a", slot))
    assert skipped == 0
    assert rebuilt.rulings_seen == 2
    assert seen == ["B", "A"]


def test_rank_one_candidate_has_no_alternative() -> None:
    pick, alternative, block = rank_and_block(
        initial_state(), "builder", ("b-1",), "evening"
    )
    assert pick == "b-1"
    assert alternative is None
    assert block != ""


def test_rank_moved_commitment_carries_on_without_block() -> None:
    slot = slot_at("18:00")
    moment = slot + timedelta(minutes=5)
    moved, _ = rebuild_state(
        (tap("t1", "card-a", "A", moment),), card_rows("card-a", slot)
    )
    assert moved.commitments["b-1"].profile_id == "builder"
    pick, alternative, block = rank_and_block(
        moved, "disconnect", ("b-1", "d-9"), "evening"
    )
    assert (pick, alternative, block) == (None, None, "")


def test_rank_returns_pick_alternative_block() -> None:
    pick, alternative, block = rank_and_block(
        initial_state(), "builder", ("b-2", "b-1"), "evening"
    )
    assert pick in ("b-1", "b-2")
    assert alternative in ("b-1", "b-2")
    assert pick != alternative
    assert "candidates" in block


def test_rebuild_state_type_and_empty() -> None:
    rebuilt, skipped = rebuild_state((), ())
    assert isinstance(rebuilt, PolicyState)
    assert (skipped, rebuilt.rulings_seen) == (0, 0)


# -- slice 3: run_slot and check_slot with fakes (made-up data) --

SUBJECT = "subject-a"

_COMMITMENTS = [
    {
        "id": "b-1",
        "profile_id": "builder",
        "title": "Morning pages draft",
        "kind": "build",
        "dimension": "love",
        "evidence": "github_push",
    },
    {
        "id": "b-2",
        "profile_id": "builder",
        "title": "Evening review notes",
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
    {
        "id": "d-2",
        "profile_id": "disconnect",
        "title": "Quiet reading block",
        "kind": "music",
        "dimension": "love",
        "evidence": "github_push",
    },
    {
        "id": "d-3",
        "profile_id": "disconnect",
        "title": "Slow tea pause",
        "kind": "rest",
        "dimension": "love",
        "evidence": "github_push",
    },
]


def _env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, titles: str = "default"
) -> tuple[Path, Path]:
    terms = tmp_path / "terms"
    terms.mkdir(exist_ok=True)
    (terms / "deny-terms.txt").write_text("zzforbiddenzz\n")
    commitments = tmp_path / "commitments.json"
    if titles == "canary":
        rows = [dict(item, title=f"CanaryTitle{item['id']}") for item in _COMMITMENTS]
    else:
        rows = _COMMITMENTS
    commitments.write_text(json.dumps(rows))
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(terms))
    monkeypatch.setenv("IKIGAI_COMMITMENTS_FILE", str(commitments))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "424242")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("IKIGAI_KILL_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return terms, commitments


class _Clock:
    """A wall clock the test sets by hand; never the real home or time."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@dataclass
class _Facts:
    result: FactsChildResult
    calls: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.calls = []

    def __call__(self, **kwargs: Any) -> FactsChildResult:
        assert self.calls is not None
        self.calls.append(dict(kwargs))
        return self.result


def _down_result() -> FactsChildResult:
    return FactsChildResult("MODEL_DOWN", None, None)


class _DownWonder:
    """Wonder is down: every call raises, nothing is ever parsed."""

    transport = "muse"
    transport_version: str | None = "fake version 1.0"
    harness_rules_file: bool | None = None

    def __init__(self, message: str = "synthetic down") -> None:
        self.message = message
        self.calls = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1
        raise MetaUnavailableError(self.message, latency_ms=5)


class _Telegram:
    def __init__(self, fail_first: Any = None, fail_all: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_first = fail_first
        self.fail_all = fail_all
        self.message_id = 11

    def send_photo(
        self,
        chat_id: int,
        photo: bytes,
        caption: str,
        markup: dict[str, Any],
        timeout_s: float = 60.0,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "chat_id": chat_id,
                "photo_len": len(photo),
                "caption": caption,
                "timeout_s": timeout_s,
            }
        )
        if self.fail_all is not None:
            raise self.fail_all
        if self.fail_first is not None and len(self.calls) == 1:
            raise self.fail_first
        return {"message_id": self.message_id}


@dataclass
class _Harness:
    db: Path
    seams: Seams
    clock: _Clock
    facts: _Facts
    wonder: _DownWonder
    telegram: _Telegram
    sleeps: list[float]


def _harness(
    tmp_path: Path,
    slot: datetime,
    *,
    facts: FactsChildResult | None = None,
    wonder: _DownWonder | None = None,
    telegram: _Telegram | None = None,
    home: Path | None = None,
) -> _Harness:
    clock = _Clock(slot)
    fake_facts = _Facts(facts or _down_result())
    fake_wonder = wonder or _DownWonder()
    fake_telegram = telegram or _Telegram()
    sleeps: list[float] = []
    seams = Seams(
        facts=fake_facts,
        wonder=lambda terms, deadline: fake_wonder,
        telegram=fake_telegram,
        clock=clock,
        sleep=sleeps.append,
        home=home or (tmp_path / "home"),
        ledger_sleep=lambda s: None,
    )
    _seed_calendar_cursor(tmp_path / "cycle.db", slot)
    return _Harness(
        db=tmp_path / "cycle.db",
        seams=seams,
        clock=clock,
        facts=fake_facts,
        wonder=fake_wonder,
        telegram=fake_telegram,
        sleeps=sleeps,
    )


def _seed_calendar_cursor(
    db: Path, updated_at: datetime, name: str = "calendar-synthetic"
) -> None:
    """Write one `calendar-` cursor row as a good poll would leave it."""
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
            (name, "{}", updated_at.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_busy_block(db: Path, slot: datetime, as_of: datetime) -> None:
    """Store one busy calendar block covering the slot's own hour."""
    store = EventStore(db_path=db)
    try:
        store.append_events(
            [
                Event.model_validate(
                    {
                        "id": "evt-busy-cover-a",
                        "subject_id": SUBJECT,
                        "source": "synthetic",
                        "type": "calendar.event.created",
                        "time": slot.isoformat(),
                        "source_id": "busy-cover-a@aaa",
                        "data": {
                            "type": "calendar.event.created",
                            "start": slot.isoformat(),
                            "end": (slot + timedelta(hours=1)).isoformat(),
                            "busy": True,
                            "category": "synthetic",
                            "tags": [],
                            "is_new": False,
                        },
                        "tier": "private",
                        "collected_at": as_of.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                ),
            ]
        )
    finally:
        store.close()


def _run(
    slot: datetime,
    harness: _Harness,
    capsys: pytest.CaptureFixture[str],
    **kwargs: Any,
) -> tuple[int, str, str]:
    params: dict[str, Any] = {
        "slot": slot,
        "subject_id": SUBJECT,
        "db_path": harness.db,
        "no_wait": True,
        "seams": harness.seams,
    }
    params.update(kwargs)
    code = run_slot(**params)  # type: ignore[arg-type]
    out = capsys.readouterr()
    return code, out.out, out.err


def _details(slot: datetime, db: Path) -> list[str]:
    return [row.detail for row in SlotLedger(db).rows_for_slot(slot)]


def _briefing_dict(cid: str, profile: str, slot: datetime) -> dict[str, Any]:
    start = slot.replace(hour=16, minute=0)
    end = slot.replace(hour=17, minute=0)
    return {
        "id": f"brf-{cid}",
        "profile_id": profile,
        "subject_id": SUBJECT,
        "slot": slot.isoformat(),
        "sections": [
            {
                "type": "overall_state",
                "claims": [
                    {"id": "c1", "text": "First claim text here.", "fact_ids": []}
                ],
            },
            {
                "type": "actions",
                "claims": [],
                "actions": [
                    {
                        "id": "act-1",
                        "commitment_id": cid,
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


@dataclass
class _ProposeSpy:
    """A stand-in for propose that returns canned proposals per profile."""

    contexts: dict[str, Any] | None = None
    cycles: dict[str, str | None] | None = None
    calls: int = 0
    attempts: tuple[Any, ...] = ()

    def __post_init__(self) -> None:
        self.contexts = {}
        self.cycles = {}

    def __call__(self, **kwargs: Any) -> ProposalResult:
        assert self.contexts is not None
        assert self.cycles is not None
        profile = str(kwargs["profile_id"])
        self.calls += 1
        self.contexts[profile] = kwargs["context"]
        self.cycles[profile] = kwargs["cycle_id"]
        eligible = kwargs["eligible"]
        hour = kwargs["hour"]
        assert hour is not None
        shown = eligible[0].id
        briefing = Briefing.model_validate(
            _briefing_dict(shown, profile, kwargs["slot"])
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
            attempts=self.attempts,
            cycle_age_s=0.0,
            prompt_hash="",
        )


def _patch_propose(monkeypatch: pytest.MonkeyPatch, spy: _ProposeSpy) -> _ProposeSpy:
    monkeypatch.setattr("framework.cycle.propose", spy)
    return spy


# -- pinned slots, slot-today, classify --


def test_pinned_slots_run_sixth_refuses_and_force_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    for hm in ("13:30", "15:30", "18:00", "20:30", "22:30"):
        slot = slot_at(hm)
        harness = _harness(tmp_path / hm.replace(":", ""), slot)
        code, out, err = _run(slot, harness, capsys)
        assert code == 0, out
        assert err == ""
        assert re.fullmatch(
            r"slot=\S+ profiles=\d+ kind=\S+ card=\S+ seconds=\d+"
            r" dry=0 kill=unset",
            out.strip(),
        ), out
    slot = slot_at("16:00")
    harness = _harness(tmp_path / "sixth", slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 2
    assert "code=SLOT_NOT_PINNED" in out
    harness = _harness(tmp_path / "forced", slot)
    code, out, _ = _run(slot, harness, capsys, force_slot=True)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert _detail_for(rows, "forced") == "1"


def _detail_for(rows: Any, key: str) -> str | None:
    for row in rows:
        for pair in row.detail.split(" "):
            name, _, value = pair.partition("=")
            if name == key:
                return value
    return None


def test_slot_today_matches_iso_on_both_sides_of_dst() -> None:
    before = datetime(2026, 10, 24, 12, 0, tzinfo=MADRID)
    after = datetime(2026, 10, 26, 12, 0, tzinfo=MADRID)
    first = slot_from_today("15:30", before)
    second = slot_from_today("15:30", after)
    assert first.isoformat() == "2026-10-24T15:30:00+02:00"
    assert second.isoformat() == "2026-10-26T15:30:00+01:00"
    assert first != second
    with pytest.raises(ValueError):
        slot_from_today("15-30", before)


def test_slot_today_wires_both_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, datetime] = {}

    def _fake_run_slot(**kwargs: Any) -> int:
        seen["run"] = kwargs["slot"]
        return 0

    def _fake_check_slot(**kwargs: Any) -> int:
        seen["check"] = kwargs["slot"]
        return 0

    monkeypatch.setattr(cycle_main, "run_slot", _fake_run_slot)
    monkeypatch.setattr(cycle_main, "check_slot", _fake_check_slot)
    assert (
        cycle_main.main(
            [
                "run-slot",
                "--slot-today",
                "15:30",
                "--subject-id",
                SUBJECT,
                "--db",
                str(tmp_path / "a.db"),
            ]
        )
        == 0
    )
    assert (
        cycle_main.main(
            ["check-slot", "--slot-today", "15:30", "--db", str(tmp_path / "a.db")]
        )
        == 0
    )
    assert seen["run"] == seen["check"]
    assert seen["run"].isoformat().endswith("T15:30:00+01:00") or seen[
        "run"
    ].isoformat().endswith("T15:30:00+02:00")


def test_classify_splits_forceable_from_bad_offset() -> None:
    assert classify_slot(slot_at("15:30")) == "ok"
    assert classify_slot(slot_at("16:00")) == "unpinned"
    naive = datetime(2026, 11, 2, 15, 30)
    assert classify_slot(naive) == "bad_offset"
    wrong = datetime.fromisoformat("2026-11-02T15:30:00+02:00")
    assert classify_slot(wrong) == "bad_offset"


def test_forced_bad_offset_stays_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    naive = datetime(2026, 11, 2, 15, 30)
    harness = _harness(tmp_path, naive)
    code, out, _ = _run(naive, harness, capsys, force_slot=True)
    assert code == 2
    assert "code=SLOT_NOT_PINNED" in out


# -- preflight --


def test_preflight_passes_with_fake_home_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert "kill=unset" in out


def test_preflight_rules_file_trips_even_mode_000(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    home = tmp_path / "home"
    rules = home / ".config" / "muse" / "AGENTS.md"
    rules.parent.mkdir(parents=True)
    rules.write_text("synthetic rules")
    rules.chmod(0o000)
    harness = _harness(tmp_path, slot, home=home)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 2
    assert "code=PREFLIGHT_RULES_FILE" in out
    assert SlotLedger(harness.db).send_state(slot) == "none"
    assert harness.telegram.calls == []


def test_preflight_key_trips_and_value_stays_hidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("META_API_KEY", "canary-key-9z9z")
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 2
    assert "code=PREFLIGHT_META_API_KEY" in out
    assert "canary-key-9z9z" not in out
    for detail in _details(slot, harness.db):
        assert "canary-key-9z9z" not in detail


def test_preflight_blank_key_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("META_API_KEY", "   ")
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out


# -- disconnect limits through run_slot --


def _seed_delivered_disconnect(
    db: Path, slot: datetime, card: str, *, forced: bool = False
) -> None:
    ledger = SlotLedger(db)
    ledger.save_slot_cards(
        (
            SlotCardRow(
                card_id=card,
                letter="A",
                slot=slot,
                subject_id=SUBJECT,
                as_of=slot,
                bucket="afternoon",
                profile_id="builder",
                commitment_id="b-1",
                kind="proposal",
                policy_pick="b-1",
                policy_alternative=None,
            ),
            SlotCardRow(
                card_id=card,
                letter="B",
                slot=slot,
                subject_id=SUBJECT,
                as_of=slot,
                bucket="afternoon",
                profile_id="disconnect",
                commitment_id="d-1",
                kind="proposal",
                policy_pick="d-1",
                policy_alternative=None,
            ),
        )
    )
    detail = {"forced": "1"} if forced else None
    ledger.append_step(slot, "send_intent", "intent", 0.1, card, detail)
    ledger.append_step(slot, "send", "delivered", 0.2, card, detail)


def test_fourth_slot_runs_builder_alone_after_three_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("16:00")
    harness = _harness(tmp_path, slot)
    for hm, card in (("15:30", "card-a"), ("20:30", "card-b"), ("22:30", "card-c")):
        _seed_delivered_disconnect(harness.db, slot_at(hm), card)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, harness, capsys, force_slot=True)
    assert code == 0, out
    assert spy.calls == 1
    assert set(spy.contexts or {}) == {"builder"}
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "DISCONNECT_DAILY_CAP" in [row.outcome for row in rows]
    sides = SlotLedger(harness.db).slot_cards_for_slot(slot)
    assert [side.profile_id for side in sides] == ["builder"]
    assert "DISCONNECT_DAILY_CAP" in out


def test_resumed_disconnect_card_at_cap_ends_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A stored card carrying Disconnect at the cap still ends `delivered`."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("22:30")
    scratch = _harness(tmp_path / "scratch", slot)
    (tmp_path / "scratch").mkdir(parents=True, exist_ok=True)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, scratch, capsys)
    assert code == 0, out
    assert spy.calls == 2
    stored_id = SlotLedger(scratch.db).latest_card_id(slot)
    assert stored_id is not None
    payload = SlotLedger(scratch.db).load_card_payload(stored_id)
    assert payload is not None
    sides = SlotLedger(scratch.db).slot_cards_for_card(stored_id)
    assert any(side.profile_id == "disconnect" for side in sides)
    harness = _harness(tmp_path, slot)
    for hm, card in (("13:30", "card-a"), ("15:30", "card-b"), ("18:00", "card-c")):
        _seed_delivered_disconnect(harness.db, slot_at(hm), card)
    SlotLedger(harness.db).save_card_step(
        slot, stored_id, {"codes": "-"}, sides, payload[0], payload[1], 0.1
    )
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "delivered" in [row.outcome for row in rows if row.step == "send"]
    assert [row.outcome for row in rows if row.step == "done"] == ["delivered"]
    assert "DISCONNECT_DAILY_CAP" not in [row.outcome for row in rows]


def test_unknown_and_open_intents_count_and_forced_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path)
    db = tmp_path / "cycle.db"
    _seed_delivered_disconnect(db, slot_at("15:30"), "card-a", forced=True)
    ledger = SlotLedger(db)
    ledger.save_slot_cards(
        (
            SlotCardRow(
                card_id="card-open",
                letter="B",
                slot=slot_at("22:30"),
                subject_id=SUBJECT,
                as_of=slot_at("22:30"),
                bucket="night",
                profile_id="disconnect",
                commitment_id="d-1",
                kind="proposal",
                policy_pick="d-1",
                policy_alternative=None,
            ),
            SlotCardRow(
                card_id="card-b",
                letter="B",
                slot=slot_at("20:30"),
                subject_id=SUBJECT,
                as_of=slot_at("20:30"),
                bucket="evening",
                profile_id="disconnect",
                commitment_id="d-1",
                kind="proposal",
                policy_pick="d-1",
                policy_alternative=None,
            ),
        )
    )
    ledger.append_step(slot_at("20:30"), "send_intent", "intent", 0.1, "card-b", None)
    ledger.append_step(
        slot_at("20:30"), "send", "DELIVERY_UNKNOWN", 0.1, "card-b", None
    )
    ledger.append_step(
        slot_at("22:30"), "send_intent", "intent", 0.1, "card-open", None
    )
    assert ledger.disconnect_count(slot_at("15:30").date()) == 3


def test_dry_run_never_counts_and_leaves_the_real_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    before = list(harness.db.parent.glob("*.db"))
    code, out, _ = _run(slot, harness, capsys, dry_run=True)
    assert code == 0, out
    assert "dry=1" in out
    assert "card=card-" in out
    assert harness.telegram.calls == []
    after = list(harness.db.parent.glob("*.db"))
    assert before == after
    assert SlotLedger(harness.db).rows_for_slot(slot) == ()


def test_forced_2300_has_no_hour_and_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = datetime(2026, 11, 2, 23, 0, tzinfo=MADRID)
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys, force_slot=True)
    assert code == 0, out
    assert "code=NOOP_NO_FREE_HOUR" in out
    assert harness.telegram.calls == []
    sides = SlotLedger(harness.db).slot_cards_for_slot(slot)
    assert sides == ()


def test_forced_2250_with_clock_2305_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = datetime(2026, 11, 2, 22, 50, tzinfo=MADRID)
    harness = _harness(tmp_path, slot)
    harness.clock.now = datetime(2026, 11, 2, 23, 5, tzinfo=MADRID)
    code, _, _ = _run(slot, harness, capsys, force_slot=True)
    assert code == 0
    assert harness.telegram.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert [row.outcome for row in rows if row.step == "done"] != []


def test_send_time_lock_binds_before_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("22:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot + timedelta(minutes=30)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=DISCONNECT_AFTER_CUTOFF" in out
    assert harness.telegram.calls == []
    done = [row for row in SlotLedger(harness.db).rows_for_slot(slot)]
    assert "DISCONNECT_AFTER_CUTOFF" in [row.outcome for row in done]


def test_2030_slot_busy_until_2115_keeps_music_rest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("20:30")

    from framework.briefing.context import TimeInterval as _Interval

    picked = _Interval(
        start=slot_at("21:15"),
        end=slot_at("22:15"),
    )
    from framework.cycle import orchestrator

    monkeypatch.setattr(orchestrator, "plan_hour", lambda **kwargs: picked)
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    sides = SlotLedger(harness.db).slot_cards_for_slot(slot)
    shown = {side.profile_id: side.commitment_id for side in sides}
    assert shown["disconnect"] in ("d-2", "d-3")
    assert "d-1" not in set(shown.values())


def test_no_eligible_disconnect_means_absent_builder_card(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    commitments = tmp_path / "commitments.json"
    rows = [dict(item) for item in json.loads(commitments.read_text())]
    for item in rows:
        if item["profile_id"] == "disconnect":
            item["kind"] = "build"
    commitments.write_text(json.dumps(rows))
    slot = slot_at("20:30")

    from framework.briefing.context import TimeInterval as _Interval

    picked = _Interval(
        start=slot_at("21:15"),
        end=slot_at("22:15"),
    )
    from framework.cycle import orchestrator

    monkeypatch.setattr(orchestrator, "plan_hour", lambda **kwargs: picked)
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    sides = SlotLedger(harness.db).slot_cards_for_slot(slot)
    assert [side.profile_id for side in sides] == ["builder"]
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert any(
        "NOOP_NO_ELIGIBLE_COMMITMENT" in row.detail
        for row in rows
        if row.step == "propose_disconnect"
    )


def test_untapped_delivered_slot_rerun_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=ALREADY_DONE" in out
    assert len(harness.telegram.calls) == 1


# -- hour and sides --


def test_orchestrator_hour_equals_result_hour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path)
    from framework.cycle import run_proposals as _real_run_proposals
    from framework.cycle.orchestrator import (
        MODEL_PARAMS as _MODELS,
    )
    from framework.cycle.orchestrator import (
        SLOT_LIMITS as _LIMITS,
    )
    from framework.cycle.orchestrator import (
        STALE_AFTER_S as _STALE,
    )
    from framework.cycle.orchestrator import plan_hour as _plan_hour

    db = tmp_path / "cycle.db"
    store = EventStore(db_path=db)
    try:
        fact_store = FactStore(db_path=store.db_path)
        try:
            proposal_store = ProposalStore(db_path=store.db_path)
            try:
                slot = slot_at("15:30")
                as_of = slot - timedelta(minutes=25)
                from framework.cycle import run_cycle as _run_cycle

                class _Stub:
                    def complete(self, prompt: str) -> Any:
                        raise AssertionError("no model")

                _run_cycle(as_of, SUBJECT, store, fact_store, _Stub())  # type: ignore[arg-type]
                from framework.briefing import load_commitments
                from framework.briefing.context import load_private_terms

                terms = load_private_terms()
                loaded = load_commitments(os.environ, private_terms=terms.terms)
                assert loaded.available
                expected = _plan_hour(
                    as_of=as_of, slot=slot, subject_id=SUBJECT, store=store
                )
                (result,) = _real_run_proposals(
                    as_of=as_of,
                    slot=slot,
                    subject_id=SUBJECT,
                    profiles=("builder",),
                    store=store,
                    fact_store=fact_store,
                    proposal_store=proposal_store,
                    client=_DownWonder(),
                    private_terms=terms,
                    eligible_by_profile={
                        "builder": tuple(
                            item
                            for item in loaded.commitments
                            if item.profile_id == "builder"
                        )
                    },
                    limits=_LIMITS,
                    models=_MODELS,
                    stale_after_s=_STALE,
                    cycle_id=None,
                    policy_by_profile={"builder": ""},
                    parents={},
                )
                assert result.hour == expected
            finally:
                proposal_store.close()
        finally:
            fact_store.close()
    finally:
        store.close()


def test_moved_invitation_revision_outside_span_frees_slot_hour(
    tmp_path: Path,
) -> None:
    from framework.cycle.orchestrator import plan_hour as _plan_hour

    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    db = tmp_path / "busy.db"
    store = EventStore(db_path=db)
    try:
        old_start = slot
        new_start = slot + timedelta(days=40)
        revisions = (
            Event.model_validate(
                {
                    "id": "rev-1",
                    "subject_id": SUBJECT,
                    "source": "synthetic",
                    "type": "calendar.event.created",
                    "time": old_start.isoformat(),
                    "source_id": "inv-move-1@aaa",
                    "data": {
                        "type": "calendar.event.created",
                        "start": old_start.isoformat(),
                        "end": (old_start + timedelta(hours=1)).isoformat(),
                        "busy": True,
                        "category": "synthetic",
                        "tags": ["iki-review"],
                        "is_new": False,
                    },
                    "tier": "private",
                    "collected_at": (as_of - timedelta(hours=1)).isoformat(),
                    "collector_version": "synthetic@0.1.0",
                }
            ),
            Event.model_validate(
                {
                    "id": "rev-2",
                    "subject_id": SUBJECT,
                    "source": "synthetic",
                    "type": "calendar.event.updated",
                    "time": new_start.isoformat(),
                    "source_id": "inv-move-1@bbb",
                    "data": {
                        "type": "calendar.event.updated",
                        "start": new_start.isoformat(),
                        "end": (new_start + timedelta(hours=1)).isoformat(),
                        "busy": True,
                        "category": "synthetic",
                        "tags": ["iki-review"],
                        "is_new": False,
                    },
                    "tier": "private",
                    "collected_at": as_of.isoformat(),
                    "collector_version": "synthetic@0.1.0",
                }
            ),
        )
        store.append_events(list(revisions))
        hour = _plan_hour(as_of=as_of, slot=slot, subject_id=SUBJECT, store=store)
        assert hour is not None
        assert hour.start == slot
        assert hour.end == slot + timedelta(hours=1)
    finally:
        store.close()


# -- send, run level: retries, crashes, resends, fresh --


def test_send_not_sent_then_success_retries_with_waits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=TelegramTransportError("synthetic refuse"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert len(telegram.calls) == 2
    assert harness.sleeps == [30.0]
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    intents = [row for row in rows if row.step == "send_intent"]
    assert [row.outcome for row in rows if row.step == "send"] == [
        "SEND_NOT_SENT",
        "delivered",
    ]
    assert [row.card_id for row in intents] == [intents[0].card_id] * 2


def test_crash_after_intent_records_unknown_and_never_resends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=KeyboardInterrupt("boom"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=harness.db,
            no_wait=True,
            seams=harness.seams,
        )
    capsys.readouterr()
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(telegram.calls) == 1


def test_resend_unknown_sends_once_more_and_refuses_otherwise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramDeliveryUnknown

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=TelegramDeliveryUnknown("lost"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(telegram.calls) == 1
    code, out, _ = _run(slot, harness, capsys, resend_unknown=True)
    assert code == 0, out
    assert len(telegram.calls) == 2
    details = _details(slot, harness.db)
    assert any("resend_unknown=1" in detail for detail in details)
    other = slot_at("18:00")
    harness2 = _harness(tmp_path / "other", other, telegram=_Telegram())
    code, out, _ = _run(other, harness2, capsys, resend_unknown=True)
    assert code == 2
    assert "code=RESEND_NOT_UNKNOWN" in out


def test_plain_rerun_reuses_results_and_fresh_calls_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("13:30")
    harness = _harness(tmp_path, slot)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert spy.calls == 1
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=ALREADY_DONE" in out
    assert spy.calls == 1


def test_fresh_refused_on_delivered_and_on_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramDeliveryUnknown

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, _, _ = _run(slot, harness, capsys)
    assert code == 0
    code, out, _ = _run(slot, harness, capsys, fresh=True)
    assert code == 2
    assert "code=FRESH_REFUSED" in out
    other = slot_at("18:00")
    harness2 = _harness(
        tmp_path / "unknown",
        other,
        telegram=_Telegram(fail_first=TelegramDeliveryUnknown("lost")),
    )
    code, _, _ = _run(other, harness2, capsys)
    assert code == 1
    code, out, _ = _run(other, harness2, capsys, fresh=True)
    assert code == 2
    assert "code=FRESH_REFUSED" in out


def test_fresh_rerun_calls_the_model_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    slot = slot_at("13:30")
    harness = _harness(
        tmp_path,
        slot,
        telegram=_Telegram(fail_all=TelegramTransportError("down")),
    )
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=SEND_NOT_SENT" in out
    assert spy.calls == 1
    code, out, _ = _run(slot, harness, capsys, fresh=True)
    assert code == 1
    assert "code=SEND_NOT_SENT" in out
    assert spy.calls == 2


# -- kill file arms --


def test_kill_at_start_stops_before_any_model_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    kill.write_text("stop\n")
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=killed" in out
    assert harness.facts.calls == []
    assert harness.telegram.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert [row.outcome for row in rows if row.step == "start"] == [
        "ok",
        "killed",
    ]


def test_kill_before_propose_stops_with_no_wonder_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    slot = slot_at("15:30")
    real_facts = _Facts(_down_result())
    harness = _harness(tmp_path, slot, facts=real_facts.result)
    harness.clock.now = slot - timedelta(minutes=25)

    def _facts_and_stop(**kwargs: Any) -> FactsChildResult:
        kill.write_text("stop\n")
        return real_facts(**kwargs)

    harness.seams = Seams(
        facts=_facts_and_stop,
        wonder=lambda terms, deadline: harness.wonder,
        telegram=harness.telegram,
        clock=harness.clock,
        sleep=harness.sleeps.append,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=killed" in out
    assert spy.calls == 0
    assert harness.telegram.calls == []


def test_kill_before_send_stops_with_no_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    inner = _ProposeSpy()

    def _stop_then_propose(**kwargs: Any) -> ProposalResult:
        result = inner(**kwargs)
        kill.write_text("stop\n")
        return result

    monkeypatch.setattr("framework.cycle.propose", _stop_then_propose)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=killed" in out
    assert inner.calls == 1
    assert harness.telegram.calls == []


def test_kill_during_slot_wait_stops_before_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot - timedelta(minutes=10)
    calls: list[float] = []

    def _sleep_and_stop(seconds: float) -> None:
        calls.append(seconds)
        if len(calls) >= 1:
            kill.write_text("stop\n")

    harness.seams = Seams(
        facts=harness.facts,
        wonder=harness.seams.wonder,
        telegram=harness.telegram,
        clock=harness.clock,
        sleep=_sleep_and_stop,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    code, out, _ = _run(slot, harness, capsys, no_wait=False, skip_local_model=True)
    assert code == 0
    assert "code=killed" in out
    assert harness.telegram.calls == []


def test_stored_card_resumed_past_slot_plus_30_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    real_load = SlotLedger.load_card_payload
    crashed: list[bool] = []

    def _crash_once(self: SlotLedger, card_id: str) -> Any:
        if not crashed:
            crashed.append(True)
            raise RuntimeError("synthetic crash after card save")
        return real_load(self, card_id)

    monkeypatch.setattr(SlotLedger, "load_card_payload", _crash_once)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=RuntimeError" in out
    assert harness.telegram.calls == []
    assert SlotLedger(harness.db).latest_card_id(slot) is not None
    harness.clock.now = slot + timedelta(minutes=31)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=STALE_CARD" in out
    assert harness.telegram.calls == []


def test_delivery_unknown_rerun_sends_nothing_and_exits_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramDeliveryUnknown

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=TelegramDeliveryUnknown("lost"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(telegram.calls) == 1
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(telegram.calls) == 1


def test_send_failing_as_not_sent_makes_four_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(
        tmp_path,
        slot,
        telegram=_Telegram(fail_all=TelegramTransportError("down")),
    )
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=SEND_NOT_SENT" in out
    assert len(harness.telegram.calls) == 4
    assert harness.sleeps == [30.0, 60.0, 120.0]


def test_kill_during_retry_wait_stops_the_next_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    slot = slot_at("15:30")
    harness = _harness(
        tmp_path,
        slot,
        telegram=_Telegram(fail_first=TelegramTransportError("down")),
    )
    sleeps: list[float] = harness.sleeps

    def _sleep_and_stop(seconds: float) -> None:
        sleeps.append(seconds)
        kill.write_text("stop\n")

    harness.seams = Seams(
        facts=harness.facts,
        wonder=harness.seams.wonder,
        telegram=harness.telegram,
        clock=harness.clock,
        sleep=_sleep_and_stop,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=killed" in out
    assert len(harness.telegram.calls) == 1
    assert sleeps == [30.0]


# -- timing, dry run, failures --


def test_skip_local_model_records_skipped_without_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys, skip_local_model=True)
    assert code == 0, out
    assert harness.facts.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "SKIPPED" in [row.outcome for row in rows if row.step == "facts_model"]


def test_late_run_past_deadline_skips_child_as_facts_deadline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot + timedelta(minutes=11)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert harness.facts.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "FACTS_DEADLINE" in [
        row.outcome for row in rows if row.step == "facts_model"
    ]


def test_unparseable_facts_stdout_carries_code_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(
        tmp_path, slot, facts=FactsChildResult("FACTS_UNPARSED", None, None)
    )
    harness.clock.now = slot - timedelta(minutes=25)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "FACTS_UNPARSED" in [
        row.outcome for row in rows if row.step == "facts_model"
    ]
    assert harness.telegram.calls != []


def test_wonder_deadline_shrinks_timeout_then_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path)
    seen: list[float] = []
    now = slot_at("15:30")

    class _Inner:
        transport = "muse"
        transport_version: str | None = "fake 1.0"
        harness_rules_file: bool | None = None

        def complete(self, request: Any) -> Any:
            raise AssertionError("past the deadline")

    def _make(timeout_s: float) -> Any:
        seen.append(timeout_s)
        return _Inner()

    clock = _Clock(now)
    deadline = now + timedelta(seconds=200)
    client = DeadlineWonderClient(make_client=_make, deadline=deadline, clock=clock)
    from framework.proposal.core import WonderRequest

    request = WonderRequest(
        prompt="synthetic",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={},
    )
    clock.now = deadline - timedelta(seconds=150)
    with pytest.raises(AssertionError):
        client.complete(request)
    assert seen == [120.0]
    clock.now = deadline - timedelta(seconds=90)
    with pytest.raises(AssertionError):
        client.complete(request)
    assert seen == [120.0, 90.0]
    clock.now = deadline - timedelta(seconds=10)
    with pytest.raises(MetaUnavailableError, match="slot deadline"):
        client.complete(request)
    assert seen == [120.0, 90.0]


def test_past_deadline_propose_is_fallback_holding_slot_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path)
    from framework.briefing.context import (
        GateContext,
        MetricSnapshot,
        TimeInterval,
    )
    from framework.proposal.core import propose

    slot = slot_at("15:30")
    hour = TimeInterval(
        start=slot.replace(hour=16, minute=0),
        end=slot.replace(hour=17, minute=0),
    )
    inner = _DownWonder()
    clock = _Clock(slot)
    commitment = Commitment.model_validate(
        {
            "id": "b-1",
            "profile_id": "builder",
            "title": "Morning pages draft",
            "kind": "build",
            "dimension": "love",
            "evidence": "github_push",
        }
    )
    client = DeadlineWonderClient(
        make_client=lambda timeout_s: inner,
        deadline=slot - timedelta(seconds=1),
        clock=clock,
    )
    assert client.transport == "muse"
    context = GateContext(
        facts={},
        metrics=MetricSnapshot(values={"period.last.pushes": 3.0}),
        parent_briefing=None,
        parent_metrics=None,
        free_intervals=(),
        busy_intervals=(),
        limits=SLOT_LIMITS,
        private_terms=(),
        private_terms_available=False,
        forbidden_raw_literals=(),
        commitments=(commitment,),
        commitments_available=True,
    )
    result = propose(
        profile_id="builder",
        subject_id=SUBJECT,
        slot=slot,
        as_of=slot,
        cycle_id="cycle-x",
        run=1,
        hour=hour,
        eligible=(commitment,),
        context=context,
        client=client,  # type: ignore[arg-type]
        models=MODEL_PARAMS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=slot,
        offered={},
    )
    assert result.kind == "fallback"
    assert ("MODEL_UNAVAILABLE", "slot deadline") in result.attempts[0].codes


def test_wonder_down_fallback_says_why_and_watchdog_reports_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot, wonder=_DownWonder("synthetic down"))
    harness.clock.now = slot - timedelta(minutes=25)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    propose_rows = [row for row in rows if row.step == "propose_builder"]
    assert propose_rows and propose_rows[0].outcome == "fallback"
    assert "transport=muse" in propose_rows[0].detail
    assert "wonder_down=1" in propose_rows[0].detail
    assert "FALLBACK_MODEL_UNAVAILABLE" in propose_rows[0].detail
    code = check_slot(slot=slot, db_path=harness.db, seams=harness.seams)
    out = capsys.readouterr().out
    assert code == 5
    assert "code=DEGRADED detail=FALLBACK_SIDE" in out
    code = check_slot(slot=slot, db_path=harness.db, seams=harness.seams)
    out = capsys.readouterr().out
    assert code == 5
    assert "code=DEGRADED detail=MODEL_DOWN" in out
    code = check_slot(slot=slot, db_path=harness.db, seams=harness.seams)
    out = capsys.readouterr().out
    assert code == 5
    assert "code=DEGRADED detail=WONDER_TRANSPORT" in out
    code = check_slot(slot=slot, db_path=harness.db, seams=harness.seams)
    out = capsys.readouterr().out
    assert code == 0
    assert "code=DEGRADED_REPEAT" in out


def test_no_facts_at_all_gives_fallbacks_with_no_prose(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from framework.cycle import orchestrator

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("synthetic locked")

    monkeypatch.setattr(orchestrator, "run_cycle", _boom)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    sides = SlotLedger(harness.db).slot_cards_for_slot(slot)
    assert sides != ()
    assert {side.kind for side in sides} == {"fallback"}
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "OperationalError" in [
        row.outcome for row in rows if row.step == "facts_code"
    ]


def test_dry_run_builds_no_telegram_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    slot = slot_at("15:30")
    clock = _Clock(slot)

    class _Exploding:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError("dry run must build no client")

    seams = Seams(
        facts=_Facts(_down_result()),
        wonder=lambda terms, deadline: _DownWonder(),
        telegram=_Exploding(),  # type: ignore[arg-type]
        clock=clock,
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    code = run_slot(
        slot=slot,
        subject_id=SUBJECT,
        db_path=tmp_path / "cycle.db",
        dry_run=True,
        no_wait=True,
        seams=seams,
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "dry=1" in out
    assert "card=card-" in out


def test_nothing_private_reaches_logs_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path, titles="canary")
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, err = _run(slot, harness, capsys)
    assert code == 0, out
    assert "CanaryTitle" not in out
    assert "CanaryTitle" not in err
    for detail in _details(slot, harness.db):
        assert "CanaryTitle" not in detail


def test_nothing_private_reaches_logs_on_failure_arms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path, titles="canary")
    slot = slot_at("15:30")

    def _boom_facts(**kwargs: Any) -> FactsChildResult:
        raise RuntimeError("canary-boom-facts")

    harness = _harness(tmp_path, slot)
    harness.clock.now = slot - timedelta(minutes=25)
    harness.seams = Seams(
        facts=_boom_facts,
        wonder=harness.seams.wonder,
        telegram=harness.telegram,
        clock=harness.clock,
        sleep=harness.sleeps.append,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    code, out, err = _run(slot, harness, capsys)
    assert code == 0, out
    assert "canary-boom-facts" not in out
    assert "canary-boom-facts" not in err
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "RuntimeError" in [row.outcome for row in rows if row.step == "facts_model"]
    for row in rows:
        assert "canary-boom-facts" not in row.outcome
        assert "canary-boom-facts" not in row.detail
        assert "CanaryTitle" not in row.detail


def test_terms_and_commitments_unavailable_send_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    monkeypatch.setenv("HIDDEN_CRITERIA_DIR", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir(exist_ok=True)
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=TERMS_UNAVAILABLE" in out
    assert harness.facts.calls == []
    _env(monkeypatch, tmp_path)
    (tmp_path / "commitments.json").write_text("[]")
    harness = _harness(tmp_path / "second", slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=COMMITMENTS_UNAVAILABLE" in out
    assert harness.facts.calls == []


# -- contributor and transport --


def test_run_slot_has_no_model_option_and_constants_hold_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        cycle_main.main(
            [
                "run-slot",
                "--slot",
                slot_at("15:30").isoformat(),
                "--model",
                "muse-wonder-1.0",
            ]
        )
    assert "contributor" not in MODEL_PARAMS.first_model
    assert "contributor" not in MODEL_PARAMS.retry_model


def test_contributor_model_refused_before_any_runner_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from framework.proposal.client import ContributorModelRefused
    from framework.proposal.core import WonderRequest
    from framework.proposal.muse_client import MuseExecClient, RunResult

    seen: list[dict[str, Any]] = []

    def _fake_runner(argv: Any, *, env: Any, timeout_s: float, cwd: Any) -> RunResult:
        seen.append(dict(env))
        return RunResult(0, b"{}", False)

    monkeypatch.setenv("MUSE_NO_AUTO_UPDATE", "1")
    client = MuseExecClient(
        private_terms=(),
        private_terms_available=True,
        muse_bin="/fake/muse",
        runner=_fake_runner,  # type: ignore[arg-type]
    )
    request = WonderRequest(
        prompt="synthetic",
        model="contributor-test",
        effort="high",
        response_schema={},
    )
    with pytest.raises(ContributorModelRefused):
        client.complete(request)
    assert seen == []
    request = WonderRequest(
        prompt="synthetic",
        model="muse-wonder-1.0",
        effort="high",
        response_schema={},
    )
    with pytest.raises(MetaUnavailableError):
        client.complete(request)
    assert seen != []
    assert seen[0].get("MUSE_NO_AUTO_UPDATE") == "1"


# -- D9 parents, D17 two cycles, D15 stale --


def test_parents_dict_missing_profile_means_no_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch, tmp_path)
    from framework.briefing import load_commitments
    from framework.briefing.context import MetricSnapshot, load_private_terms
    from framework.cycle import run_proposals as _real_run_proposals

    db = tmp_path / "cycle.db"
    store = EventStore(db_path=db)
    try:
        fact_store = FactStore(db_path=store.db_path)
        try:
            proposal_store = ProposalStore(db_path=store.db_path)
            try:
                first, second = slot_at("13:30"), slot_at("15:30")
                as_of = first - timedelta(minutes=25)
                from framework.cycle import run_cycle as _run_cycle

                class _Stub:
                    def complete(self, prompt: str) -> Any:
                        raise AssertionError("no model")

                _run_cycle(as_of, SUBJECT, store, fact_store, _Stub())  # type: ignore[arg-type]
                terms = load_private_terms()
                loaded = load_commitments(os.environ, private_terms=terms.terms)
                assert loaded.available
                eligible = {
                    item.profile_id: tuple(
                        entry
                        for entry in loaded.commitments
                        if entry.profile_id == item.profile_id
                    )
                    for item in loaded.commitments
                }
                spy = _ProposeSpy()
                monkeypatch.setattr("framework.cycle.propose", spy)
                _real_run_proposals(
                    as_of=as_of,
                    slot=first,
                    subject_id=SUBJECT,
                    profiles=("builder", "disconnect"),
                    store=store,
                    fact_store=fact_store,
                    proposal_store=proposal_store,
                    client=_DownWonder(),
                    private_terms=terms,
                    eligible_by_profile=eligible,
                    limits=SLOT_LIMITS,
                    models=MODEL_PARAMS,
                    stale_after_s=STALE_AFTER_S,
                    cycle_id=None,
                    policy_by_profile={},
                    parents=None,
                )
                assert spy.calls == 2
                parent_briefing = Briefing.model_validate(
                    _briefing_dict("b-1", "builder", second)
                )
                spy2 = _ProposeSpy()
                monkeypatch.setattr("framework.cycle.propose", spy2)
                _real_run_proposals(
                    as_of=as_of,
                    slot=second,
                    subject_id=SUBJECT,
                    profiles=("builder", "disconnect"),
                    store=store,
                    fact_store=fact_store,
                    proposal_store=proposal_store,
                    client=_DownWonder(),
                    private_terms=terms,
                    eligible_by_profile=eligible,
                    limits=SLOT_LIMITS,
                    models=MODEL_PARAMS,
                    stale_after_s=STALE_AFTER_S,
                    cycle_id=None,
                    policy_by_profile={},
                    parents={
                        "builder": (
                            parent_briefing,
                            MetricSnapshot(values={}),
                        )
                    },
                )
                assert spy2.calls == 2
                assert spy2.contexts is not None
                assert spy2.contexts["builder"].parent_briefing is parent_briefing
                assert spy2.contexts["disconnect"].parent_briefing is None
            finally:
                proposal_store.close()
        finally:
            fact_store.close()
    finally:
        store.close()


def test_run_slot_parents_come_only_from_delivered_cards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    from framework.briefing.context import TimeInterval

    first = slot_at("13:30")
    harness = _harness(tmp_path, first)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(first, harness, capsys)
    assert code == 0, out
    second = slot_at("15:30")
    harness2 = _harness(tmp_path / "second", second)
    import shutil

    harness2.db.parent.mkdir(parents=True, exist_ok=True)
    _checkpoint(harness.db)
    shutil.copy(harness.db, harness2.db)
    store = EventStore(db_path=harness2.db)
    proposal_store = ProposalStore(db_path=store.db_path)
    try:
        ghost = spy(
            profile_id="disconnect",
            subject_id=SUBJECT,
            slot=slot_at("14:00"),
            as_of=second,
            cycle_id="cycle-ghost",
            run=1,
            hour=TimeInterval(start=slot_at("14:00"), end=slot_at("15:00")),
            eligible=[SimpleNamespace(id="d-9")],
            context=None,
            client=None,
            models=MODEL_PARAMS,
            policy="",
            stale_after_s=STALE_AFTER_S,
            cycle_as_of=second,
            offered={},
        )
        proposal_store.record(ghost, snapshot={})
    finally:
        proposal_store.close()
        store.close()
    _checkpoint(harness2.db)
    spy2 = _ProposeSpy()
    monkeypatch.setattr("framework.cycle.propose", spy2)
    code, out, _ = _run(second, harness2, capsys)
    assert code == 0, out
    assert spy2.contexts is not None
    assert spy2.contexts["builder"].parent_briefing is not None
    assert spy2.contexts["disconnect"].parent_briefing is None


def test_refused_then_fresh_fallback_slot_is_no_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A refused slot re-run fresh with fallbacks leaves no proposal parent.

    The later slot falls back to the earlier delivered proposal for Builder
    and to no parent for Disconnect.
    """
    from framework import cycle as cycle_pkg
    from framework.telegram.client import TelegramAuthError

    _env(monkeypatch, tmp_path)
    real_propose = cycle_pkg.propose
    first = slot_at("13:30")
    harness = _harness(tmp_path, first)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(first, harness, capsys)
    assert code == 0, out
    assert spy.calls == 1
    second = slot_at("15:30")
    refused = _harness(
        tmp_path, second, telegram=_Telegram(fail_all=TelegramAuthError("nope"))
    )
    code, out, _ = _run(second, refused, capsys)
    assert code == 1, out
    assert "code=SEND_REFUSED" in out
    fresh = _harness(tmp_path, second)
    monkeypatch.setattr("framework.cycle.propose", real_propose)
    code, out, _ = _run(second, fresh, capsys, fresh=True)
    assert code == 0, out
    kinds = {
        side.profile_id: side.kind
        for side in SlotLedger(fresh.db).slot_cards_for_card(
            SlotLedger(fresh.db).latest_card_id(second) or ""
        )
    }
    assert kinds.get("builder") == "fallback"
    third = slot_at("20:30")
    later = _harness(tmp_path, third)
    spy3 = _ProposeSpy()
    monkeypatch.setattr("framework.cycle.propose", spy3)
    code, out, _ = _run(third, later, capsys)
    assert code == 0, out
    assert spy3.contexts is not None
    builder_parent = spy3.contexts["builder"].parent_briefing
    assert builder_parent is not None
    assert builder_parent.slot == first
    assert spy3.contexts["disconnect"].parent_briefing is None


def test_two_cycles_at_one_as_of_propose_from_the_model_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    from evals.glimmer_cases import RecordingLLM, base_case
    from framework.cycle import run_cycle as _run_cycle
    from framework.store.fact_store import FactStore as _FactStore

    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    db = tmp_path / "seed.db"
    store = EventStore(db_path=db)
    try:
        from framework.schemas.events import Event as _Event

        def _screen(eid: str) -> _Event:
            moment = as_of - timedelta(hours=1)
            return _Event.model_validate(
                {
                    "id": eid,
                    "subject_id": SUBJECT,
                    "source": "activitywatch",
                    "type": "screen.hour",
                    "time": moment.isoformat(),
                    "source_id": f"mac:{eid}",
                    "data": {
                        "type": "screen.hour",
                        "device": "mac",
                        "minutes_by_category": {"code": 60.0},
                    },
                    "tier": "private",
                    "collected_at": moment.isoformat(),
                    "collector_version": "synthetic@0.1.0",
                }
            )

        store.append_events([_screen("seed-screen-1")])
        fact_store = _FactStore(db_path=store.db_path)
        try:

            class _Stub:
                def complete(self, prompt: str) -> Any:
                    raise AssertionError("no model")

            code_result, _ = _run_cycle(
                as_of,
                SUBJECT,
                store,
                fact_store,
                _Stub(),  # type: ignore[arg-type]
                personal_pass=False,
                feed_pass=False,
            )
            case = base_case()
            model_result, _ = _run_cycle(
                as_of,
                SUBJECT,
                store,
                fact_store,
                RecordingLLM(personal=case.personal_texts, feed=case.feed_texts),
            )
        finally:
            fact_store.close()
    finally:
        store.close()
    assert code_result.cycle_id != model_result.cycle_id
    harness = _harness(
        tmp_path, slot, facts=FactsChildResult("ok", model_result.cycle_id, 1)
    )
    harness.clock.now = slot - timedelta(minutes=25)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    import framework.store.fact_store as fact_store_module

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("run_slot never fetches the latest cycle")

    monkeypatch.setattr(fact_store_module.FactStore, "fetch_latest_cycle", _boom)
    import shutil

    _checkpoint(db)
    shutil.copy(db, harness.db)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert spy.cycles == {
        "builder": model_result.cycle_id,
        "disconnect": model_result.cycle_id,
    }
    details = _details(slot, harness.db)
    assert any(f"cycle={model_result.cycle_id}" in detail for detail in details)
    propose_details = [
        row.detail
        for row in SlotLedger(harness.db).rows_for_slot(slot)
        if row.step.startswith("propose_")
    ]
    assert propose_details
    assert not any(f"cycle={code_result.cycle_id}" in d for d in propose_details)


def test_stale_slot_sends_nothing_and_explains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("13:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot + timedelta(minutes=31)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=STALE_CARD" in out
    assert harness.telegram.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "STALE_CARD" in [row.outcome for row in rows if row.step == "done"]


# -- check-slot exit codes --


def _checkpoint(db: Path) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


def _check_harness(tmp_path: Path, slot: datetime, *, timeout: float = 300.0) -> Seams:
    return Seams(
        facts=_Facts(_down_result()),
        wonder=lambda terms, deadline: _DownWonder(),
        telegram=None,
        clock=_Clock(slot),
        sleep=lambda s: None,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
        check_timeout_s=timeout,
        check_poll_s=0.01,
    )


def _check(
    slot: datetime, db: Path, seams: Seams, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    code = check_slot(slot=slot, db_path=db, seams=seams)
    return code, capsys.readouterr().out


@pytest.mark.parametrize(
    "done_code",
    [
        "delivered",
        "STALE_CARD",
        "killed",
        "SLOT_NOT_PINNED",
        "NOOP_NO_FREE_HOUR",
        "NOOP_SLOT_OUTSIDE_ALLOWED_HOURS",
        "NOOP_NO_ELIGIBLE_COMMITMENT",
        "NOOP_MIXED",
        "DISCONNECT_DAILY_CAP",
        "DISCONNECT_AFTER_CUTOFF",
    ],
)
def test_check_exit_zero_for_explained_codes(
    tmp_path: Path, done_code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.append_step(slot, "done", done_code, 0.1, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0, out
    assert f"code={done_code if done_code != 'delivered' else 'DELIVERED'}" in out


@pytest.mark.parametrize(
    "seed",
    [
        ("rows_without_done", "UNEXPLAINED"),
        ("intent_open", "DELIVERY_UNKNOWN"),
        ("unknown", "DELIVERY_UNKNOWN"),
        ("not_sent", "SEND_NOT_SENT"),
        ("refused", "SEND_REFUSED"),
        ("preflight", "PREFLIGHT_RULES_FILE"),
        ("commitments", "COMMITMENTS_UNAVAILABLE"),
        ("terms", "TERMS_UNAVAILABLE"),
        ("chart", "CHART_FAILED"),
        ("outbound", "NOOP_OUTBOUND_BLOCKED"),
    ],
)
def test_check_exit_one_for_alerts(
    tmp_path: Path,
    seed: tuple[str, str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    name, wanted = seed
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    if name == "rows_without_done":
        pass
    elif name == "intent_open":
        ledger.append_step(slot, "send_intent", "intent", 0.1, "card-x", None)
    elif name == "unknown":
        ledger.append_step(slot, "send_intent", "intent", 0.1, "card-x", None)
        ledger.append_step(slot, "send", "DELIVERY_UNKNOWN", 0.1, "card-x", None)
    elif name == "not_sent":
        ledger.append_step(slot, "send_intent", "intent", 0.1, "card-x", None)
        ledger.append_step(slot, "send", "SEND_NOT_SENT", 0.1, "card-x", None)
    elif name == "refused":
        ledger.append_step(slot, "send_intent", "intent", 0.1, "card-x", None)
        ledger.append_step(slot, "send", "SEND_REFUSED", 0.1, "card-x", None)
    elif name in ("preflight", "commitments", "terms", "chart"):
        codes = {
            "preflight": "PREFLIGHT_RULES_FILE",
            "commitments": "COMMITMENTS_UNAVAILABLE",
            "terms": "TERMS_UNAVAILABLE",
            "chart": "CHART_FAILED",
        }
        ledger.append_step(slot, name, codes[name], 0.1, None, None)
    else:
        ledger.append_step(slot, "done", wanted, 0.1, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 1, out
    assert f"code={wanted}" in out


def test_check_no_run_is_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slot = slot_at("15:30")
    code, out = _check(
        slot, tmp_path / "cycle.db", _check_harness(tmp_path, slot), capsys
    )
    assert code == 1
    assert "code=NO_RUN" in out


def test_check_wait_with_lock_held_then_released(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import fcntl

    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    SlotLedger(db).append_step(slot, "start", "ok", 0.0, None, None)
    lock_path = Path(str(db) + ".run-slot.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, out = _check(
            slot, db, _check_harness(tmp_path, slot, timeout=0.05), capsys
        )
        assert code == 4
        assert "code=SLOT_STILL_RUNNING" in out
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)


def test_check_degraded_fallback_side_reports_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.append_step(slot, "send_intent", "intent", 0.1, "card-x", None)
    ledger.append_step(slot, "send", "delivered", 0.2, "card-x", None)
    ledger.save_slot_cards(
        (
            SlotCardRow(
                card_id="card-x",
                letter="A",
                slot=slot,
                subject_id=SUBJECT,
                as_of=slot,
                bucket="afternoon",
                profile_id="builder",
                commitment_id="b-1",
                kind="fallback",
                policy_pick=None,
                policy_alternative=None,
            ),
        )
    )
    ledger.append_step(slot, "done", "delivered", 0.3, "card-x", None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 5
    assert "code=DEGRADED detail=FALLBACK_SIDE" in out
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0
    assert "code=DEGRADED_REPEAT" in out


def test_check_degraded_facts_model_reports_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.append_step(slot, "facts_model", "MODEL_DOWN", 0.1, None, None)
    ledger.append_step(slot, "done", "STALE_CARD", 0.2, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 5
    assert "code=DEGRADED detail=MODEL_DOWN" in out
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0
    assert "code=DEGRADED_REPEAT" in out


# -- wrapper, rules file, sanitise --


def test_wrapper_forwards_harness_rules_file() -> None:
    inner = SimpleNamespace(
        transport="muse", transport_version=None, harness_rules_file=True
    )
    clock = _Clock(slot_at("15:30"))
    client = DeadlineWonderClient(
        make_client=lambda timeout_s: inner,  # type: ignore[arg-type]
        deadline=clock.now + timedelta(seconds=100),
        clock=clock,
    )
    assert client.harness_rules_file is True
    assert client.transport == "muse"
    plain = SimpleNamespace(
        transport="muse", transport_version=None, harness_rules_file=None
    )
    client = DeadlineWonderClient(
        make_client=lambda timeout_s: plain,  # type: ignore[arg-type]
        deadline=clock.now + timedelta(seconds=100),
        clock=clock,
    )
    assert client.harness_rules_file is None


@dataclass(frozen=True)
class _HarnessAttempt:
    number: int = 1
    model_requested: str = "muse-wonder-1.0"
    model_reported: str = "muse-wonder-1.0"
    effort: str = "high"
    prompt_hash: str = "abc"
    raw_text: str = ""
    parsed_ok: bool = True
    blocked: bool = False
    codes: tuple[tuple[str, str], ...] = ()
    latency_ms: int = 5
    prompt_tokens: int | None = None
    completion_tokens: int | None = 3
    reasoning_tokens: int | None = None
    finish_reason: str | None = "completed"
    cached_tokens: int | None = None
    transport: str = "muse"
    transport_version: str | None = "fake version 1.0"
    harness_rules_file: bool | None = None


def test_propose_row_carries_rules_file_only_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    spy = _ProposeSpy(attempts=(_HarnessAttempt(harness_rules_file=True),))
    _patch_propose(monkeypatch, spy)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    details = _details(slot, harness.db)
    assert any("rules_file=1" in detail for detail in details)
    assert any("transport_version=fake_version_1.0" in d for d in details)
    other = slot_at("18:00")
    harness2 = _harness(tmp_path / "plain", other)
    spy2 = _ProposeSpy(attempts=(_HarnessAttempt(harness_rules_file=None),))
    _patch_propose(monkeypatch, spy2)
    code, out, _ = _run(other, harness2, capsys)
    assert code == 0, out
    assert not any("rules_file" in d for d in _details(other, harness2.db))


# -- cli edge --


def test_cli_edge_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cycle_main.main(["run-slot", "--subject-id", SUBJECT])
    with pytest.raises(SystemExit):
        cycle_main.main(
            [
                "run-slot",
                "--slot",
                slot_at("15:30").isoformat(),
                "--slot-today",
                "15:30",
            ]
        )
    with pytest.raises(SystemExit):
        cycle_main.main(
            [
                "check-slot",
                "--slot",
                slot_at("15:30").isoformat(),
                "--slot-today",
                "15:30",
            ]
        )
    assert (
        cycle_main.main(
            [
                "run-slot",
                "--slot",
                "not-a-time",
                "--subject-id",
                SUBJECT,
                "--db",
                str(tmp_path / "a.db"),
            ]
        )
        == 2
    )
    assert (
        cycle_main.main(
            [
                "run-slot",
                "--slot",
                slot_at("15:30").isoformat(),
                "--db",
                str(tmp_path / "a.db"),
            ]
        )
        == 2
    )
    assert (
        cycle_main.main(
            [
                "run-slot",
                "--slot",
                slot_at("15:30").isoformat(),
                "--subject-id",
                SUBJECT,
                "--db",
                str(tmp_path / "a.db"),
                "--lead-minutes",
                "many",
            ]
        )
        == 2
    )


def test_one_side_at_1330_two_at_1530(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _env(monkeypatch, tmp_path)
    _patch_propose(monkeypatch, _ProposeSpy())
    first = slot_at("13:30")
    harness = _harness(tmp_path / "early", first)
    code, out, _ = _run(first, harness, capsys)
    assert code == 0, out
    sides = SlotLedger(harness.db).slot_cards_for_slot(first)
    assert [side.letter for side in sides] == ["A"]
    assert [side.profile_id for side in sides] == ["builder"]
    second = slot_at("15:30")
    harness = _harness(tmp_path / "late", second)
    code, out, _ = _run(second, harness, capsys)
    assert code == 0, out
    sides = SlotLedger(harness.db).slot_cards_for_slot(second)
    assert [(side.letter, side.profile_id) for side in sides] == [
        ("A", "builder"),
        ("B", "disconnect"),
    ]


# -- slice 3 review fixes (made-up data) --


def _seed_code_events(db: Path) -> None:
    """One public push and one private screen hour inside the code window."""
    from framework.schemas.events import Event as _Event

    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    moment = as_of - timedelta(hours=1)
    store = EventStore(db_path=db)
    try:
        store.append_events(
            [
                _Event.model_validate(
                    {
                        "id": "seed-push-1",
                        "subject_id": SUBJECT,
                        "source": "github",
                        "type": "github.push",
                        "time": moment.isoformat(),
                        "source_id": "push-seed-1",
                        "data": {
                            "type": "github.push",
                            "repo": "madeup/repo",
                            "counts": {"commits": 2},
                        },
                        "tier": "public",
                        "collected_at": moment.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                ),
                _Event.model_validate(
                    {
                        "id": "seed-screen-1",
                        "subject_id": SUBJECT,
                        "source": "activitywatch",
                        "type": "screen.hour",
                        "time": moment.isoformat(),
                        "source_id": "mac:seed-1",
                        "data": {
                            "type": "screen.hour",
                            "device": "mac",
                            "minutes_by_category": {"code": 60.0},
                        },
                        "tier": "private",
                        "collected_at": moment.isoformat(),
                        "collector_version": "synthetic@0.1.0",
                    }
                ),
            ]
        )
    finally:
        store.close()


def test_code_cycle_runs_with_both_passes_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real code cycle runs in-process; propose gets the code cycle id."""
    _env(monkeypatch, tmp_path)
    from framework.cycle import orchestrator

    slot = slot_at("15:30")
    _seed_code_events(tmp_path / "cycle.db")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    code_rows = [row for row in rows if row.step == "facts_code"]
    assert [row.outcome for row in code_rows] == ["ok"]
    cycle_id = orchestrator.parse_detail(code_rows[-1].detail).get("cycle")
    assert cycle_id
    fact_store = FactStore(db_path=harness.db)
    try:
        runs = fact_store.runs(cycle_id)
        assert runs
        facts = fact_store.fetch_facts(cycle_id, max(runs))
        assert facts
        assert {row["origin"] for row in facts} == {"code"}
    finally:
        fact_store.close()
    for profile in ("propose_builder", "propose_disconnect"):
        details = [row.detail for row in rows if row.step == profile]
        assert details, profile
        assert any(f"cycle={cycle_id}" in detail for detail in details), profile


def test_resume_after_intent_skips_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A re-run after a send crash goes straight to the send state rules."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=KeyboardInterrupt("boom"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=harness.db,
            no_wait=True,
            seams=harness.seams,
        )
    capsys.readouterr()
    (tmp_path / "commitments.json").unlink()

    def _boom_facts(**kwargs: Any) -> FactsChildResult:
        raise AssertionError("facts must not run on resume")

    def _boom_wonder(terms: Any, deadline: Any) -> Any:
        raise AssertionError("wonder must not run on resume")

    resume = Seams(
        facts=_boom_facts,
        wonder=_boom_wonder,
        telegram=telegram,
        clock=harness.clock,
        sleep=harness.sleeps.append,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    code = run_slot(
        slot=slot,
        subject_id=SUBJECT,
        db_path=harness.db,
        no_wait=True,
        seams=resume,
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(telegram.calls) == 1


def test_resend_unknown_refused_on_delivered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--resend-unknown` on a delivered slot refuses before `ALREADY_DONE`."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    code, out, _ = _run(slot, harness, capsys, resend_unknown=True)
    assert code == 2
    assert "code=RESEND_NOT_UNKNOWN" in out


def test_resend_unknown_on_intent_open_sends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--resend-unknown` on a crashed send records unknown, then sends."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    telegram = _Telegram(fail_first=KeyboardInterrupt("boom"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=harness.db,
            no_wait=True,
            seams=harness.seams,
        )
    capsys.readouterr()
    code, out, _ = _run(slot, harness, capsys, resend_unknown=True)
    assert code == 0, out
    assert len(telegram.calls) == 2
    outcomes = [row.outcome for row in SlotLedger(harness.db).rows_for_slot(slot)]
    assert "DELIVERY_UNKNOWN" in outcomes
    assert "delivered" in outcomes
    assert any("resend_unknown=1" in detail for detail in _details(slot, harness.db))


def test_facts_model_failure_counts_as_complete_on_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A re-run after `MODEL_DOWN` does not restart the facts child."""
    from framework.cycle import orchestrator

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot - timedelta(minutes=25)
    real_hour = orchestrator.plan_hour
    state = {"calls": 0}

    def _once(**kwargs: Any) -> Any:
        if state["calls"] == 0:
            state["calls"] += 1
            raise KeyboardInterrupt("boom")
        return real_hour(**kwargs)

    monkeypatch.setattr(orchestrator, "plan_hour", _once)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=harness.db,
            no_wait=True,
            seams=harness.seams,
        )
    capsys.readouterr()
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.facts.calls or []) == 1
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert len([row for row in rows if row.step == "facts_model"]) == 1


def test_skipped_facts_row_written_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A re-run after `SKIPPED` does not write the row again."""
    from framework.cycle import orchestrator
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(
        tmp_path, slot, telegram=_Telegram(fail_all=TelegramTransportError("down"))
    )
    real_hour = orchestrator.plan_hour
    state = {"calls": 0}

    def _once(**kwargs: Any) -> Any:
        if state["calls"] == 0:
            state["calls"] += 1
            raise KeyboardInterrupt("boom")
        return real_hour(**kwargs)

    monkeypatch.setattr(orchestrator, "plan_hour", _once)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=harness.db,
            no_wait=True,
            skip_local_model=True,
            seams=harness.seams,
        )
    capsys.readouterr()
    code, out, _ = _run(slot, harness, capsys, skip_local_model=True)
    assert code == 1
    assert "code=SEND_NOT_SENT" in out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert len([row for row in rows if row.step == "facts_model"]) == 1
    assert harness.facts.calls == []


def test_refusal_writes_nothing_and_forced_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unpinned slot refuses with no ledger row; `--force-slot` runs it."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("16:00")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 2
    assert "code=SLOT_NOT_PINNED" in out
    assert SlotLedger(harness.db).rows_for_slot(slot) == ()
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 0
    assert "code=SLOT_NOT_PINNED" in check_out
    code, out, _ = _run(slot, harness, capsys, force_slot=True)
    assert code == 0, out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert _detail_for(rows, "forced") == "1"


def test_dry_run_takes_no_lock_and_cleans_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A dry run runs under a held lock and leaves no copy behind."""
    import fcntl
    import tempfile

    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    copies: list[Path] = []
    real_mkstemp = tempfile.mkstemp

    def _spy_mkstemp(*args: Any, **kwargs: Any) -> Any:
        made = real_mkstemp(*args, **kwargs)
        copies.append(Path(made[1]))
        return made

    monkeypatch.setattr(tempfile, "mkstemp", _spy_mkstemp)
    lock_path = Path(str(harness.db) + ".run-slot.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    held = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, out, _ = _run(slot, harness, capsys, dry_run=True)
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        os.close(held)
    assert code == 0, out
    assert "dry=1" in out
    assert copies
    for copy in copies:
        assert not copy.exists()
        assert not Path(str(copy) + "-wal").exists()
        assert not Path(str(copy) + "-shm").exists()
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out


def test_check_killed_last_row_is_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A slot whose last row says `killed` checks as `killed`, exit 0."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.append_step(slot, "facts_model", "killed", 0.1, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0
    assert "code=killed" in out


def test_check_rows_without_done_are_unexplained(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rows with no `done` and no explanation check as `UNEXPLAINED`."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    SlotLedger(db).append_step(slot, "start", "ok", 0.0, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 1
    assert "code=UNEXPLAINED" in out


def test_commitment_gone_card_has_no_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A card whose sides all dropped writes a card row and no `done` row."""

    def _gone(**kwargs: Any) -> ProposalResult:
        from framework.briefing import Briefing

        profile = str(kwargs["profile_id"])
        briefing = Briefing.model_validate(
            _briefing_dict("gone-1", profile, kwargs["slot"])
        )
        return ProposalResult(
            kind="proposal",
            profile_id=profile,  # type: ignore[arg-type]
            subject_id=kwargs["subject_id"],
            cycle_id=kwargs["cycle_id"],
            run=kwargs["run"],
            slot=kwargs["slot"],
            hour=kwargs["hour"],
            briefing=briefing,
            fallback=None,
            reason_codes=(),
            attempts=(),
            cycle_age_s=0.0,
            prompt_hash="",
        )

    _env(monkeypatch, tmp_path)
    monkeypatch.setattr("framework.cycle.propose", _gone)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=COMMITMENT_GONE" in out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert [row.outcome for row in rows if row.step == "card"] == ["COMMITMENT_GONE"]
    assert [row for row in rows if row.step == "done"] == []
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 1
    assert "code=COMMITMENT_GONE" in check_out


def test_check_stored_card_with_nothing_after_is_unexplained(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A crash right after the card step is UNEXPLAINED, not COMMITMENT_GONE."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.save_card_step(
        slot, "card-a", {"codes": "-"}, card_rows("card-a", slot), "{}", "{}", 0.1
    )
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 1
    assert "code=UNEXPLAINED" in out


def test_check_chart_failed_card_reports_chart_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A card step that failed with CHART_FAILED is not COMMITMENT_GONE."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.append_step(slot, "card", "CHART_FAILED", 0.1, None, None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 1
    assert "code=CHART_FAILED" in out


def test_check_delivered_without_done_is_delivered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A crash between the delivered row and the done row is DELIVERED."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.save_card_step(
        slot, "card-a", {"codes": "-"}, card_rows("card-a", slot), "{}", "{}", 0.1
    )
    ledger.append_step(slot, "send_intent", "intent", 0.2, "card-a", None)
    ledger.append_step(slot, "send", "delivered", 0.3, "card-a", None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0
    assert "code=DELIVERED" in out


def test_check_retry_then_delivered_without_done_is_delivered(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A first unsent try then a delivered try with no done is DELIVERED."""
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    ledger = SlotLedger(db)
    ledger.append_step(slot, "start", "ok", 0.0, None, None)
    ledger.save_card_step(
        slot, "card-a", {"codes": "-"}, card_rows("card-a", slot), "{}", "{}", 0.1
    )
    ledger.append_step(slot, "send_intent", "intent", 0.2, "card-a", None)
    ledger.append_step(slot, "send", "SEND_NOT_SENT", 0.3, "card-a", None)
    ledger.append_step(slot, "send_intent", "intent", 0.4, "card-a", None)
    ledger.append_step(slot, "send", "delivered", 0.5, "card-a", None)
    code, out = _check(slot, db, _check_harness(tmp_path, slot), capsys)
    assert code == 0
    assert "code=DELIVERED" in out


def _noop_result(*codes: str) -> ProposalResult:
    return ProposalResult(
        kind="noop",
        profile_id="builder",
        subject_id=SUBJECT,
        cycle_id="cycle-x",
        run=1,
        slot=slot_at("15:30"),
        hour=None,
        briefing=None,
        fallback=None,
        reason_codes=tuple(codes),
        attempts=(),
        cycle_age_s=0.0,
        prompt_hash="",
    )


def test_noop_code_reads_first_noop_prefix_per_result() -> None:
    """Raw `CYCLE_STALE` and gate codes never become the slot's noop code."""
    from framework.cycle import orchestrator

    assert (
        orchestrator._noop_code([_noop_result("CYCLE_STALE", "NOOP_NO_FREE_HOUR")])
        == "NOOP_NO_FREE_HOUR"
    )
    assert (
        orchestrator._noop_code([_noop_result("NOOP_NO_ELIGIBLE_COMMITMENT")])
        == "NOOP_NO_ELIGIBLE_COMMITMENT"
    )
    assert (
        orchestrator._noop_code(
            [
                _noop_result("NOOP_OUTBOUND_BLOCKED"),
                _noop_result("NOOP_NO_ELIGIBLE_COMMITMENT"),
            ]
        )
        == "NOOP_OUTBOUND_BLOCKED"
    )
    assert (
        orchestrator._noop_code(
            [
                _noop_result("CYCLE_STALE"),
                _noop_result("NOOP_NO_ELIGIBLE_COMMITMENT"),
            ]
        )
        == "NOOP_NO_ELIGIBLE_COMMITMENT"
    )
    assert orchestrator._noop_code([_noop_result("CYCLE_STALE")]) == "NOOP_MIXED"


def test_chart_build_failure_sends_minimal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A chart build failure still delivers a card with the minimal chart."""
    from framework.cycle import orchestrator
    from framework.telegram.models import ChartData

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("synthetic tally failure")

    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(orchestrator, "build_chart_data", _boom)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert harness.telegram.calls != []
    assert "CHART_MINIMAL" in " ".join(_details(slot, harness.db))
    ledger = SlotLedger(harness.db)
    card_id = ledger.latest_card_id(slot)
    assert card_id is not None
    payload = ledger.load_card_payload(card_id)
    assert payload is not None
    chart = ChartData.model_validate_json(payload[1])
    assert chart.missing == ("screen", "pushes + PRs")


def test_stale_slot_spends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A real run past slot plus 30 minutes stops before any model call."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    harness.clock.now = slot + timedelta(minutes=31)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=STALE_CARD" in out
    assert harness.facts.calls == []
    assert harness.wonder.calls == 0
    assert harness.telegram.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert "STALE_CARD" in [row.outcome for row in rows if row.step == "done"]
    stale = slot_at("18:00")
    dry = _harness(tmp_path / "dry", stale)
    dry.clock.now = stale + timedelta(minutes=31)
    code, out, _ = _run(stale, dry, capsys, dry_run=True)
    assert code == 0, out
    assert "code=STALE_CARD" not in out
    assert "card=card-" in out


def test_cutoff_checked_before_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A retry whose clock crossed 23:00 stops with no second attempt."""
    from framework.telegram.client import TelegramTransportError

    _env(monkeypatch, tmp_path)
    slot = slot_at("22:30")
    telegram = _Telegram(fail_first=TelegramTransportError("connect-refused"))
    harness = _harness(tmp_path, slot, telegram=telegram)
    harness.clock.now = datetime(2026, 11, 2, 22, 59, 50, tzinfo=MADRID)

    def _advance(seconds: float) -> None:
        harness.clock.now = harness.clock.now + timedelta(seconds=seconds)

    harness.seams = Seams(
        facts=harness.facts,
        wonder=harness.seams.wonder,
        telegram=telegram,
        clock=harness.clock,
        sleep=_advance,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=DISCONNECT_AFTER_CUTOFF" in out
    assert len(telegram.calls) == 1
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert len([row for row in rows if row.step == "send_intent"]) == 1
    assert "DISCONNECT_AFTER_CUTOFF" in [
        row.outcome for row in rows if row.step == "done"
    ]


def test_lock_oserror_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An `OSError` opening the lock file is not another run."""
    _env(monkeypatch, tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("synthetic lock failure")

    monkeypatch.setattr(os, "open", _boom)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1
    assert "code=LOCK_UNAVAILABLE" in out


def test_manual_fallback_skips_hourless_side_and_explains_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No cycle and no hour writes a card row and a `done` row, no send."""
    import sqlite3

    from framework.cycle import orchestrator

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("synthetic locked")

    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(orchestrator, "run_cycle", _boom)
    monkeypatch.setattr(orchestrator, "plan_hour", lambda **kwargs: None)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert "code=NOOP_NO_FREE_HOUR" in out
    assert harness.telegram.calls == []
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert [row.outcome for row in rows if row.step == "card"] == ["NOOP_NO_FREE_HOUR"]
    assert [row.outcome for row in rows if row.step == "done"] == ["NOOP_NO_FREE_HOUR"]
    assert SlotLedger(harness.db).slot_cards_for_slot(slot) == ()


def test_manual_fallback_reuses_stored_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A re-run with no cycle reuses stored fallbacks, recording nothing new."""
    import sqlite3

    from framework.briefing.context import TimeInterval
    from framework.cycle import orchestrator
    from framework.store.proposal_store import ProposalStore

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("synthetic locked")

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    db = tmp_path / "cycle.db"
    hour = TimeInterval(start=slot + timedelta(hours=1), end=slot + timedelta(hours=2))
    seed = ProposalStore(db_path=db)
    try:
        for profile, cid in (("builder", "b-1"), ("disconnect", "d-1")):
            stored = orchestrator._manual_fallback(
                profile=profile,
                subject_id=SUBJECT,
                slot=slot,
                hour=hour,
                commitment=commitment(cid, profile),
            )
            seed.record(stored, snapshot={})
    finally:
        seed.close()
    monkeypatch.setattr(orchestrator, "run_cycle", _boom)
    recorded: list[str] = []
    real_record = ProposalStore.record

    def _count(self: ProposalStore, result: Any, **kwargs: Any) -> str:
        recorded.append(result.profile_id)
        return real_record(self, result, **kwargs)

    monkeypatch.setattr(ProposalStore, "record", _count)
    harness = _harness(tmp_path, slot)
    telegram_calls_before = len(harness.telegram.calls)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert recorded == []
    assert any("reused=1" in detail for detail in _details(slot, harness.db))
    assert len(harness.telegram.calls) > telegram_calls_before


def test_propose_row_carries_tokens_in(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The propose row keeps completion tokens and adds the prompt total."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    spy = _ProposeSpy(attempts=(_HarnessAttempt(prompt_tokens=7, completion_tokens=3),))
    _patch_propose(monkeypatch, spy)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert any("tokens=3" in detail for detail in _details(slot, harness.db))
    assert any("tokens_in=7" in detail for detail in _details(slot, harness.db))


def test_killed_after_facts_code_names_facts_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A kill landing after the code cycle stops at the facts step."""
    from framework.cycle import orchestrator
    from framework.cycle import run_cycle as _real_run_cycle

    _env(monkeypatch, tmp_path)
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    real = _real_run_cycle

    def _write_kill(*args: Any, **kwargs: Any) -> Any:
        kill.write_text("stop\n")
        return real(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "run_cycle", _write_kill)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0
    assert "code=killed" in out
    rows = SlotLedger(harness.db).rows_for_slot(slot)
    assert ("facts_code", "killed") in [(row.step, row.outcome) for row in rows]
    assert harness.facts.calls == []
    assert harness.telegram.calls == []


def test_lead_minutes_negative_is_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A negative `--lead-minutes` is a usage error, exit 2."""
    code = cycle_main.main(
        [
            "run-slot",
            "--slot",
            slot_at("15:30").isoformat(),
            "--subject-id",
            SUBJECT,
            "--db",
            str(tmp_path / "a.db"),
            "--lead-minutes",
            "-5",
        ]
    )
    assert code == 2
    assert "error: --lead-minutes must not be negative" in capsys.readouterr().err


def test_help_names_forced_outside_hours_builds_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`run-slot --help` says a forced run outside hours builds no proposal."""
    with pytest.raises(SystemExit) as excinfo:
        cycle_main.main(["run-slot", "--help"])
    assert excinfo.value.code == 0
    assert "builds no proposal" in capsys.readouterr().out


# -- slice 4: two-slot full run with real cycles and real proposals --


def _full_run_event(
    eid: str,
    etype: str,
    moment: datetime,
    data: dict[str, Any],
    *,
    tier: str = "public",
) -> Event:
    payload = dict(data)
    payload["type"] = etype
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": SUBJECT,
            "source": "github" if etype.startswith("github") else "activitywatch",
            "type": etype,
            "time": moment.isoformat(),
            "source_id": f"{etype}-{eid}",
            "data": payload,
            "tier": tier,
            "collected_at": (moment + timedelta(minutes=5)).isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


class _FullRunWonder:
    """A fake runner whose draft passes the gate: real kind=proposal cards."""

    transport = "muse"
    transport_version: str | None = "synthetic 1.0"
    harness_rules_file: bool | None = None

    def complete(self, request: Any) -> Any:
        import json as _json

        from framework.proposal.core import WonderResponse as _Response

        properties = request.response_schema["properties"]
        cids = properties["commitment_id"]["enum"]
        claim_schema = properties["overall_state"]["items"]["properties"]
        fact_ids = claim_schema.get("fact_ids", {}).get("items", {}).get("enum", [])
        metric_ids = (
            claim_schema.get("metric_refs", {}).get("items", {}).get("enum", [])
        )
        assert fact_ids, "the gate needs a fact to cite"
        assert "period.last.pushes" in metric_ids
        second = "since_last" in properties
        # Code facts record first, so the last id is the model fact.
        model_fact = fact_ids[-1]
        payload: dict[str, Any] = {
            "commitment_id": cids[0],
            "overall_state": [
                {
                    "text": "The recorded push activity stands as noted",
                    "fact_ids": [fact_ids[0]],
                    "metric_refs": [],
                }
            ],
            "working": [
                {
                    "text": "The recorded session stands as noted",
                    "fact_ids": [model_fact],
                    "metric_refs": [],
                }
            ],
            "not_working": [],
        }
        if second:
            payload["since_last"] = [
                {
                    "text": "Pushes rose 1 in last",
                    "fact_ids": [],
                    "metric_refs": ["period.last.pushes"],
                }
            ]
        return _Response(
            text=_json.dumps(payload),
            model_reported="synthetic",
            latency_ms=7,
            finish_reason="stop",
            prompt_tokens=11,
            completion_tokens=13,
            reasoning_tokens=None,
        )


def _model_stub_for(as_of: datetime, events: tuple[Event, ...]) -> Any:
    from evals.glimmer_cases import RecordingLLM, personal_batch
    from framework.glimmer.facts import ALLOWED_TYPES, MAX_PROMPT_EVENTS
    from framework.glimmer.metrics import select_winners as _winners

    winners = _winners(
        [
            event
            for event in events
            if event.type in ALLOWED_TYPES and event.collected_at <= as_of
        ]
    )
    prompt_rows = [e for e in winners if e.type != "feed.item"][-MAX_PROMPT_EVENTS:]
    alias = next(
        f"e{index + 1}"
        for index, event in enumerate(prompt_rows)
        if event.id == "evt-full-push-b"
    )
    return RecordingLLM(
        (
            personal_batch(
                {
                    "statement": "The recorded push activity stands as noted",
                    "evidence": [alias],
                }
            ),
        )
    )


def test_two_slot_full_run_with_real_cycles_and_proposals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two consecutive slots in one temp database, nothing patched in propose.

    The first card carries one side, the second two; the second since line
    counts the push collected between the two as_of values; a tap on the
    first card reaches replay at the second; trace reads the second card.
    """
    from framework.cycle import run_cycle as _run_cycle
    from framework.cycle.card_build import since_counts, since_line
    from framework.cycle.trace import trace as _trace
    from framework.glimmer.metrics import WINDOW as _WINDOW
    from framework.telegram.ledger import CardLedger

    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("IKIGAI_SUBJECT_ID", SUBJECT)
    first = slot_at("13:30")
    second = slot_at("15:30")
    as_of1 = first - timedelta(minutes=25)
    as_of2 = second - timedelta(minutes=25)
    seeds = (
        _full_run_event(
            "evt-full-push-a",
            "github.push",
            as_of1 - timedelta(hours=3),
            {"repo": "synthetic/quiet", "counts": {"commits": 2}},
        ),
        _full_run_event(
            "evt-full-push-b",
            "github.push",
            as_of1 - timedelta(hours=2),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
        ),
        _full_run_event(
            "evt-full-pr-a",
            "github.pr",
            as_of1 - timedelta(hours=4),
            {"repo": "synthetic/quiet", "counts": {"opened": 1}},
        ),
        _full_run_event(
            "evt-full-screen-a",
            "screen.hour",
            as_of1 - timedelta(hours=1),
            {"device": "mac", "minutes_by_category": {"code": 60.0}},
            tier="private",
        ),
        _full_run_event(
            "evt-full-push-c",
            "github.push",
            as_of1 + timedelta(minutes=30),
            {"repo": "synthetic/quiet", "counts": {"commits": 3}},
        ),
    )
    harness = _harness(tmp_path, first)
    harness.clock.now = first - timedelta(minutes=25)
    db = harness.db
    store = EventStore(db_path=db)
    try:
        assert store.append_events(list(seeds)) == len(seeds)
        fact_store = FactStore(db_path=store.db_path)
        try:
            model_ids: dict[str, tuple[str, int]] = {}
            for as_of in (as_of1, as_of2):
                made, run = _run_cycle(
                    as_of,
                    SUBJECT,
                    store,
                    fact_store,
                    _model_stub_for(as_of, seeds),
                    feed_pass=False,
                )
                model_ids[as_of.isoformat()] = (made.cycle_id, run)
        finally:
            fact_store.close()
    finally:
        store.close()

    def _facts(**kwargs: Any) -> FactsChildResult:
        cycle_id, run = model_ids[kwargs["as_of"].isoformat()]
        return FactsChildResult("ok", cycle_id, run)

    wonder = _FullRunWonder()
    harness = _Harness(
        db=harness.db,
        seams=dataclasses.replace(
            harness.seams,
            facts=_facts,  # type: ignore[arg-type]
            wonder=lambda terms, deadline: wonder,
        ),
        clock=harness.clock,
        facts=harness.facts,
        wonder=harness.wonder,
        telegram=harness.telegram,
        sleeps=harness.sleeps,
    )
    code, out, _ = _run(first, harness, capsys)
    assert code == 0, out
    ledger = SlotLedger(db)
    card1 = ledger.latest_card_id(first)
    assert card1 is not None
    sides1 = ledger.slot_cards_for_card(card1)
    assert len(sides1) == 1
    assert [side.kind for side in sides1] == ["proposal"]
    assert _outcome(ledger, first, "facts_code") == "ok"

    tap_store = EventStore(db_path=db)
    try:
        assert tap_store.append_event(
            tap("t-full-1", card1, "A", first + timedelta(minutes=5))
        )
    finally:
        tap_store.close()

    clock2 = _Clock(second - timedelta(minutes=25))
    seams2 = Seams(
        facts=_facts,  # type: ignore[arg-type]
        wonder=lambda terms, deadline: wonder,  # type: ignore[arg-type]
        telegram=harness.telegram,
        clock=clock2,
        sleep=harness.seams.sleep,
        home=harness.seams.home,
        ledger_sleep=lambda s: None,
    )
    harness2 = _Harness(
        db=db,
        seams=seams2,
        clock=clock2,
        facts=harness.facts,
        wonder=harness.wonder,
        telegram=harness.telegram,
        sleeps=[],
    )
    code, out, _ = _run(second, harness2, capsys)
    assert code == 0, out
    card2 = SlotLedger(db).latest_card_id(second)
    assert card2 is not None
    assert card2 != card1
    sides2 = SlotLedger(db).slot_cards_for_card(card2)
    assert len(sides2) == 2
    assert {side.kind for side in sides2} == {"proposal"}
    assert _outcome(SlotLedger(db), second, "facts_code") == "ok"

    rows2 = SlotLedger(db).slot_cards_for_card(card2)
    as_of2 = rows2[0].as_of
    rows1 = SlotLedger(db).slot_cards_for_card(card1)
    previous_as_of = rows1[0].as_of
    reader = EventStore(db_path=db)
    try:
        window = reader.events_between(SUBJECT, previous_as_of - _WINDOW, as_of2)
    finally:
        reader.close()
    counts = since_counts(window, previous_as_of, as_of2)
    card_text = CardLedger(db_path=db).load(card2)
    assert card_text is not None
    assert card_text.since_line == since_line(
        rows1[0].slot.astimezone(ZoneInfo("Europe/Madrid")),
        counts,
    )
    assert card_text.since_line is not None
    assert card_text.since_line.startswith("Since 13:30:")
    assert "push" in card_text.since_line

    stored = SlotLedger(db).learner_state_for_slot(second)
    assert stored is not None
    assert PolicyState.model_validate_json(stored).rulings_seen == 1

    assert _trace(card_id=card2, db_path=db) == 0
    traced = capsys.readouterr().out
    assert "origin=code" in traced
    assert "origin=model" in traced


def test_first_card_since_line_reads_plain_count_over_late_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """First card through run_slot: 2 recent pushes, 15 late old ones.

    The old rows are dated days earlier but first collected a few hours
    after the card's 24-hour bound, so a difference of totals would read
    17. The stored since line reads the plain count: 2.
    """
    from framework.telegram.ledger import CardLedger

    def _late(eid: str, etype: str, moment: datetime, collected: datetime) -> Event:
        counts = {"commits": 1} if etype == "github.push" else {"opened": 1}
        return Event.model_validate(
            {
                "id": eid,
                "subject_id": SUBJECT,
                "source": "github",
                "type": etype,
                "time": moment.isoformat(),
                "source_id": f"{etype}-{eid}",
                "data": {"type": etype, "repo": "madeup/repo", "counts": counts},
                "tier": "public",
                "collected_at": collected.isoformat(),
                "collector_version": "synthetic@0.1.0",
            }
        )

    _env(monkeypatch, tmp_path)
    slot = slot_at("13:30")
    as_of = slot - timedelta(minutes=25)
    previous = as_of - timedelta(hours=24)
    collected_late = previous + timedelta(hours=3)
    old_moment = datetime(2026, 10, 30, 12, 0, tzinfo=MADRID)
    harness = _harness(tmp_path, slot)
    store = EventStore(db_path=harness.db)
    try:
        rows = [
            _late(
                f"e-old-{index}",
                "github.pr" if index % 3 == 2 else "github.push",
                old_moment + timedelta(minutes=index),
                collected_late,
            )
            for index in range(15)
        ]
        rows.append(
            _late(
                "e-new-1",
                "github.push",
                slot.replace(hour=12, minute=0),
                slot.replace(hour=12, minute=1),
            )
        )
        rows.append(
            _late(
                "e-new-2",
                "github.push",
                slot.replace(hour=12, minute=30),
                slot.replace(hour=12, minute=31),
            )
        )
        assert store.append_events(rows) == len(rows)
    finally:
        store.close()
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run(slot, harness, capsys)
    assert code == 0, out
    assert spy.calls == 1
    card_id = SlotLedger(harness.db).latest_card_id(slot)
    assert card_id is not None
    card = CardLedger(db_path=harness.db).load(card_id)
    assert card is not None
    assert card.since_line == "First card, last 24h: 2 pushes + PRs."


def _outcome(ledger: SlotLedger, slot: datetime, step: str) -> str | None:
    for row in ledger.rows_for_slot(slot):
        if row.step == step:
            return row.outcome
    return None


# -- slice 3b: timer-run deadline rules (fake clock, made-up data) --
#
# The timer starts every run at slot minus 25; a fake sleep advances the
# clock through the wait. A hung facts child burns the clock to the
# deadline it was given. A hung Wonder is the real DeadlineWonderClient
# over a real MuseExecClient whose runner burns its whole timeout_s on
# the fake clock and comes back timed out. The fake Telegram stamps the
# clock at each send, so "send at the slot" is an equality.


class _StampTelegram(_Telegram):
    """A fake transport that stamps the fake clock at each send."""

    def __init__(self, clock: _Clock) -> None:
        super().__init__()
        self.clock = clock
        self.at: list[datetime] = []

    def send_photo(self, *args: Any, **kwargs: Any) -> Any:
        self.at.append(self.clock.now)
        return super().send_photo(*args, **kwargs)


class _HungFacts:
    """A hung facts child: runs the fake clock to its deadline, gives up."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> FactsChildResult:
        self.calls.append(dict(kwargs))
        self.clock.now = kwargs["deadline"]
        return FactsChildResult("FACTS_DEADLINE", None, None)


class _HangRunner:
    """Burns its whole timeout_s on the fake clock, then reports a kill."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.timeouts: list[float] = []

    def __call__(
        self,
        argv: Any,
        *,
        env: Any,
        timeout_s: float,
        cwd: Any,
    ) -> Any:
        from framework.proposal.muse_client import RunResult

        self.timeouts.append(timeout_s)
        self.clock.now = self.clock.now + timedelta(seconds=timeout_s)
        return RunResult(None, b"", True)


def _timer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slot: datetime,
    *,
    facts: Any | None = None,
    runner: Any | None = None,
    bin_name: str,
) -> Any:
    """A timer run at slot minus 25 with an advancing fake clock."""
    from framework.proposal.muse_client import MuseExecClient

    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "framework.proposal.muse_client.rules_file_path",
        lambda *args, **kwargs: str(tmp_path / "no-rules-here"),
    )
    clock = _Clock(slot - timedelta(minutes=25))
    facts_seam = facts if facts is not None else _HungFacts(clock)
    if runner is None:
        runner = _HangRunner(clock)
    deadlines: list[datetime] = []
    telegram = _StampTelegram(clock)

    def _factory(terms: Any, deadline: datetime) -> Any:
        deadlines.append(deadline)

        def _make(timeout_s: float) -> Any:
            return MuseExecClient(
                private_terms=terms.terms,
                private_terms_available=terms.available,
                muse_bin=f"fake-muse-{bin_name}",
                timeout_s=timeout_s,
                runner=runner,
            )

        return DeadlineWonderClient(make_client=_make, deadline=deadline, clock=clock)

    def _sleep(seconds: float) -> None:
        clock.now = clock.now + timedelta(seconds=seconds)

    seams = Seams(
        facts=facts_seam,
        wonder=_factory,
        telegram=telegram,
        clock=clock,
        sleep=_sleep,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    return SimpleNamespace(
        db=tmp_path / "cycle.db",
        clock=clock,
        facts=facts_seam,
        runner=runner,
        deadlines=deadlines,
        telegram=telegram,
        seams=seams,
    )


def _run_timer(
    slot: datetime, run: Any, capsys: pytest.CaptureFixture[str], **kwargs: Any
) -> tuple[int, str, str]:
    params: dict[str, Any] = {
        "slot": slot,
        "subject_id": SUBJECT,
        "db_path": run.db,
        "no_wait": False,
        "seams": run.seams,
    }
    params.update(kwargs)
    code = run_slot(**params)  # type: ignore[arg-type]
    out = capsys.readouterr()
    return code, out.out, out.err


def _seed_timer_events(db: Path, as_of: datetime) -> None:
    _seed_calendar_cursor(db, as_of)
    store = EventStore(db_path=db)
    try:
        assert (
            store.append_events(
                [
                    _full_run_event(
                        "evt-timer-push-a",
                        "github.push",
                        as_of - timedelta(hours=3),
                        {"repo": "synthetic/quiet", "counts": {"commits": 2}},
                    ),
                    _full_run_event(
                        "evt-timer-pr-a",
                        "github.pr",
                        as_of - timedelta(hours=4),
                        {"repo": "synthetic/quiet", "counts": {"opened": 1}},
                    ),
                    _full_run_event(
                        "evt-timer-screen-a",
                        "screen.hour",
                        as_of - timedelta(hours=1),
                        {"device": "mac", "minutes_by_category": {"code": 60.0}},
                        tier="private",
                    ),
                ]
            )
            == 3
        )
    finally:
        store.close()


def _pre_record_code_cycle(db: Path, as_of: datetime) -> str:
    """Record one code-only cycle now; the facts seam can then report it."""
    from framework.cycle import run_cycle as _run_cycle

    store = EventStore(db_path=db)
    try:
        fact_store = FactStore(db_path=store.db_path)
        try:

            class _Stub:
                def complete(self, prompt: str) -> Any:
                    raise AssertionError("no model")

            result, _ = _run_cycle(
                as_of,
                SUBJECT,
                store,
                fact_store,
                _Stub(),  # type: ignore[arg-type]
                personal_pass=False,
                feed_pass=False,
            )
            return result.cycle_id
        finally:
            fact_store.close()
    finally:
        store.close()


def test_hung_local_model_gives_code_cycle_card_at_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hung facts child ends at slot minus four; the card names code facts."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="hung-local")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert len(run.facts.calls) == 1
    assert run.facts.calls[0]["deadline"] == slot - timedelta(minutes=4)
    rows = SlotLedger(run.db).rows_for_slot(slot)
    code_rows = [row for row in rows if row.step == "facts_code"]
    assert [row.outcome for row in code_rows] == ["ok"]
    code_id = _detail_for(code_rows, "cycle")
    assert code_id
    assert spy.cycles == {"builder": code_id, "disconnect": code_id}
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_hung_wonder_gives_labelled_fallbacks_at_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hung Wonder falls back on both sides; the send still lands at the slot."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="hung-wonder")
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    facts_calls: list[dict[str, Any]] = []

    def _fine_facts(**kwargs: Any) -> FactsChildResult:
        facts_calls.append(dict(kwargs))
        return FactsChildResult("ok", code_id, 1)

    run.seams = dataclasses.replace(run.seams, facts=_fine_facts)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert len(facts_calls) == 1
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"fallback"}
    rows = SlotLedger(run.db).rows_for_slot(slot)
    propose_rows = [row for row in rows if row.step.startswith("propose_")]
    assert len(propose_rows) == 2
    for row in propose_rows:
        assert "FALLBACK_MODEL_UNAVAILABLE" in row.detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1
    check = _check(slot, run.db, _check_harness(tmp_path, slot), capsys)
    assert check[0] == 5
    assert "code=DEGRADED detail=FALLBACK_SIDE" in check[1]
    check = _check(slot, run.db, _check_harness(tmp_path, slot), capsys)
    assert check[0] == 5
    assert "code=DEGRADED detail=WONDER_TRANSPORT" in check[1]
    check = _check(slot, run.db, _check_harness(tmp_path, slot), capsys)
    assert check[0] == 0
    assert "code=DEGRADED_REPEAT" in check[1]


def test_both_hung_one_goal_slot_sends_at_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both models hung on a one-goal slot: one fallback, one send at the slot."""
    from framework.cycle.slot_ledger import SlotLedger as _Ledger

    slot = slot_at("13:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="both-hung-one")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    card_times: list[datetime] = []
    real_save = _Ledger.save_card_step

    def _timed_save(self: Any, *args: Any, **kwargs: Any) -> Any:
        card_times.append(run.clock.now)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(_Ledger, "save_card_step", _timed_save)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert [side.profile_id for side in sides] == ["builder"]
    assert {side.kind for side in sides} == {"fallback"}
    assert card_times != [] and all(mark < slot for mark in card_times)
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_both_hung_two_goal_slot_sends_at_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both models hung on a two-goal slot: labelled fallbacks, one send."""
    from framework.cycle.slot_ledger import SlotLedger as _Ledger

    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="both-hung-two")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    card_times: list[datetime] = []
    real_save = _Ledger.save_card_step

    def _timed_save(self: Any, *args: Any, **kwargs: Any) -> Any:
        card_times.append(run.clock.now)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(_Ledger, "save_card_step", _timed_save)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"fallback"}
    rows = SlotLedger(run.db).rows_for_slot(slot)
    propose_rows = [row for row in rows if row.step.startswith("propose_")]
    assert len(propose_rows) == 2
    for row in propose_rows:
        assert "FALLBACK_MODEL_UNAVAILABLE" in row.detail
    assert card_times != [] and all(mark < slot for mark in card_times)
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


class _FlakyRunner:
    """First exec call drafts too long; every later call hangs."""

    def __init__(self, clock: _Clock, bin_name: str) -> None:
        self.clock = clock
        self.bin = bin_name
        self.exec_calls = 0

    def __call__(
        self,
        argv: Any,
        *,
        env: Any,
        timeout_s: float,
        cwd: Any,
    ) -> Any:
        import json as _json

        from framework.proposal.muse_client import RunResult

        if list(argv) == [self.bin, "--version"]:
            self.clock.now = self.clock.now + timedelta(seconds=timeout_s)
            return RunResult(0, b"fake version 9\n", False)
        self.exec_calls += 1
        if self.exec_calls > 1:
            self.clock.now = self.clock.now + timedelta(seconds=timeout_s)
            return RunResult(None, b"", True)
        with open(os.path.join(os.path.dirname(cwd), "schema.json"), "rb") as handle:
            schema = _json.loads(handle.read())
        properties = schema["properties"]
        cids = properties["commitment_id"]["enum"]
        claim_schema = properties["overall_state"]["items"]["properties"]
        fact_ids = claim_schema["fact_ids"]["items"]["enum"]
        payload = {
            "commitment_id": cids[0],
            "overall_state": [
                {
                    "text": " ".join(["word"] * 60),
                    "fact_ids": [fact_ids[0]],
                    "metric_refs": [],
                }
            ],
            "working": [],
            "not_working": [],
        }
        terminal = _json.dumps(
            {
                "payload": {
                    "kind": "run_terminal",
                    "terminal": "completed",
                    "text": _json.dumps(payload),
                }
            }
        )
        usage = _json.dumps({"payload": {"kind": "run_usage", "models": []}})
        return RunResult(0, (terminal + "\n" + usage + "\n").encode(), False)


def _live_factory(run: Any, runner: Any, terms: Any, deadline: datetime) -> Any:
    from framework.proposal.muse_client import MuseExecClient

    def _make(timeout_s: float) -> Any:
        return MuseExecClient(
            private_terms=terms.terms,
            private_terms_available=terms.available,
            muse_bin=runner.bin,
            timeout_s=timeout_s,
            runner=runner,
        )

    return DeadlineWonderClient(make_client=_make, deadline=deadline, clock=run.clock)


def test_bad_draft_then_hung_retry_still_sends_at_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A gate-failing draft retries into a hang; the second goal still fits."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="bad-draft")
    flaky = _FlakyRunner(run.clock, "fake-muse-bad-draft")
    run.seams = dataclasses.replace(
        run.seams,
        wonder=lambda terms, deadline: _live_factory(run, flaky, terms, deadline),
    )
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert flaky.exec_calls == 3
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"fallback"}
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_late_model_result_keeps_code_cycle_and_resends_stored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A model cycle landing after the give-up still loses; the re-run resends."""
    from framework.cycle import run_cycle as _run_cycle
    from framework.cycle.slot_ledger import SlotLedger as _Ledger

    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="late-model")
    as_of = slot - timedelta(minutes=25)
    seeds = [
        _full_run_event(
            "evt-full-push-a",
            "github.push",
            as_of - timedelta(hours=3),
            {"repo": "synthetic/quiet", "counts": {"commits": 2}},
        ),
        _full_run_event(
            "evt-full-push-b",
            "github.push",
            as_of - timedelta(hours=2),
            {"repo": "synthetic/quiet", "counts": {"commits": 1}},
        ),
        _full_run_event(
            "evt-full-screen-a",
            "screen.hour",
            as_of - timedelta(hours=1),
            {"device": "mac", "minutes_by_category": {"code": 60.0}},
            tier="private",
        ),
    ]
    store = EventStore(db_path=run.db)
    try:
        assert store.append_events(seeds) == len(seeds)
    finally:
        store.close()
    model_ids: list[str] = []
    facts_calls: list[dict[str, Any]] = []

    def _late_facts(**kwargs: Any) -> FactsChildResult:
        facts_calls.append(dict(kwargs))
        run.clock.now = kwargs["deadline"]
        inner = EventStore(db_path=Path(kwargs["db_path"]))
        try:
            fact_store = FactStore(db_path=inner.db_path)
            try:
                made, _ = _run_cycle(
                    kwargs["as_of"],
                    SUBJECT,
                    inner,
                    fact_store,
                    _model_stub_for(kwargs["as_of"], tuple(seeds)),
                    feed_pass=False,
                )
                model_ids.append(made.cycle_id)
            finally:
                fact_store.close()
        finally:
            inner.close()
        return FactsChildResult("FACTS_DEADLINE", None, None)

    run.seams = dataclasses.replace(run.seams, facts=_late_facts)
    spy = _patch_propose(monkeypatch, _ProposeSpy())
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    real_save = _Ledger.save_card_step

    def _save_and_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        out = real_save(self, *args, **kwargs)
        kill.write_text("stop\n")
        return out

    monkeypatch.setattr(_Ledger, "save_card_step", _save_and_stop)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert "code=killed" in out
    assert model_ids != []
    rows = SlotLedger(run.db).rows_for_slot(slot)
    code_id = _detail_for([row for row in rows if row.step == "facts_code"], "cycle")
    assert code_id and code_id != model_ids[0]
    assert spy.cycles == {"builder": code_id, "disconnect": code_id}
    assert run.telegram.calls == []

    monkeypatch.delenv("IKIGAI_KILL_FILE")

    def _boom_facts(**kwargs: Any) -> FactsChildResult:
        raise AssertionError("no second facts child on resume")

    run.seams = dataclasses.replace(run.seams, facts=_boom_facts)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert len(facts_calls) == 1
    assert spy.calls == 2
    assert len(run.telegram.calls) == 1
    assert run.telegram.at == [slot]


def test_restart_after_stored_card_waits_and_sends_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A crash after the card step resumes at the send; one send in total."""
    from framework.cycle.slot_ledger import SlotLedger as _Ledger

    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="restart-card")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    kill = tmp_path / "stop"
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    real_save = _Ledger.save_card_step

    def _save_and_stop(self: Any, *args: Any, **kwargs: Any) -> Any:
        out = real_save(self, *args, **kwargs)
        kill.write_text("stop\n")
        return out

    monkeypatch.setattr(_Ledger, "save_card_step", _save_and_stop)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert "code=killed" in out
    assert run.telegram.calls == []

    monkeypatch.delenv("IKIGAI_KILL_FILE")
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert len(run.facts.calls) == 1
    assert len(run.telegram.calls) == 1
    assert run.telegram.at == [slot]


def test_restart_after_facts_row_starts_no_second_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A crash in propose leaves the facts row done; the re-run proposes once."""
    from framework.cycle import propose as _real_propose

    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="restart-facts")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    state = {"crashed": False}

    def _once(**kwargs: Any) -> Any:
        if not state["crashed"]:
            state["crashed"] = True
            raise KeyboardInterrupt("boom")
        return _real_propose(**kwargs)

    monkeypatch.setattr("framework.cycle.propose", _once)
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=run.db,
            no_wait=False,
            seams=run.seams,
        )
    capsys.readouterr()
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert len(run.facts.calls) == 1
    assert len(run.telegram.calls) == 1
    assert run.telegram.at == [slot]


def test_restart_after_open_intent_records_unknown_and_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A crash mid-send leaves an open intent; the re-run explains, not sends."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="restart-intent")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    run.telegram.fail_first = KeyboardInterrupt("boom")
    with pytest.raises(KeyboardInterrupt, match="boom"):
        run_slot(
            slot=slot,
            subject_id=SUBJECT,
            db_path=run.db,
            no_wait=False,
            seams=run.seams,
        )
    capsys.readouterr()
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 1
    assert "code=DELIVERY_UNKNOWN" in out
    assert len(run.telegram.calls) == 1
    assert run.telegram.at == [slot]


def test_no_cycle_forced_outside_hours_sends_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No facts at a forced out-of-hours slot is a window noop, never a send."""
    import sqlite3

    from framework.cycle import orchestrator

    slot = datetime(2026, 11, 2, 11, 0, tzinfo=MADRID)
    run = _timer(tmp_path, monkeypatch, slot, bin_name="no-cycle-window")

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise sqlite3.OperationalError("synthetic locked")

    monkeypatch.setattr(orchestrator, "run_cycle", _boom)

    def _boom_propose(**kwargs: Any) -> Any:
        raise AssertionError("no cycle means no propose")

    monkeypatch.setattr("framework.cycle.propose", _boom_propose)
    code, out, _ = _run_timer(slot, run, capsys, force_slot=True)
    assert code == 0, out
    assert "code=NOOP_FALLBACK_WINDOW" in out
    assert run.telegram.calls == []
    rows = SlotLedger(run.db).rows_for_slot(slot)
    assert "NOOP_FALLBACK_WINDOW" in [row.outcome for row in rows if row.step == "card"]


def test_late_hand_run_skips_child_but_wonder_gets_its_try(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hand run started after slot minus four skips the child, tries Wonder."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="late-hand")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    run.clock.now = slot - timedelta(minutes=2)
    facts_calls: list[dict[str, Any]] = []

    def _boom_facts(**kwargs: Any) -> FactsChildResult:
        facts_calls.append(dict(kwargs))
        raise AssertionError("the child must be skipped this late")

    deadlines: list[datetime] = []
    wonder = _FullRunWonder()

    def _late_factory(terms: Any, deadline: datetime) -> Any:
        deadlines.append(deadline)
        return DeadlineWonderClient(
            make_client=lambda timeout_s: wonder,  # type: ignore[arg-type]
            deadline=deadline,
            clock=run.clock,
        )

    run.seams = dataclasses.replace(run.seams, facts=_boom_facts, wonder=_late_factory)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert facts_calls == []
    rows = SlotLedger(run.db).rows_for_slot(slot)
    assert "FACTS_DEADLINE" in [
        row.outcome for row in rows if row.step == "facts_model"
    ]
    assert deadlines == [slot + timedelta(seconds=30)]
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"proposal"}
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


# -- local start retries (fake clock, fake runners, made-up data) --
#
# A burst of fast local failures is retried inside the propose deadline:
# each profile wraps the one seams client in a fresh retrying client, so
# each failure belongs to its profile. The propose row carries
# local_retries=<n> only above zero; masked stderr lives only in the new
# table, never in stdout or slot_ledger.detail.


def _draft_stdout_for(schema: dict[str, Any]) -> bytes:
    """A gate-passing draft for one request schema, as raw stdout bytes."""
    import json as _json

    properties = schema["properties"]
    cids = properties["commitment_id"]["enum"]
    claim_schema = properties["overall_state"]["items"]["properties"]
    fact_ids = claim_schema.get("fact_ids", {}).get("items", {}).get("enum", [])
    metric_ids = claim_schema.get("metric_refs", {}).get("items", {}).get("enum", [])
    assert fact_ids, "the gate needs a fact to cite"
    assert "period.last.pushes" in metric_ids
    model_fact = fact_ids[-1]
    payload: dict[str, Any] = {
        "commitment_id": cids[0],
        "overall_state": [
            {
                "text": "The recorded push activity stands as noted",
                "fact_ids": [fact_ids[0]],
                "metric_refs": [],
            }
        ],
        "working": [
            {
                "text": "The recorded session stands as noted",
                "fact_ids": [model_fact],
                "metric_refs": [],
            }
        ],
        "not_working": [],
    }
    if "since_last" in properties:
        payload["since_last"] = [
            {
                "text": "Pushes rose 1 in last",
                "fact_ids": [],
                "metric_refs": ["period.last.pushes"],
            }
        ]

    def _line(entry: dict[str, Any]) -> str:
        return _json.dumps(
            {
                "schema_version": 1,
                "stream": {"kind": "session", "id": "s"},
                "record_type": "event",
                "payload": entry,
            }
        )

    terminal = {
        "kind": "run_terminal",
        "terminal": "completed",
        "text": _json.dumps(payload),
        "reason": None,
    }
    return (_line(terminal) + "\n").encode()


class _BurstRunner:
    """A fake runner: fast exits on the burst calls, drafts after."""

    def __init__(self, fail_calls: set[int], stderr: bytes) -> None:
        self._fail = set(fail_calls)
        self._stderr = stderr
        self.calls = 0
        self.runs = 0

    def __call__(
        self, argv: Any, *, env: Any, timeout_s: float, cwd: str | None
    ) -> Any:
        import json as _json

        from framework.proposal.muse_client import RunResult

        self.calls += 1
        args = [str(item) for item in argv]
        if len(args) > 1 and args[1] == "--version":
            return RunResult(0, b"fake-muse-burst 0.0\n", False)
        self.runs += 1
        if self.runs in self._fail:
            return RunResult(1, b"burst\n", False, self._stderr)
        schema_path = args[args.index("--output-schema") + 1]
        schema = _json.loads(Path(schema_path).read_bytes())
        return RunResult(0, _draft_stdout_for(schema), False)


class _AlwaysBurstRunner:
    """A fake runner that never clears: every call is a fast exit 1."""

    def __init__(self, stderr: bytes) -> None:
        self._stderr = stderr
        self.calls = 0

    def __call__(
        self, argv: Any, *, env: Any, timeout_s: float, cwd: str | None
    ) -> Any:
        from framework.proposal.muse_client import RunResult

        self.calls += 1
        args = [str(item) for item in argv]
        if len(args) > 1 and args[1] == "--version":
            return RunResult(0, b"fake-muse-burst 0.0\n", False)
        return RunResult(1, b"burst\n", False, self._stderr)


def _burst_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, slot: datetime, runner: Any
) -> _Harness:
    from framework.briefing.context import load_private_terms
    from framework.proposal.muse_client import MuseExecClient

    _env(monkeypatch, tmp_path)
    harness = _harness(tmp_path, slot)
    _seed_timer_events(harness.db, slot - timedelta(minutes=25))
    terms = load_private_terms()
    client = MuseExecClient(
        private_terms=terms.terms,
        private_terms_available=terms.available,
        muse_bin="fake-muse-burst",
        timeout_s=120,
        runner=runner,
    )
    harness = dataclasses.replace(
        harness,
        seams=dataclasses.replace(harness.seams, wonder=lambda terms, deadline: client),
    )
    return harness


def test_burst_clears_delivers_two_proposal_sides_with_retry_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    slot = slot_at("15:30")
    runner = _BurstRunner({1, 2, 4, 5}, stderr=b"launcher hiccup, retry soon\n")
    harness = _burst_harness(tmp_path, monkeypatch, slot, runner)
    code, out, err = _run(slot, harness, capsys)
    assert code == 0, out
    ledger = SlotLedger(harness.db)
    sides = ledger.slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"proposal"}
    details = {row.step: row.detail for row in ledger.rows_for_slot(slot)}
    assert (
        details["propose_builder"] and "local_retries=2" in details["propose_builder"]
    )
    assert "local_retries=2" in details["propose_disconnect"]
    retries = ledger.local_retries_for_slot(slot)
    assert [(row.profile, row.attempt) for row in retries] == [
        ("builder", 1),
        ("builder", 2),
        ("disconnect", 1),
        ("disconnect", 2),
    ]
    assert {row.reason for row in retries} == {"exit 1"}
    assert {row.exit_code for row in retries} == {1}
    assert all(row.latency_ms < 2000 for row in retries)
    assert all("hiccup" in row.stderr_masked for row in retries)
    assert harness.sleeps == [5.0, 20.0, 5.0, 20.0]
    assert harness.telegram.calls != []
    assert "hiccup" not in out
    assert "hiccup" not in err
    assert all("hiccup" not in row.detail for row in ledger.rows_for_slot(slot))


def test_burst_that_never_clears_gives_two_labelled_fallbacks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    token = "tok_" + "Ab3-" * 8
    email = "fellow@example.invalid"
    stderr = (f"burst canary {email} {token} launcher hiccup\n").encode()
    slot = slot_at("15:30")
    harness = _burst_harness(tmp_path, monkeypatch, slot, _AlwaysBurstRunner(stderr))
    code, out, err = _run(slot, harness, capsys)
    assert code == 0, out
    ledger = SlotLedger(harness.db)
    sides = ledger.slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"fallback"}
    rows = {row.step: row for row in ledger.rows_for_slot(slot)}
    for step in ("propose_builder", "propose_disconnect"):
        assert "local_retries=3" in rows[step].detail
        assert "FALLBACK_MODEL_UNAVAILABLE" in rows[step].detail
        assert "wonder_down=1" in rows[step].detail
    retries = ledger.local_retries_for_slot(slot)
    assert len(retries) == 6
    assert [(row.profile, row.attempt) for row in retries] == [
        ("builder", 1),
        ("builder", 2),
        ("builder", 3),
        ("disconnect", 1),
        ("disconnect", 2),
        ("disconnect", 3),
    ]
    for row in retries:
        assert row.reason == "exit 1"
        assert row.exit_code == 1
        assert row.latency_ms < 2000
        assert "hiccup" in row.stderr_masked
        assert token not in row.stderr_masked
        assert email not in row.stderr_masked
    assert harness.sleeps == [5.0, 20.0, 5.0, 20.0]
    assert harness.telegram.calls != []
    for blob in (out, err):
        assert token not in blob
        assert email not in blob
        assert "hiccup" not in blob
    for row in ledger.rows_for_slot(slot):
        assert token not in row.detail
        assert email not in row.detail
        assert "hiccup" not in row.detail


# -- calendar staleness (fake clock, proposal sides, made-up data) --
#
# The card never changes with the collector's health: a stale calendar only
# marks the `hour` row and alerts once per Madrid day through the watchdog.


def _hour_rows(db: Path, slot: datetime) -> list[Any]:
    return [row for row in SlotLedger(db).rows_for_slot(slot) if row.step == "hour"]


def _hour_mark(db: Path, slot: datetime, key: str) -> str:
    raw = _detail_for(_hour_rows(db, slot), key)
    assert raw is not None
    return raw


def _proposal_run(
    slot: datetime,
    harness: _Harness,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str, str]:
    return _run(slot, harness, capsys, skip_local_model=True)


def test_stale_calendar_marks_hour_and_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cursor 10 hours old leaves the hour in place and alerts stale."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(harness.db, as_of - timedelta(hours=10))
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    hour_rows = _hour_rows(harness.db, slot)
    assert len(hour_rows) == 1
    assert _detail_for(hour_rows, "calendar_stale") == "1"
    assert datetime.fromisoformat(_hour_mark(harness.db, slot, "start")) == slot
    assert datetime.fromisoformat(
        _hour_mark(harness.db, slot, "end")
    ) == slot + timedelta(hours=1)
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out
    code, out, _ = _run(slot, harness, capsys, skip_local_model=True)
    assert code == 0
    assert "code=ALREADY_DONE" in out
    assert len(_hour_rows(harness.db, slot)) == 1


def test_missing_calendar_cursor_reads_as_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No calendar cursor at all is stale, with the same hour and alert."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    conn = sqlite3.connect(harness.db)
    try:
        conn.execute("DELETE FROM cursors")
        conn.commit()
    finally:
        conn.close()
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    hour_rows = _hour_rows(harness.db, slot)
    assert len(hour_rows) == 1
    assert _detail_for(hour_rows, "calendar_stale") == "1"
    assert datetime.fromisoformat(_hour_mark(harness.db, slot, "start")) == slot
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out


def test_stale_calendar_hour_still_walks_past_busy_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A block stored after the last good poll still moves the stale hour."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(harness.db, as_of - timedelta(hours=10))
    _seed_busy_block(harness.db, slot, as_of)
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    hour_rows = _hour_rows(harness.db, slot)
    assert len(hour_rows) == 1
    assert _detail_for(hour_rows, "calendar_stale") == "1"
    assert datetime.fromisoformat(
        _hour_mark(harness.db, slot, "start")
    ) == slot + timedelta(hours=1)
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out


def test_fresh_calendar_leaves_hour_clean_and_delivers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A cursor 5 minutes old marks nothing and the watchdog says delivered."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(harness.db, as_of - timedelta(minutes=5))
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    hour_rows = _hour_rows(harness.db, slot)
    assert len(hour_rows) == 1
    assert _detail_for(hour_rows, "calendar_stale") is None
    assert datetime.fromisoformat(_hour_mark(harness.db, slot, "start")) == slot
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 0
    assert "code=DELIVERED" in check_out


def test_calendar_boundary_one_hour_is_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Exactly one hour old is fresh; one second more is stale."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    fresh = _harness(tmp_path / "fresh", slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(fresh.db, as_of - timedelta(hours=1))
    code, out, _ = _proposal_run(slot, fresh, capsys)
    assert code == 0, out
    assert _detail_for(_hour_rows(fresh.db, slot), "calendar_stale") is None
    check_code, check_out = _check(
        slot, fresh.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 0
    assert "code=DELIVERED" in check_out
    stale = _harness(tmp_path / "stale", slot)
    _seed_calendar_cursor(stale.db, as_of - timedelta(hours=1, seconds=1))
    code, out, _ = _proposal_run(slot, stale, capsys)
    assert code == 0, out
    assert _detail_for(_hour_rows(stale.db, slot), "calendar_stale") == "1"
    check_code, check_out = _check(
        slot, stale.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out


def test_two_calendars_with_one_old_cursor_are_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two calendars count the oldest cursor: one old poll is stale."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(harness.db, as_of - timedelta(minutes=5), "calendar-first")
    _seed_calendar_cursor(harness.db, as_of - timedelta(hours=10), "calendar-second")
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1
    assert _detail_for(_hour_rows(harness.db, slot), "calendar_stale") == "1"
    check_code, check_out = _check(
        slot, harness.db, _check_harness(tmp_path, slot), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out


def test_mixed_naive_and_aware_cursors_still_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A naive cursor beside an aware one never stops the slot's card.

    The naive stamp reads as UTC where the ledger reads it, before
    anything compares the stamps, so the mixed sort cannot raise.
    """
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    naive = (as_of - timedelta(minutes=5)).replace(tzinfo=None)
    _seed_calendar_cursor(harness.db, naive, "calendar-naive")
    _seed_calendar_cursor(harness.db, as_of - timedelta(minutes=5), "calendar-aware")
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1


def test_unparseable_cursor_stamp_still_sends(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unparseable cursor stamp is skipped and the card still sends."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    harness = _harness(tmp_path, slot)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(harness.db, as_of - timedelta(minutes=5))
    conn = sqlite3.connect(harness.db)
    try:
        conn.execute(
            "INSERT INTO cursors (name, cursor, updated_at) VALUES (?, ?, ?)",
            ("calendar-broken", "{}", "not-a-stamp"),
        )
        conn.commit()
    finally:
        conn.close()
    code, out, _ = _proposal_run(slot, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 1


def test_second_stale_slot_same_day_repeats_quietly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A second stale slot on the same Madrid day reports DEGRADED_REPEAT."""
    _env(monkeypatch, tmp_path)
    first = slot_at("15:30")
    second = slot_at("18:00")
    harness = _harness(tmp_path, first)
    _patch_propose(monkeypatch, _ProposeSpy())
    _seed_calendar_cursor(
        harness.db, first - timedelta(minutes=25) - timedelta(hours=10)
    )
    code, out, _ = _proposal_run(first, harness, capsys)
    assert code == 0, out
    code, out, _ = _proposal_run(second, harness, capsys)
    assert code == 0, out
    assert len(harness.telegram.calls) == 2
    check_code, check_out = _check(
        first, harness.db, _check_harness(tmp_path, first), capsys
    )
    assert check_code == 5
    assert "code=DEGRADED detail=CALENDAR_STALE" in check_out
    check_code, check_out = _check(
        second, harness.db, _check_harness(tmp_path, second), capsys
    )
    assert check_code == 0
    assert "code=DEGRADED_REPEAT" in check_out


# -- slice 3c: one more attempt for a timed-out Wonder call (fake clock) --
#
# A Wonder call that ends in a timeout gets one more attempt when a full
# call's time still remains before the propose deadline, through
# TimeoutRetryClient, counted as timeout_retries on the propose row. The
# runner below answers --version at once, because that probe costs
# milliseconds in production and must not burn the fake clock.


class _ScriptRunner:
    """A fake runner: scripted exec behaviors, an instant version, no port."""

    def __init__(
        self,
        clock: _Clock,
        bin_name: str,
        script: list[str],
        kill_file: Path | None = None,
    ) -> None:
        self.clock = clock
        self.bin = bin_name
        self._script = list(script)
        self._kill_file = kill_file
        self.exec_calls = 0
        self.calls: list[tuple[str, float, datetime]] = []

    def __call__(self, argv: Any, *, env: Any, timeout_s: float, cwd: Any) -> Any:
        import json as _json

        from framework.proposal.muse_client import RunResult

        args = [str(item) for item in argv]
        if len(args) > 1 and args[1] == "--version":
            self.calls.append(("version", timeout_s, self.clock.now))
            return RunResult(0, b"fake-muse-timeout 0.0\n", False)
        self.exec_calls += 1
        before = self.clock.now
        self.calls.append(("exec", timeout_s, before))
        if self._kill_file is not None and self.exec_calls == 1:
            self._kill_file.write_text("stop\n")
        behavior = self._script.pop(0) if self._script else "hang"
        if behavior == "hang":
            self.clock.now = before + timedelta(seconds=timeout_s)
            return RunResult(None, b"", True)
        if behavior == "burst":
            return RunResult(1, b"burst\n", False, b"launcher hiccup, retry soon\n")
        with open(os.path.join(os.path.dirname(cwd), "schema.json"), "rb") as handle:
            schema = _json.loads(handle.read())
        if behavior == "bad":
            properties = schema["properties"]
            cids = properties["commitment_id"]["enum"]
            claim_schema = properties["overall_state"]["items"]["properties"]
            fact_ids = claim_schema["fact_ids"]["items"]["enum"]
            payload: dict[str, Any] = {
                "commitment_id": cids[0],
                "overall_state": [
                    {
                        "text": " ".join(["word"] * 60),
                        "fact_ids": [fact_ids[0]],
                        "metric_refs": [],
                    }
                ],
                "working": [],
                "not_working": [],
            }
            terminal = _json.dumps(
                {
                    "payload": {
                        "kind": "run_terminal",
                        "terminal": "completed",
                        "text": _json.dumps(payload),
                    }
                }
            )
            usage = _json.dumps({"payload": {"kind": "run_usage", "models": []}})
            return RunResult(0, (terminal + "\n" + usage + "\n").encode(), False)
        if behavior == "good":
            return RunResult(0, _draft_stdout_for(schema), False)
        raise AssertionError(f"unknown behavior {behavior}")


def _script_timer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slot: datetime,
    script: list[str],
    *,
    bin_name: str,
    start_minutes: int = 25,
    kill_file: Path | None = None,
) -> Any:
    """A timer run like _timer but with a scripted runner and an offset start."""
    from framework.proposal.muse_client import MuseExecClient

    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "framework.proposal.muse_client.rules_file_path",
        lambda *args, **kwargs: str(tmp_path / "no-rules-here"),
    )
    clock = _Clock(slot - timedelta(minutes=start_minutes))
    runner = _ScriptRunner(clock, f"fake-muse-{bin_name}", script, kill_file=kill_file)
    deadlines: list[datetime] = []
    telegram = _StampTelegram(clock)

    def _factory(terms: Any, deadline: datetime) -> Any:
        deadlines.append(deadline)

        def _make(timeout_s: float) -> Any:
            return MuseExecClient(
                private_terms=terms.terms,
                private_terms_available=terms.available,
                muse_bin=runner.bin,
                timeout_s=timeout_s,
                runner=runner,
            )

        return DeadlineWonderClient(make_client=_make, deadline=deadline, clock=clock)

    def _sleep(seconds: float) -> None:
        clock.now = clock.now + timedelta(seconds=seconds)

    seams = Seams(
        facts=_HungFacts(clock),
        wonder=_factory,
        telegram=telegram,
        clock=clock,
        sleep=_sleep,
        home=tmp_path / "home",
        ledger_sleep=lambda s: None,
    )
    return SimpleNamespace(
        db=tmp_path / "cycle.db",
        clock=clock,
        facts=seams.facts,
        runner=runner,
        deadlines=deadlines,
        telegram=telegram,
        seams=seams,
    )


def _ok_facts(code_id: str) -> Any:
    """A facts seam that reports the pre-recorded cycle at once."""

    def _fine(**kwargs: Any) -> FactsChildResult:
        return FactsChildResult("ok", code_id, 1)

    return _fine


def _facts_at(clock: _Clock, mark: datetime, code_id: str) -> Any:
    """A facts seam ending at one mark: the clock jumps there, then ok."""

    def _go(**kwargs: Any) -> FactsChildResult:
        clock.now = mark
        return FactsChildResult("ok", code_id, 1)

    return _go


def _stored_attempts(db: Path, profile: str) -> int:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT a.proposal_key FROM proposal_attempts a"
            " JOIN proposal_results r ON a.proposal_key = r.proposal_key"
            " WHERE r.subject_id = ? AND r.profile_id = ?",
            (SUBJECT, profile),
        ).fetchall()
        return len(rows)
    finally:
        conn.close()


def _propose_rows(db: Path, slot: datetime) -> list[Any]:
    return [
        row
        for row in SlotLedger(db).rows_for_slot(slot)
        if row.step.startswith("propose_")
    ]


def test_timeout_then_answer_is_a_proposal_with_one_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Builder's first call times out and the retry answers: a proposal side."""
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["hang", "good", "good"],
        bin_name="t13b-retry-once",
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"proposal"}
    assert len(run.telegram.calls) == 1
    assert run.telegram.at == [slot]
    assert run.runner.exec_calls == 3
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert rows["propose_builder"].outcome == "proposal"
    assert "timeout_retries=1" in rows["propose_builder"].detail
    assert "timeout_retries" not in rows["propose_disconnect"].detail
    assert "local_retries" not in rows["propose_builder"].detail
    assert "local_retries" not in rows["propose_disconnect"].detail
    assert SlotLedger(run.db).local_retries_for_slot(slot) == ()
    assert _stored_attempts(run.db, "builder") == 1


def test_second_attempt_proposal_reads_delivered_with_no_alert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A side that got its proposal on the second attempt is a normal side."""
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["hang", "good", "good"],
        bin_name="t13b-retry-calm",
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    check_code, check_out = _check(slot, run.db, _check_harness(tmp_path, slot), capsys)
    assert check_code == 0, check_out
    assert "code=DELIVERED" in check_out


def test_every_call_hanging_with_time_to_spare_retries_both_sides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Hung Wonders with minutes to spare: two calls per side, labelled fallbacks."""
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path, monkeypatch, slot, ["hang"], bin_name="t13b-retry-both"
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert len(sides) == 2
    assert {side.kind for side in sides} == {"fallback"}
    assert run.runner.exec_calls == 4
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert len(rows) == 2
    for row in rows.values():
        assert row.outcome == "fallback"
        assert "FALLBACK_MODEL_UNAVAILABLE" in row.detail
        assert "timeout_retries=1" in row.detail
        assert "wonder_down=1" in row.detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_both_hung_one_goal_makes_no_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both models hung on a one-goal slot: the stalled call is not retried."""
    slot = slot_at("13:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="t13b-hung-one")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert run.runner.timeouts == [120.0, 10.0]
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert len(rows) == 1
    assert "timeout_retries" not in rows["propose_builder"].detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_both_hung_two_goal_makes_no_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both models hung on a two-goal slot: each side stalls once, then falls back."""
    slot = slot_at("15:30")
    run = _timer(tmp_path, monkeypatch, slot, bin_name="t13b-hung-two")
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert run.runner.timeouts == [120.0, 10.0, 80.0]
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert len(rows) == 2
    for row in rows.values():
        assert "timeout_retries" not in row.detail
        assert "FALLBACK_MODEL_UNAVAILABLE" in row.detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


@pytest.mark.parametrize(
    ("minutes_before", "want_execs"),
    [
        (25, 4),
        (10, 4),
        (6, 3),
        (5, 3),
        (4.5, 2),
        (4, 2),
    ],
    ids=["25min", "10min", "6min", "5min", "4.5min", "4min"],
)
def test_hung_wonder_facts_distance_keeps_send_on_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    minutes_before: float,
    want_execs: int,
) -> None:
    """Every call hanging, facts ending nearer the slot: the send still lands on it."""
    from framework.cycle.slot_ledger import SlotLedger as _Ledger

    slot = slot_at("15:30")
    mark = slot - timedelta(minutes=minutes_before)
    name = f"t13b-hang-{str(minutes_before).replace('.', 'p')}"
    run = _script_timer(tmp_path, monkeypatch, slot, ["hang"], bin_name=name)
    _seed_timer_events(run.db, slot - timedelta(minutes=25))
    code_id = _pre_record_code_cycle(run.db, slot - timedelta(minutes=25))
    run.seams = dataclasses.replace(
        run.seams, facts=_facts_at(run.clock, mark, code_id)
    )
    card_times: list[datetime] = []
    real_save = _Ledger.save_card_step

    def _timed_save(self: Any, *args: Any, **kwargs: Any) -> Any:
        card_times.append(run.clock.now)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(_Ledger, "save_card_step", _timed_save)
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert run.runner.exec_calls == want_execs
    deadline = max(mark + timedelta(seconds=150), slot - timedelta(seconds=30))
    for kind, timeout_s, before in run.runner.calls:
        if kind != "exec":
            continue
        assert timeout_s <= 120.0
        assert timeout_s <= (deadline - before).total_seconds() + 1e-6
    assert card_times != [] and all(
        mark <= slot - timedelta(seconds=30) for mark in card_times
    )
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_hand_run_three_minutes_before_slot_makes_no_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A hand run started three minutes before the slot leaves too little to retry."""
    slot = slot_at("15:30")

    def _past_deadline(**kwargs: Any) -> FactsChildResult:
        return FactsChildResult("FACTS_DEADLINE", None, None)

    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["hang"],
        bin_name="t13b-retry-late",
        start_minutes=3,
    )
    run.seams = dataclasses.replace(run.seams, facts=_past_deadline)
    _seed_timer_events(run.db, slot - timedelta(minutes=3))
    code, out, _ = _run_timer(slot, run, capsys, lead_minutes=3)
    assert code == 0, out
    assert run.runner.exec_calls == 2
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert len(rows) == 2
    for row in rows.values():
        assert "timeout_retries" not in row.detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_bad_draft_then_repair_timeout_still_proposes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad first draft, a repair call that times out, then a good repair."""
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["bad", "hang", "good", "good"],
        bin_name="t13b-retry-repair",
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert {side.kind for side in sides} == {"proposal"}
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert "timeout_retries=1" in rows["propose_builder"].detail
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_kill_during_first_hung_call_makes_no_second_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The kill file appearing during the first hung call: the slot ends killed."""
    slot = slot_at("15:30")
    kill = tmp_path / "stop"
    run = _script_timer(
        tmp_path, monkeypatch, slot, ["hang"], bin_name="t13b-retry-kill"
    )
    monkeypatch.setenv("IKIGAI_KILL_FILE", str(kill))
    run.runner._kill_file = kill
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    assert "code=killed" in out
    assert run.runner.exec_calls == 1
    rows = SlotLedger(run.db).rows_for_slot(slot)
    assert [row.step for row in rows if row.step == "propose_disconnect"] == []
    assert rows[-1].outcome == "killed"


def test_timeout_then_local_start_then_success_counts_each_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A timeout, then a local start failure on the retry, then a success."""
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["hang", "burst", "good", "good"],
        bin_name="t13b-retry-burst",
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert {side.kind for side in sides} == {"proposal"}
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert "timeout_retries=1" in rows["propose_builder"].detail
    assert "local_retries=1" in rows["propose_builder"].detail
    retries = SlotLedger(run.db).local_retries_for_slot(slot)
    assert [(row.profile, row.attempt) for row in retries] == [("builder", 1)]
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_timeout_then_local_start_then_timeout_falls_back_once_each(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A timeout, a local start failure on the retry, then another timeout.

    The local start wrapper sits inside the timeout wrapper, so the
    local failure retries inside the second timeout attempt instead of
    restarting the call for a second extra timeout attempt. Builder
    falls back with one of each count, and Disconnect still proposes.
    """
    slot = slot_at("15:30")
    run = _script_timer(
        tmp_path,
        monkeypatch,
        slot,
        ["hang", "burst", "hang", "good"],
        bin_name="t13b-retry-order",
    )
    as_of = slot - timedelta(minutes=25)
    _seed_timer_events(run.db, as_of)
    code_id = _pre_record_code_cycle(run.db, as_of)
    run.seams = dataclasses.replace(run.seams, facts=_ok_facts(code_id))
    code, out, _ = _run_timer(slot, run, capsys)
    assert code == 0, out
    sides = SlotLedger(run.db).slot_cards_for_slot(slot)
    assert {side.profile_id: side.kind for side in sides} == {
        "builder": "fallback",
        "disconnect": "proposal",
    }
    rows = {row.step: row for row in _propose_rows(run.db, slot)}
    assert rows["propose_builder"].outcome == "fallback"
    assert "timeout_retries=1" in rows["propose_builder"].detail
    assert "local_retries=1" in rows["propose_builder"].detail
    assert rows["propose_disconnect"].outcome == "proposal"
    assert "timeout_retries" not in rows["propose_disconnect"].detail
    assert "local_retries" not in rows["propose_disconnect"].detail
    retries = SlotLedger(run.db).local_retries_for_slot(slot)
    assert [(row.profile, row.attempt) for row in retries] == [("builder", 1)]
    assert run.telegram.at == [slot]
    assert len(run.telegram.calls) == 1


def test_run_proposals_failure_after_retry_keeps_the_count(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """run_proposals raising after a retried timeout: the failure row keeps it."""
    from framework.proposal.core import WonderRequest

    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    harness = _harness(tmp_path, slot, wonder=_DownWonder("timeout"))

    def _raising(**kwargs: Any) -> Any:
        client = kwargs["client"]
        request = WonderRequest(
            prompt="made-up prompt",
            model="muse-wonder-1.0",
            effort="high",
            response_schema={"type": "object"},
        )
        with pytest.raises(MetaUnavailableError):
            client.complete(request)
        raise RuntimeError("boom-after-timeout")

    monkeypatch.setattr("framework.cycle.orchestrator.run_proposals", _raising)
    code, out, _ = _run(slot, harness, capsys)
    assert code == 1, out
    assert "code=RuntimeError" in out
    rows = [row for row in SlotLedger(harness.db).rows_for_slot(slot)]
    failed = [row for row in rows if row.step == "propose_builder"]
    assert len(failed) == 1
    assert failed[0].outcome == "RuntimeError"
    assert "timeout_retries=1" in failed[0].detail


def test_card_bytes_match_stale_or_fresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The alert never touches the card: stale and fresh bytes are equal."""
    _env(monkeypatch, tmp_path)
    slot = slot_at("15:30")
    as_of = slot - timedelta(minutes=25)
    _patch_propose(monkeypatch, _ProposeSpy())
    fresh = _harness(tmp_path / "fresh", slot)
    _seed_calendar_cursor(fresh.db, as_of - timedelta(minutes=5))
    code, out, _ = _proposal_run(slot, fresh, capsys)
    assert code == 0, out
    stale = _harness(tmp_path / "stale", slot)
    _seed_calendar_cursor(stale.db, as_of - timedelta(hours=10))
    code, out, _ = _proposal_run(slot, stale, capsys)
    assert code == 0, out
    fresh_ledger = SlotLedger(fresh.db)
    stale_ledger = SlotLedger(stale.db)
    assert fresh_ledger.latest_card_id(slot) == stale_ledger.latest_card_id(slot)
    assert fresh_ledger.load_card_payload(
        fresh_ledger.latest_card_id(slot)  # type: ignore[arg-type]
    ) == stale_ledger.load_card_payload(
        stale_ledger.latest_card_id(slot)  # type: ignore[arg-type]
    )
