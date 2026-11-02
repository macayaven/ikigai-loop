"""Ticket 14 Step 4: the voice fold table, disputes, and the chain rule."""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from framework.briefing.context import MetricSnapshot, PrivateTerms, ProfileLimits
from framework.briefing.schemas import Commitment
from framework.schemas.core import Fact, FactWindow
from framework.schemas.events import (
    AppCorrectionData,
    AppFactDisputeData,
    AppTapData,
    Event,
)
from framework.store import EventStore
from framework.store.fact_store import FactStore
from framework.store.proposal_store import ProposalStore
from framework.voice.state import (
    DisputedCitations,
    MetricCitation,
    apply_disputes,
    disputed_number_displays,
    disputes_for_cycle,
    filter_eligible,
    fold_corrections,
    fold_disputes,
    is_hidden,
    load_voice_state,
    standing_chain_ruling,
)

MADRID = ZoneInfo("Europe/Madrid")
SUBJECT = "subject-1"

MON_10 = datetime(2026, 11, 2, 10, 0, tzinfo=MADRID)
MON_20 = datetime(2026, 11, 2, 20, 0, tzinfo=MADRID)
TUE_10 = datetime(2026, 11, 3, 10, 0, tzinfo=MADRID)
TUE_00 = datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
WED_10 = datetime(2026, 11, 4, 10, 0, tzinfo=MADRID)
SUN_10 = datetime(2026, 11, 1, 10, 0, tzinfo=MADRID)
SUN_20 = datetime(2026, 11, 1, 20, 0, tzinfo=MADRID)
NEXT_MON_09 = datetime(2026, 11, 9, 9, 0, tzinfo=MADRID)

EARLY = datetime(2000, 1, 1, tzinfo=MADRID)


def correction(
    operation: str,
    until: str | None,
    *,
    commitment_id: str | None = "cm-test-one",
    said_at: datetime = MON_10,
    message_id: int = 1,
    slot: datetime | None = None,
    event_id: str | None = None,
    event_time: datetime | None = None,
) -> Event:
    data = AppCorrectionData(
        commitment_id=commitment_id,
        operation=operation,  # type: ignore[arg-type]
        until=until,  # type: ignore[arg-type]
        slot=slot if slot is not None else said_at,
        said_at=said_at,
        message_id=message_id,
        reported_by="user",
    )
    moment = event_time if event_time is not None else said_at
    return Event(
        id=event_id or f"evt-{message_id}",
        subject_id=SUBJECT,
        source="telegram",
        type="app.correction",
        time=moment,
        source_id=f"voice:{message_id}",
        data=data,
        tier="private",
        collected_at=moment,
        collector_version="voice-test@0.1.0",
    )


def dispute(
    *,
    fact_id: str | None = None,
    metric_id: str | None = None,
    metric_value: float | None = None,
    cycle_id: str | None = None,
    card_id: str = "card-" + "a" * 16,
    message_id: int = 1,
    said_time: datetime = MON_10,
) -> Event:
    data = AppFactDisputeData(
        fact_id=fact_id,
        metric_id=metric_id,
        metric_value=metric_value,
        cycle_id=cycle_id,
        card_id=card_id,
        message_id=message_id,
        reported_by="user",
    )
    return Event(
        id=f"evt-dispute-{message_id}",
        subject_id=SUBJECT,
        source="telegram",
        type="app.fact_dispute",
        time=said_time,
        source_id=f"voice:{message_id}:dispute",
        data=data,
        tier="private",
        collected_at=said_time,
        collector_version="voice-test@0.1.0",
    )


def tap(card_id: str, target: str, moment: datetime, event_id: str) -> Event:
    return Event(
        id=event_id,
        subject_id=SUBJECT,
        source="telegram",
        type="app.tap",
        time=moment,
        source_id=f"{card_id}:{target}",
        data=AppTapData(block_id=card_id, target=target),
        tier="private",
        collected_at=moment,
        collector_version="telegram@0.1.0",
    )


def commitment(cid: str) -> Commitment:
    return Commitment(
        id=cid,
        profile_id="builder",
        title=f"Synthetic commitment {cid}",
        kind="build",
        dimension="good_at",
        evidence="tap",
    )


# -- the fold table, row by row -------------------------------------------


def test_skip_slot_hides_only_that_slot() -> None:
    entries = fold_corrections([correction("skip", "slot", slot=MON_20)])
    (entry,) = entries.values()
    assert entry.hidden_for_slot == MON_20
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_10)


def test_skip_today_returns_at_next_midnight() -> None:
    entries = fold_corrections([correction("skip", "today")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_00)
    assert not is_hidden(entry, TUE_10)


def test_skip_tomorrow_returns_the_day_after() -> None:
    entries = fold_corrections([correction("skip", "tomorrow")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 4, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, MON_20)
    assert is_hidden(entry, TUE_10)
    assert not is_hidden(entry, WED_10)


def test_skip_this_week_returns_next_monday() -> None:
    entries = fold_corrections([correction("skip", "this_week")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 9, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, SUN_20)
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, NEXT_MON_09)


def test_sunday_this_week_returns_next_day() -> None:
    entries = fold_corrections(
        [correction("skip", "this_week", said_at=SUN_10, slot=SUN_20)]
    )
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 2, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, SUN_20)
    assert not is_hidden(entry, MON_10)


def test_skip_open_hides_until_keep() -> None:
    entries = fold_corrections([correction("skip", "open")])
    (entry,) = entries.values()
    assert entry.status == "skipped_open"
    assert is_hidden(entry, MON_20)
    assert is_hidden(entry, NEXT_MON_09)


def test_defer_today_hides_this_slot_only() -> None:
    entries = fold_corrections([correction("defer", "today", slot=MON_20)])
    (entry,) = entries.values()
    assert entry.hidden_for_slot == MON_20
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_10)


def test_defer_tomorrow_returns_at_midnight() -> None:
    entries = fold_corrections([correction("defer", "tomorrow")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_10)


def test_defer_this_week_returns_tomorrow() -> None:
    entries = fold_corrections([correction("defer", "this_week")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_10)


def test_drop_open_hides_always() -> None:
    entries = fold_corrections([correction("drop", "open")])
    (entry,) = entries.values()
    assert entry.status == "dropped"
    assert is_hidden(entry, MON_20)
    assert is_hidden(entry, NEXT_MON_09)


def test_done_today_counts_for_that_day() -> None:
    entries = fold_corrections([correction("done", "today")])
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    assert entry.done_day == datetime(2026, 11, 2, tzinfo=MADRID).date()
    assert is_hidden(entry, MON_20)
    assert not is_hidden(entry, TUE_10)


def test_keep_clears_skip() -> None:
    events = [
        correction("skip", "open", message_id=1, event_id="evt-1"),
        correction("keep", None, message_id=2, event_id="evt-2"),
    ]
    assert fold_corrections(events) == {}


def test_keep_clears_drop() -> None:
    events = [
        correction("drop", "open", message_id=1, event_id="evt-1"),
        correction("keep", None, message_id=2, event_id="evt-2"),
    ]
    assert fold_corrections(events) == {}


def test_keep_clears_done() -> None:
    events = [
        correction("done", "today", message_id=1, event_id="evt-1"),
        correction("keep", None, message_id=2, event_id="evt-2"),
    ]
    assert fold_corrections(events) == {}


def test_keep_clears_defer() -> None:
    events = [
        correction("defer", "tomorrow", message_id=1, event_id="evt-1"),
        correction("keep", None, message_id=2, event_id="evt-2"),
    ]
    assert fold_corrections(events) == {}


def test_last_wins_per_commitment() -> None:
    events = [
        correction("skip", "open", message_id=1, event_id="evt-1"),
        correction("defer", "tomorrow", message_id=2, event_id="evt-2"),
    ]
    entries = fold_corrections(events)
    assert entries["cm-test-one"].status == "defer"


def test_fact_correction_and_none_change_no_state() -> None:
    events = [
        correction(
            "fact_correction",
            None,
            commitment_id=None,
            message_id=1,
            event_id="evt-1",
        ),
        correction("none", None, commitment_id=None, message_id=2, event_id="evt-2"),
    ]
    assert fold_corrections(events) == {}


def test_fold_orders_by_said_at_not_store_order() -> None:
    said_monday = datetime(2026, 11, 2, 10, 0, tzinfo=MADRID)
    said_tuesday = datetime(2026, 11, 3, 10, 0, tzinfo=MADRID)
    stored_wednesday = datetime(2026, 11, 4, 10, 0, tzinfo=MADRID)
    stored_monday = datetime(2026, 11, 2, 11, 0, tzinfo=MADRID)
    skip = correction(
        "skip",
        "open",
        said_at=said_monday,
        message_id=10,
        event_id="evt-10",
        event_time=stored_wednesday,
    )
    keep = correction(
        "keep",
        None,
        said_at=said_tuesday,
        message_id=11,
        event_id="evt-11",
        event_time=stored_monday,
    )
    assert fold_corrections([skip, keep]) == {}
    assert fold_corrections([keep, skip]) == {}


def test_overnight_note_hides_nothing_tuesday() -> None:
    said = datetime(2026, 11, 2, 23, 59, tzinfo=MADRID)
    handled = datetime(2026, 11, 3, 0, 10, tzinfo=MADRID)
    events = [
        correction(
            "skip",
            "today",
            said_at=said,
            message_id=20,
            event_id="evt-20",
            event_time=handled,
            slot=handled,
        )
    ]
    entries = fold_corrections(events)
    (entry,) = entries.values()
    assert entry.hidden_until == datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
    tuesday_slot = datetime(2026, 11, 3, 20, 0, tzinfo=MADRID)
    assert not is_hidden(entry, tuesday_slot)


def test_is_hidden_none_entry_is_false() -> None:
    assert not is_hidden(None, MON_20)


def test_filter_eligible_keeps_file_order() -> None:
    entries = fold_corrections(
        [correction("drop", "open", commitment_id="cm-b", message_id=1)]
    )
    result = filter_eligible(
        [commitment("cm-a"), commitment("cm-b"), commitment("cm-c")],
        entries,
        slot=MON_20,
    )
    assert [c.id for c in result] == ["cm-a", "cm-c"]


# -- disputes --------------------------------------------------------------


def test_fold_disputes_collects_facts_and_metrics() -> None:
    events = [
        dispute(fact_id="fact:synthetic-1", message_id=1),
        dispute(
            metric_id="period.last.pushes",
            metric_value=3.0,
            cycle_id="cycle-1",
            message_id=2,
        ),
        dispute(
            metric_id="period.last.pushes",
            metric_value=4.0,
            cycle_id="cycle-2",
            message_id=3,
        ),
    ]
    disputed = fold_disputes(events)
    assert disputed.fact_ids == frozenset({"fact:synthetic-1"})
    assert disputed.metrics == (
        MetricCitation(
            metric_id="period.last.pushes",
            value=3.0,
            cycle_id="cycle-1",
            day=date(2026, 11, 2),
        ),
        MetricCitation(
            metric_id="period.last.pushes",
            value=4.0,
            cycle_id="cycle-2",
            day=date(2026, 11, 2),
        ),
    )


def test_fold_disputes_ignores_corrections() -> None:
    events = [correction("skip", "open", message_id=1)]
    assert fold_disputes(events) == DisputedCitations()


def test_load_voice_state_reads_from_early_start(tmp_path: Path) -> None:
    db = tmp_path / "voice-state.db"
    store = EventStore(db_path=db)
    try:
        weeks_ago = datetime(2026, 10, 5, 10, 0, tzinfo=MADRID)
        drop = correction(
            "drop",
            "open",
            said_at=weeks_ago,
            message_id=40,
            event_id="evt-40",
            event_time=weeks_ago,
            slot=weeks_ago,
        )
        assert store.append_event(drop)
        assert store.append_event(dispute(fact_id="fact:synthetic-1", message_id=41))
        end = datetime(2026, 11, 3, 0, 0, tzinfo=MADRID)
        entries, disputed = load_voice_state(store, SUBJECT, start=EARLY, end=end)
    finally:
        store.close()
    assert entries["cm-test-one"].status == "dropped"
    assert is_hidden(entries["cm-test-one"], MON_20)
    assert disputed.fact_ids == frozenset({"fact:synthetic-1"})


# -- the chain rule ---------------------------------------------------------


OLD_CARD = "card-" + "0" * 16
NEW_CARD = "card-" + "1" * 16


def test_chain_prefers_new_card_ruling() -> None:
    events = [
        tap(OLD_CARD, "A", MON_10, "evt-tap-1"),
        tap(NEW_CARD, "B", TUE_10, "evt-tap-2"),
    ]
    assert standing_chain_ruling(events, [OLD_CARD, NEW_CARD]) == (NEW_CARD, "B")


def test_chain_falls_back_to_old_ruling() -> None:
    events = [tap(OLD_CARD, "neither", MON_10, "evt-tap-1")]
    assert standing_chain_ruling(events, [OLD_CARD, NEW_CARD]) == (
        OLD_CARD,
        "neither",
    )


def test_late_old_tap_cannot_win_over_new() -> None:
    events = [
        tap(NEW_CARD, "B", TUE_10, "evt-tap-2"),
        tap(OLD_CARD, "A", WED_10, "evt-tap-3"),
    ]
    assert standing_chain_ruling(events, [OLD_CARD, NEW_CARD]) == (NEW_CARD, "B")


def test_chain_without_rulings_is_none() -> None:
    assert standing_chain_ruling([], [OLD_CARD, NEW_CARD]) is None


# -- apply_disputes ----------------------------------------------------------

STATEMENT = (
    "Work/Programming screen hours decreased from 4.75 in prior to 1.75 in last."
)


def disputed_fact(statement: str = STATEMENT) -> Fact:
    return Fact(
        id="fact:synthetic-7",
        subject_id=SUBJECT,
        window=FactWindow(
            start=datetime(2026, 10, 30, 14, 0, tzinfo=MADRID), end=MON_10
        ),
        statement=statement,
        evidence=["ev-synthetic-7"],
        tier="public",
    )


def test_apply_disputes_none_is_identity() -> None:
    facts = [disputed_fact()]
    snapshot = MetricSnapshot(values={"calendar.busy_hours": 2.5})
    kept, filtered, parent = apply_disputes(facts, snapshot, None, None)
    assert [f.id for f in kept] == ["fact:synthetic-7"]
    assert filtered.values == {"calendar.busy_hours": 2.5}
    assert parent is None


def test_apply_disputes_drops_fact_and_its_numbers() -> None:
    facts = [disputed_fact()]
    snapshot = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "period.last.screen.code": 1.75,
            "calendar.busy_hours": 2.5,
        }
    )
    parent = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "calendar.busy_hours": 2.5,
        }
    )
    disputed = DisputedCitations(fact_ids=frozenset({"fact:synthetic-7"}))
    kept, filtered, filtered_parent = apply_disputes(facts, snapshot, parent, disputed)
    assert kept == []
    assert filtered.values == {"calendar.busy_hours": 2.5}
    assert filtered_parent is not None
    assert filtered_parent.values == {"calendar.busy_hours": 2.5}


def test_apply_disputes_drops_metric_at_same_value_only() -> None:
    facts = [disputed_fact("Synthetic walk logged in the evening")]
    snapshot = MetricSnapshot(
        values={"period.last.pushes": 3.0, "calendar.busy_hours": 2.5}
    )
    disputed = DisputedCitations(
        metrics=(MetricCitation("period.last.pushes", 3.0, "cycle-1", DAY_SAT),)
    )
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    assert [f.id for f in kept] == ["fact:synthetic-7"]
    assert filtered.values == {"calendar.busy_hours": 2.5}
    moved = MetricSnapshot(values={"period.last.pushes": 9.0})
    _, kept_moved, _ = apply_disputes(facts, moved, None, disputed)
    assert kept_moved.values == {"period.last.pushes": 9.0}


def test_disputed_fact_metrics_are_not_offered(tmp_path: Path) -> None:
    from evals.proposal_cases import ScriptedWonderClient, text_entry
    from framework.cycle import run_proposals
    from framework.glimmer.facts import FactResult, PassResult
    from framework.proposal.core import ModelParams

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=MADRID)
    slot = datetime(2026, 10, 31, 15, 7, tzinfo=MADRID)
    db = tmp_path / "disputed.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        result = FactResult(
            facts=(disputed_fact(),),
            code_fact_ids=(),
            snapshot=MetricSnapshot(
                values={
                    "period.prior.screen.code": 4.75,
                    "period.last.screen.code": 1.75,
                    "calendar.busy_hours": 2.5,
                }
            ),
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
                    noop_reason=None,
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
                    noop_reason=None,
                ),
            ),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT,
            as_of=as_of,
            window_start=as_of,
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
        bad = (
            '{"commitment_id": "cm-test-one", "overall_state": [{"text": '
            '"Synthetic probe sentence", "fact_ids": ["fact:synthetic-9"], '
            '"metric_refs": []}], "working": [], "not_working": []}'
        )
        client = ScriptedWonderClient((text_entry(bad), text_entry(bad)))
        results = run_proposals(
            as_of=as_of,
            slot=slot,
            subject_id=SUBJECT,
            profiles=("builder",),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={
                "builder": (commitment("cm-test-one"),),
            },
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
            disputed=DisputedCitations(fact_ids=frozenset({"fact:synthetic-7"})),
        )
        assert len(results) == 1
        prompt = client.requests[0].prompt
        # Quoted display values only: the template itself names bare 1.75.
        assert '"4.75"' not in prompt
        assert '"1.75"' not in prompt
        assert "period.prior.screen.code" not in prompt
        assert "period.last.screen.code" not in prompt
        assert STATEMENT not in prompt
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


def test_disputes_for_cycle_keeps_facts_and_named_cycle_only() -> None:
    disputed = DisputedCitations(
        fact_ids=frozenset({"fact:synthetic-1"}),
        metrics=(
            MetricCitation("period.last.pushes", 3.0, "cycle-0", DAY_FRI),
            MetricCitation("period.last.pushes", 4.0, "cycle-1", DAY_FRI),
        ),
    )
    narrowed = disputes_for_cycle(disputed, "cycle-1", DAY_SAT)
    assert narrowed.fact_ids == frozenset({"fact:synthetic-1"})
    assert narrowed.metrics == (
        MetricCitation("period.last.pushes", 4.0, "cycle-1", DAY_FRI),
    )


def _run_push_claim(tmp_path: Path, disputed: DisputedCitations) -> str:
    """Record cycle-1 with pushes at 3.0, propose a claim citing it.

    Returns the single result kind: ``proposal`` when the citation's
    metric survives the dispute filter, ``fallback`` when it does not.
    Mirrors the setup in ``test_disputed_fact_metrics_are_not_offered``.
    """
    from evals.proposal_cases import (
        BASE_FACTS,
        BASE_SNAPSHOT,
        GOOD_DRAFT,
        PARSER,
        ScriptedWonderClient,
        text_entry,
    )
    from framework.cycle import run_proposals
    from framework.glimmer.facts import FactResult, PassResult
    from framework.proposal.core import ModelParams

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=MADRID)
    slot = datetime(2026, 10, 31, 15, 7, tzinfo=MADRID)
    db = tmp_path / "cycle-scoped.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        result = FactResult(
            facts=tuple(BASE_FACTS),
            code_fact_ids=(),
            snapshot=MetricSnapshot(values=dict(BASE_SNAPSHOT)),
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
                    noop_reason=None,
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
                    noop_reason=None,
                ),
            ),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT,
            as_of=as_of,
            window_start=as_of,
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
        client = ScriptedWonderClient((text_entry(GOOD_DRAFT), text_entry(GOOD_DRAFT)))
        results = run_proposals(
            as_of=as_of,
            slot=slot,
            subject_id=SUBJECT,
            profiles=("builder",),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={"builder": (PARSER,)},
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
            disputed=disputed,
        )
        assert len(results) == 1
        return results[0].kind
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


def test_metric_dispute_from_older_cycle_does_not_remove_metric(
    tmp_path: Path,
) -> None:
    kind = _run_push_claim(
        tmp_path,
        DisputedCitations(
            metrics=(MetricCitation("period.last.pushes", 3.0, "cycle-0", DAY_FRI),)
        ),
    )
    assert kind == "proposal"


def test_metric_dispute_from_stored_cycle_removes_metric(tmp_path: Path) -> None:
    kind = _run_push_claim(
        tmp_path,
        DisputedCitations(
            metrics=(MetricCitation("period.last.pushes", 3.0, "cycle-1", DAY_FRI),)
        ),
    )
    assert kind == "fallback"


def test_disputed_number_displays_only_disputed_statements() -> None:
    rows = [
        (
            "fact-1",
            (
                "Work/Programming screen hours decreased from 4.75 in prior"
                " to 1.75 in last."
            ),
        ),
        ("fact-2", "Something unrelated at 9.5."),
    ]
    disputed = DisputedCitations(fact_ids=frozenset({"fact-1"}))
    assert disputed_number_displays(rows, disputed) == frozenset({"4.75", "1.75"})
    assert disputed_number_displays(rows, DisputedCitations()) == frozenset()


def _fact_with(statement: str, fact_id: str = "fact:synthetic-7") -> Fact:
    return Fact(
        id=fact_id,
        subject_id=SUBJECT,
        window=FactWindow(
            start=datetime(2026, 10, 30, 14, 0, tzinfo=MADRID), end=MON_10
        ),
        statement=statement,
        evidence=["ev-synthetic-7"],
        tier="public",
    )


def test_metric_citation_drops_fact_holding_its_number() -> None:
    facts = [
        _fact_with("Synthetic screen time was 1.75 hours in the last period."),
        _fact_with("Synthetic unrelated line at 9.5.", "fact:synthetic-9"),
    ]
    snapshot = MetricSnapshot(
        values={
            "period.last.screen.code": 1.75,
            "period.last.screen.other": 1.75,
            "calendar.busy_hours": 2.5,
        }
    )
    disputed = DisputedCitations(
        metrics=(MetricCitation("period.last.screen.code", 1.75, "cycle-1", DAY_SAT),)
    )
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    assert [fact.id for fact in kept] == ["fact:synthetic-9"]
    assert filtered.values == {
        "period.last.screen.other": 1.75,
        "calendar.busy_hours": 2.5,
    }


def test_statement_token_7_matches_citation_at_7() -> None:
    facts = [_fact_with("Synthetic count reached 7.0 in the last period.")]
    snapshot = MetricSnapshot(values={"period.last.pushes": 7.0})
    disputed = DisputedCitations(
        metrics=(MetricCitation("period.last.pushes", 7.0, "cycle-1", DAY_SAT),)
    )
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    assert kept == []
    assert filtered.values == {}


def test_disputed_fact_drops_sibling_fact_sharing_a_number() -> None:
    facts = [
        _fact_with(STATEMENT, "fact:synthetic-7"),
        _fact_with(
            "Synthetic sibling line holding 4.75 and also 7.0.",
            "fact:synthetic-8",
        ),
        _fact_with("Synthetic unrelated line at 9.5.", "fact:synthetic-9"),
    ]
    snapshot = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "period.last.screen.code": 1.75,
            "calendar.busy_hours": 9.5,
        }
    )
    disputed = DisputedCitations(fact_ids=frozenset({"fact:synthetic-7"}))
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    assert [fact.id for fact in kept] == ["fact:synthetic-9"]
    assert filtered.values == {"calendar.busy_hours": 9.5}


def test_disputed_fact_still_drops_metrics_showing_its_numbers() -> None:
    facts = [_fact_with(STATEMENT)]
    snapshot = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "period.last.screen.code": 1.75,
            "calendar.busy_hours": 2.5,
        }
    )
    parent = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "calendar.busy_hours": 2.5,
        }
    )
    disputed = DisputedCitations(fact_ids=frozenset({"fact:synthetic-7"}))
    kept, filtered, filtered_parent = apply_disputes(facts, snapshot, parent, disputed)
    assert kept == []
    assert filtered.values == {"calendar.busy_hours": 2.5}
    assert filtered_parent is not None
    assert filtered_parent.values == {"calendar.busy_hours": 2.5}


def test_number_sharing_drop_is_not_transitive() -> None:
    facts = [
        _fact_with(STATEMENT, "fact:synthetic-7"),
        _fact_with(
            "Synthetic sibling holding 4.75 and also 3.25.",
            "fact:synthetic-8",
        ),
        _fact_with(
            "Synthetic third line holding only 3.25.",
            "fact:synthetic-9",
        ),
    ]
    snapshot = MetricSnapshot(
        values={
            "period.prior.screen.code": 4.75,
            "period.last.screen.code": 1.75,
            "period.last.other": 3.25,
            "calendar.busy_hours": 2.5,
        }
    )
    disputed = DisputedCitations(fact_ids=frozenset({"fact:synthetic-7"}))
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    # The sibling goes for sharing 4.75, but its other number 3.25 does not
    # become disputed: the third fact and its metric stay.
    assert [fact.id for fact in kept] == ["fact:synthetic-9"]
    assert filtered.values == {
        "period.last.other": 3.25,
        "calendar.busy_hours": 2.5,
    }


def test_other_cycle_metric_narrowed_first_drops_no_fact() -> None:
    facts = [_fact_with("Synthetic screen time was 1.75 hours in the last period.")]
    snapshot = MetricSnapshot(values={"period.last.screen.code": 1.75})
    disputed = disputes_for_cycle(
        DisputedCitations(
            metrics=(
                MetricCitation("period.last.screen.code", 1.75, "cycle-0", DAY_FRI),
            )
        ),
        "cycle-1",
        DAY_SAT,
    )
    kept, filtered, _ = apply_disputes(facts, snapshot, None, disputed)
    assert [fact.id for fact in kept] == ["fact:synthetic-7"]
    assert filtered.values == {"period.last.screen.code": 1.75}


def test_empty_disputed_set_changes_nothing() -> None:
    facts = [_fact_with(STATEMENT)]
    snapshot = MetricSnapshot(values={"calendar.busy_hours": 2.5})
    kept, filtered, parent = apply_disputes(facts, snapshot, None, DisputedCitations())
    assert [fact.id for fact in kept] == ["fact:synthetic-7"]
    assert filtered.values == {"calendar.busy_hours": 2.5}
    assert parent is None


def test_fact_holding_disputed_metric_number_not_in_prompt(tmp_path: Path) -> None:
    from evals.proposal_cases import ScriptedWonderClient, text_entry
    from framework.cycle import run_proposals
    from framework.glimmer.facts import FactResult, PassResult
    from framework.proposal.core import ModelParams

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=MADRID)
    slot = datetime(2026, 10, 31, 15, 7, tzinfo=MADRID)
    db = tmp_path / "disputed-metric-number.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        result = FactResult(
            facts=(
                _fact_with("Synthetic screen time was 1.75 hours in the last period."),
            ),
            code_fact_ids=(),
            snapshot=MetricSnapshot(
                values={
                    "period.last.screen.code": 1.75,
                    "calendar.busy_hours": 2.5,
                }
            ),
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
                    noop_reason=None,
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
                    noop_reason=None,
                ),
            ),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT,
            as_of=as_of,
            window_start=as_of,
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
        bad = (
            '{"commitment_id": "cm-test-one", "overall_state": [{"text": '
            '"Synthetic probe sentence", "fact_ids": ["fact:synthetic-9"], '
            '"metric_refs": []}], "working": [], "not_working": []}'
        )
        client = ScriptedWonderClient((text_entry(bad), text_entry(bad)))
        results = run_proposals(
            as_of=as_of,
            slot=slot,
            subject_id=SUBJECT,
            profiles=("builder",),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={"builder": (commitment("cm-test-one"),)},
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
            disputed=DisputedCitations(
                metrics=(
                    MetricCitation("period.last.screen.code", 1.75, "cycle-1", DAY_SAT),
                )
            ),
        )
        assert len(results) == 1
        prompt = client.requests[0].prompt
        assert "Synthetic screen time was 1.75 hours in the last period." not in prompt
        assert "period.last.screen.code" not in prompt
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()


# -- metric disputes bite by cycle or by Madrid day ---------------------------

DAY_FRI = date(2026, 10, 30)
DAY_SAT = date(2026, 10, 31)


def _day_citation(
    metric_id: str = "period.last.pushes",
    value: float = 3.0,
    cycle_id: str = "cycle-0",
    day: date = DAY_FRI,
) -> MetricCitation:
    return MetricCitation(metric_id=metric_id, value=value, cycle_id=cycle_id, day=day)


def test_metric_dispute_other_cycle_same_day_bites() -> None:
    disputed = DisputedCitations(metrics=(_day_citation(day=DAY_SAT),))
    narrowed = disputes_for_cycle(disputed, "cycle-1", DAY_SAT)
    assert narrowed.metrics == disputed.metrics


def test_metric_dispute_other_cycle_next_day_ignored() -> None:
    disputed = DisputedCitations(metrics=(_day_citation(day=DAY_FRI),))
    narrowed = disputes_for_cycle(disputed, "cycle-1", DAY_SAT)
    assert narrowed.metrics == ()


def test_metric_dispute_same_cycle_later_day_bites() -> None:
    disputed = DisputedCitations(
        metrics=(_day_citation(cycle_id="cycle-1", day=DAY_FRI),)
    )
    narrowed = disputes_for_cycle(disputed, "cycle-1", DAY_SAT)
    assert narrowed.metrics == disputed.metrics


def test_metric_dispute_new_value_ignored_on_any_day() -> None:
    facts = [_fact_with("Synthetic unrelated line at 9.5.", "fact:synthetic-9")]
    snapshot = MetricSnapshot(values={"period.last.screen.code": 9.5})
    same_day = DisputedCitations(
        metrics=(
            _day_citation(
                metric_id="period.last.screen.code",
                value=1.75,
                cycle_id="cycle-1",
                day=DAY_SAT,
            ),
        )
    )
    other_day = DisputedCitations(
        metrics=(
            _day_citation(
                metric_id="period.last.screen.code",
                value=1.75,
                cycle_id="cycle-0",
                day=DAY_FRI,
            ),
        )
    )
    for disputed in (same_day, other_day):
        narrowed = disputes_for_cycle(disputed, "cycle-1", DAY_SAT)
        kept, filtered, _ = apply_disputes(facts, snapshot, None, narrowed)
        assert [fact.id for fact in kept] == ["fact:synthetic-9"]
        assert filtered.values == {"period.last.screen.code": 9.5}


def test_midnight_boundary_disputes_are_different_days() -> None:
    before = dispute(
        metric_id="period.last.pushes",
        metric_value=3.0,
        cycle_id="cycle-0",
        message_id=50,
        said_time=datetime(2026, 10, 30, 23, 59, tzinfo=MADRID),
    )
    after = dispute(
        metric_id="period.last.pushes",
        metric_value=3.0,
        cycle_id="cycle-0",
        message_id=51,
        said_time=datetime(2026, 10, 31, 0, 1, tzinfo=MADRID),
    )
    disputed = fold_disputes([before, after])
    assert [citation.day for citation in disputed.metrics] == [DAY_FRI, DAY_SAT]
    assert disputes_for_cycle(disputed, "cycle-1", DAY_SAT).metrics == (
        disputed.metrics[1],
    )
    assert disputes_for_cycle(disputed, "cycle-1", DAY_FRI).metrics == (
        disputed.metrics[0],
    )


def test_metric_disputed_earlier_today_in_other_cycle_not_in_prompt(
    tmp_path: Path,
) -> None:
    from evals.proposal_cases import ScriptedWonderClient, text_entry
    from framework.cycle import run_proposals
    from framework.glimmer.facts import FactResult, PassResult
    from framework.proposal.core import ModelParams

    as_of = datetime(2026, 10, 31, 14, 0, tzinfo=MADRID)
    slot = datetime(2026, 10, 31, 15, 7, tzinfo=MADRID)
    db = tmp_path / "disputed-earlier-today.db"
    store = EventStore(db_path=db)
    fact_store = FactStore(db_path=db)
    proposal_store = ProposalStore(db_path=db)
    try:
        result = FactResult(
            facts=(
                _fact_with("Synthetic screen time was 1.75 hours in the last period."),
            ),
            code_fact_ids=(),
            snapshot=MetricSnapshot(
                values={
                    "period.last.screen.code": 1.75,
                    "calendar.busy_hours": 2.5,
                }
            ),
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
                    noop_reason=None,
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
                    noop_reason=None,
                ),
            ),
            responses=(),
            cycle_id="cycle-1",
            subject_id=SUBJECT,
            as_of=as_of,
            window_start=as_of,
            prompt_hash="hash",
            dropped=(),
            is_noop=False,
            noop_reason=None,
        )
        assert fact_store.record_cycle(result) == 1
        bad = (
            '{"commitment_id": "cm-test-one", "overall_state": [{"text": '
            '"Synthetic probe sentence", "fact_ids": ["fact:synthetic-9"], '
            '"metric_refs": []}], "working": [], "not_working": []}'
        )
        client = ScriptedWonderClient((text_entry(bad), text_entry(bad)))
        results = run_proposals(
            as_of=as_of,
            slot=slot,
            subject_id=SUBJECT,
            profiles=("builder",),
            store=store,
            fact_store=fact_store,
            proposal_store=proposal_store,
            client=client,
            private_terms=PrivateTerms(terms=(), available=True),
            eligible_by_profile={"builder": (commitment("cm-test-one"),)},
            limits=ProfileLimits(
                timezone="Europe/Madrid",
                allowed_start=time(13, 0),
                allowed_end=time(23, 30),
                max_actions=3,
            ),
            models=ModelParams(
                first_model="muse-wonder-1.0",
                first_effort="high",
                retry_model="muse-wonder-1.0",
                retry_effort="high",
            ),
            stale_after_s=43200.0,
            disputed=DisputedCitations(
                metrics=(
                    MetricCitation(
                        metric_id="period.last.screen.code",
                        value=1.75,
                        cycle_id="cycle-0",
                        day=DAY_SAT,
                    ),
                )
            ),
        )
        assert len(results) == 1
        prompt = client.requests[0].prompt
        assert "period.last.screen.code" not in prompt
        assert "Synthetic screen time was 1.75 hours in the last period." not in prompt
    finally:
        proposal_store.close()
        fact_store.close()
        store.close()
