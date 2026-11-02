"""Ticket 13 slice 2: card assembly, since line, chart data (made-up data)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from framework.briefing.schemas import Commitment
from framework.cycle import card_build
from framework.cycle.card_build import (
    build_card,
    build_chart_data,
    build_statements,
    build_tally,
    minimal_chart_data,
    since_counts,
    since_line,
)
from framework.cycle.slot_ledger import SlotCardRow
from framework.proposal.core import ProposalResult
from framework.schemas.events import Event
from framework.telegram.chart import render_chart_png
from framework.telegram.models import (
    ChartData,
    first_rulings,
    render_card_text,
    why_reply_pieces,
)

MADRID = ZoneInfo("Europe/Madrid")
UTC_PLUS_1 = MADRID


def slot_at(hm: str, day: int = 2) -> datetime:
    hour, minute = (int(part) for part in hm.split(":"))
    return datetime(2026, 11, day, hour, minute, tzinfo=MADRID)


def commitment(
    cid: str, profile: str, kind: str = "build", title: str | None = None
) -> Commitment:
    return Commitment.model_validate(
        {
            "id": cid,
            "profile_id": profile,
            "title": title or f"Title {cid}",
            "kind": kind,
            "dimension": "love",
            "evidence": "github_push",
        }
    )


def briefing(
    cid: str,
    profile: str,
    slot: datetime,
    action_text: str = "Model action wording",
) -> dict[str, object]:
    start = slot.replace(hour=16, minute=0)
    end = slot.replace(hour=17, minute=0)
    return {
        "id": f"brf-{cid}",
        "profile_id": profile,
        "subject_id": "subject-a",
        "slot": slot.isoformat(),
        "sections": [
            {
                "type": "overall_state",
                "claims": [
                    {
                        "id": "c1",
                        "text": "First claim text here.",
                        "fact_ids": [],
                        "metric_refs": [],
                    },
                ],
            },
            {
                "type": "working",
                "claims": [
                    {
                        "id": "c2",
                        "text": "Second claim text here.",
                        "fact_ids": [],
                        "metric_refs": [],
                    },
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
                        "text": action_text,
                        "dimension": "love",
                        "proposed_start": start.isoformat(),
                        "proposed_end": end.isoformat(),
                    }
                ],
            },
        ],
    }


def proposal_result(
    profile: str,
    cid: str,
    slot: datetime,
    kind: str = "proposal",
    reason_codes: tuple[str, ...] = (),
    title: str | None = None,
) -> ProposalResult:
    by_id = {
        cid: commitment(cid, profile, title=title)
        if title
        else commitment(cid, profile)
    }
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Briefing

    hour = TimeInterval(
        start=slot.replace(hour=16, minute=0),
        end=slot.replace(hour=17, minute=0),
    )
    if kind == "proposal":
        return ProposalResult(
            kind="proposal",
            profile_id=profile,
            subject_id="subject-a",
            cycle_id="cycle-1",
            run=1,
            slot=slot,
            hour=hour,
            briefing=Briefing.model_validate(briefing(cid, profile, slot)),
            fallback=None,
            reason_codes=reason_codes,
            attempts=(),
            cycle_age_s=1.0,
            prompt_hash="",
        )
    assert kind == "fallback"
    shown = by_id[cid]
    from framework.proposal.schemas import FallbackProposal

    return ProposalResult(
        kind="fallback",
        profile_id=profile,
        subject_id="subject-a",
        cycle_id="cycle-1",
        run=1,
        slot=slot,
        hour=hour,
        briefing=None,
        fallback=FallbackProposal(
            kind="fallback",
            profile_id=profile,
            subject_id="subject-a",
            slot=slot,
            commitment=shown,
            proposed_start=hour.start,
            proposed_end=hour.end,
            reason_codes=reason_codes,
        ),
        reason_codes=reason_codes,
        attempts=(),
        cycle_age_s=1.0,
        prompt_hash="",
    )


def noop_result(profile: str, slot: datetime) -> ProposalResult:
    return ProposalResult(
        kind="noop",
        profile_id=profile,
        subject_id="subject-a",
        cycle_id="cycle-1",
        run=1,
        slot=slot,
        hour=None,
        briefing=None,
        fallback=None,
        reason_codes=("NOOP_NO_FREE_HOUR",),
        attempts=(),
        cycle_age_s=1.0,
        prompt_hash="",
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


def screen_row(
    eid: str,
    moment: datetime,
    minutes: dict[str, float],
    collected_at: datetime | None = None,
    device: str = "mac",
) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "activitywatch",
            "type": "screen.hour",
            "time": moment.isoformat(),
            "source_id": f"{device}:{moment.isoformat()}:{eid}",
            "data": {
                "type": "screen.hour",
                "device": device,
                "minutes_by_category": minutes,
            },
            "tier": "private",
            "collected_at": (collected_at or moment).isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def push_row(eid: str, moment: datetime) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "github",
            "type": "github.push",
            "time": moment.isoformat(),
            "source_id": f"push-{eid}",
            "data": {
                "type": "github.push",
                "repo": "madeup/repo",
                "counts": {"commits": 1},
            },
            "tier": "public",
            "collected_at": moment.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def pr_row(eid: str, moment: datetime, opened: int = 1) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "github",
            "type": "github.pr",
            "time": moment.isoformat(),
            "source_id": f"pr-{eid}",
            "data": {
                "type": "github.pr",
                "repo": "madeup/repo",
                "counts": {"opened": opened},
            },
            "tier": "public",
            "collected_at": moment.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


# -- card --


def test_proposal_codes_stay_off_card_and_reach_detail() -> None:
    slot = slot_at("15:30")
    result = proposal_result(
        "builder", "b-1", slot, reason_codes=("PARENT_WITHOUT_DELTAS",)
    )
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(result,),
        commitments_by_id={"b-1": commitment("b-1", "builder")},
        picks={"builder": ("b-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert built.card.proposals[0].reason_codes == ()
    assert "PARENT_WITHOUT_DELTAS" in built.detail_codes


def test_fallback_title_and_codes_come_from_fallback() -> None:
    slot = slot_at("15:30")
    result = proposal_result(
        "disconnect",
        "d-1",
        slot,
        kind="fallback",
        reason_codes=("FALLBACK_NO_EVIDENCE",),
        title="Quiet evening title",
    )
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(result,),
        commitments_by_id={},
        picks={"disconnect": (None, None)},
        since_line=None,
    )
    assert built.card is not None
    (side,) = built.card.proposals
    assert side.kind == "fallback"
    assert side.title == "Quiet evening title"
    assert side.reason_codes == ("FALLBACK_NO_EVIDENCE",)
    assert built.card.since_line is None


def test_proposal_title_is_commitment_never_action_text() -> None:
    slot = slot_at("15:30")
    result = proposal_result("builder", "b-1", slot)
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(result,),
        commitments_by_id={
            "b-1": commitment("b-1", "builder", title="Filed commitment title")
        },
        picks={"builder": ("b-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert built.card.proposals[0].title == "Filed commitment title"


def test_gone_commitment_drops_side_with_code() -> None:
    slot = slot_at("15:30")
    builder = proposal_result("builder", "b-gone", slot)
    disconnect = proposal_result("disconnect", "d-1", slot)
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(builder, disconnect),
        commitments_by_id={"d-1": commitment("d-1", "disconnect")},
        picks={"builder": ("b-gone", None), "disconnect": ("d-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert [side.profile for side in built.card.proposals] == ["Disconnect"]
    assert built.card.proposals[0].letter == "A"
    assert [row.letter for row in built.sides] == ["A"]
    assert built.sides[0].profile_id == "disconnect"
    assert "COMMITMENT_GONE" in built.detail_codes


def test_stored_result_passes_through_build_card() -> None:
    from framework.store.proposal_store import StoredResult

    slot = slot_at("15:30")
    from framework.briefing.context import TimeInterval
    from framework.briefing.schemas import Briefing

    hour = TimeInterval(
        start=slot.replace(hour=16, minute=0),
        end=slot.replace(hour=17, minute=0),
    )
    stored = StoredResult(
        profile_id="builder",
        subject_id="subject-a",
        cycle_id="cycle-1",
        run=1,
        slot=slot,
        kind="proposal",
        briefing=Briefing.model_validate(briefing("b-1", "builder", slot)),
        fallback=None,
        hour=hour,
        reason_codes=(),
        cycle_age_s=1.0,
    )
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(stored,),
        commitments_by_id={"b-1": commitment("b-1", "builder")},
        picks={"builder": ("b-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert built.card.proposals[0].letter == "A"


def test_statements_header_then_claims_in_section_order() -> None:
    slot = slot_at("15:30")
    result = proposal_result("builder", "b-1", slot)
    assert result.briefing is not None
    pieces = build_statements([("A", "Builder", result.briefing)])
    assert pieces[0] == "A · Builder"
    assert pieces[1:] == (
        "First claim text here.",
        "Second claim text here.",
    )


def test_card_text_shows_title_hour_and_statements_through_why() -> None:
    slot = slot_at("15:30")
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(proposal_result("builder", "b-1", slot),),
        commitments_by_id={
            "b-1": commitment("b-1", "builder", title="Filed commitment title")
        },
        picks={"builder": ("b-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    text = render_card_text(built.card)
    assert "Filed commitment title" in text
    assert "16:00-17:00" in text
    assert why_reply_pieces(built.card)[:3] == list(built.card.statements)


def test_fallback_labelled_with_no_checked_facts() -> None:
    slot = slot_at("15:30")
    result = proposal_result(
        "disconnect",
        "d-1",
        slot,
        kind="fallback",
        reason_codes=("FALLBACK_NO_EVIDENCE",),
    )
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(result,),
        commitments_by_id={},
        picks={},
        since_line=None,
    )
    assert built.card is not None
    assert "(no checked facts)" in render_card_text(built.card)
    assert built.card.statements == ()


def test_one_noop_gives_one_proposal_card() -> None:
    slot = slot_at("15:30")
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(
            noop_result("builder", slot),
            proposal_result("disconnect", "d-1", slot),
        ),
        commitments_by_id={"d-1": commitment("d-1", "disconnect")},
        picks={"disconnect": ("d-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert len(built.card.proposals) == 1
    assert len(built.sides) == 1


def test_two_noops_give_no_card_and_no_send() -> None:
    slot = slot_at("13:30")
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(noop_result("builder", slot), noop_result("disconnect", slot)),
        commitments_by_id={},
        picks={},
        since_line=None,
    )
    assert built.card is None
    assert built.sides == ()


def test_lone_disconnect_is_a_and_tallies_under_disconnect() -> None:
    slot = slot_at("22:30")
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="night",
        results=(proposal_result("disconnect", "d-1", slot),),
        commitments_by_id={"d-1": commitment("d-1", "disconnect")},
        picks={"disconnect": ("d-1", None)},
        since_line="Since 20:30: nothing new recorded.",
    )
    assert built.card is not None
    assert built.card.proposals[0].letter == "A"
    assert built.sides[0].profile_id == "disconnect"
    moment = slot + timedelta(minutes=5)
    tally = build_tally((tap("t1", built.card.card_id, "A", moment),), built.sides)
    assert first_rulings((tap("t1", built.card.card_id, "A", moment),)) == {
        built.card.card_id: "A"
    }
    assert {item.label: item.count for item in tally} == {
        "Builder": 0,
        "Disconnect": 1,
        "Neither": 0,
    }


def test_two_sides_builder_a_disconnect_b_with_picks() -> None:
    slot = slot_at("15:30")
    built = build_card(
        slot=slot,
        subject_id="subject-a",
        as_of=slot,
        bucket="evening",
        results=(
            proposal_result("disconnect", "d-1", slot),
            proposal_result("builder", "b-1", slot),
        ),
        commitments_by_id={
            "b-1": commitment("b-1", "builder"),
            "d-1": commitment("d-1", "disconnect"),
        },
        picks={"builder": ("b-1", "b-2"), "disconnect": ("d-1", None)},
        since_line="Since 13:30: nothing new recorded.",
    )
    assert built.card is not None
    assert [(s.letter, s.profile) for s in built.card.proposals] == [
        ("A", "Builder"),
        ("B", "Disconnect"),
    ]
    by_profile = {row.profile_id: row for row in built.sides}
    assert by_profile["builder"].policy_pick == "b-1"
    assert by_profile["builder"].policy_alternative == "b-2"
    assert by_profile["builder"].card_id == built.card.card_id


# -- since --


def test_since_line_exact_text() -> None:
    counts = {
        "pushes": 2.0,
        "code": 1.4,
        "ai": 0.3,
        "comms": 0.0,
        "feed": 0.04,
        "browse": 0.0,
        "media": 0.0,
    }
    assert since_line(slot_at("13:30"), counts) == (
        "Since 13:30: 2 pushes + PRs, code 1.4h, ai 0.3h."
    )


def test_since_line_nothing_new_and_first_card() -> None:
    empty = {
        "pushes": 0.0,
        "code": 0.0,
        "ai": 0.0,
        "comms": 0.0,
        "feed": 0.0,
        "browse": 0.0,
        "media": 0.0,
    }
    assert since_line(slot_at("13:30"), empty) == ("Since 13:30: nothing new recorded.")
    assert since_line(slot_at("13:30"), empty, first=True) == (
        "First card, last 24h: nothing recorded."
    )
    counts = dict(empty, code=1.0)
    assert since_line(slot_at("13:30"), counts, first=True) == (
        "First card, last 24h: code 1.0h."
    )


def test_since_counts_recollected_hour_counts_latest_version_whole() -> None:
    # The 13:00 hour sits inside the card's interval [13:00, 15:00), so the
    # card counts it whole at the latest version collected by the card:
    # 1.5, not a growth of 0.5 over the earlier poll.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    hour_start = day.replace(hour=13, minute=0)
    first_seen = day.replace(hour=13, minute=0)
    recollected = day.replace(hour=14, minute=30)
    events = (
        screen_row("e1", hour_start, {"code": 60.0}, collected_at=first_seen),
        screen_row("e2", hour_start, {"code": 90.0}, collected_at=recollected),
    )
    assert since_counts(events, previous, as_of)["code"] == pytest.approx(1.5)


def test_old_dated_row_collected_between_cards_counts_on_neither() -> None:
    # A push dated before the earlier card's floor but first collected
    # after it sits in no since line: outside the later card's interval,
    # and outside the one after that too.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    third = day.replace(hour=18, minute=0)
    events = (
        stamped_push(
            "p-late",
            day.replace(hour=12, minute=0),
            day.replace(hour=14, minute=0),
        ),
    )
    assert since_counts(events, previous, as_of)["pushes"] == 0.0
    assert since_counts(events, as_of, third)["pushes"] == 0.0


def test_first_card_late_batch_counts_plain_two() -> None:
    # First card shape: as_of 13:05, so the earlier instant is 13:05 the
    # day before and the floored interval is [day-1 13:00, day 13:00).
    # Two pushes dated inside it count; 15 older pushes and pull requests,
    # dated days earlier but first collected a few hours after the bound,
    # count on no card: the count is 2, and the line reads 2.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    as_of = day.replace(hour=13, minute=5)
    previous = as_of - timedelta(hours=24)
    collected_late = previous + timedelta(hours=3)
    old_moment = datetime(2026, 10, 30, 12, 0, tzinfo=MADRID)
    olds: list[Event] = []
    for index in range(15):
        moment = old_moment + timedelta(minutes=index)
        if index % 3 == 2:
            olds.append(stamped_pr(f"r-old-{index}", moment, collected_late))
        else:
            olds.append(stamped_push(f"p-old-{index}", moment, collected_late))
    recents = (
        stamped_push(
            "p-new-1",
            day.replace(hour=12, minute=0),
            day.replace(hour=12, minute=1),
        ),
        stamped_push(
            "p-new-2",
            day.replace(hour=12, minute=30),
            day.replace(hour=12, minute=31),
        ),
    )
    events = (*olds, *recents)
    counts = since_counts(events, previous, as_of)
    assert counts["pushes"] == 2.0
    assert since_line(day.replace(hour=13, minute=30), counts, first=True) == (
        "First card, last 24h: 2 pushes + PRs."
    )


def test_late_screen_batch_counts_only_hours_at_or_after_floor() -> None:
    # Two code hours dated before the last card and three after it, all
    # first collected at 13:00 the next day: the plain count reads the 1.5
    # dated inside the interval, not the 3.5 a difference of totals read.
    prev_day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = prev_day.replace(hour=15, minute=30)
    collected = datetime(2026, 11, 3, 13, 0, tzinfo=MADRID)
    as_of = datetime(2026, 11, 3, 15, 30, tzinfo=MADRID)
    events = (
        screen_row(
            "h-early-1",
            prev_day.replace(hour=13, minute=0),
            {"code": 60.0},
            collected_at=collected,
        ),
        screen_row(
            "h-early-2",
            prev_day.replace(hour=14, minute=0),
            {"code": 60.0},
            collected_at=collected,
        ),
        screen_row(
            "h-late-1",
            collected.replace(hour=10, minute=0),
            {"code": 30.0},
            collected_at=collected,
        ),
        screen_row(
            "h-late-2",
            collected.replace(hour=11, minute=0),
            {"code": 30.0},
            collected_at=collected,
        ),
        screen_row(
            "h-late-3",
            collected.replace(hour=12, minute=0),
            {"code": 30.0},
            collected_at=collected,
        ),
    )
    assert since_counts(events, previous, as_of)["code"] == pytest.approx(1.5)


def test_since_counts_boundary_push_counts_once_across_two_cards() -> None:
    # The pinned formula keeps rows with W0 <= time < t, so a push stamped
    # exactly at the previous card counts once, in the later card.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    first = day.replace(hour=13, minute=30)
    second = day.replace(hour=15, minute=30)
    third = day.replace(hour=18, minute=0)
    events = (push_row("p1", second),)
    assert since_counts(events, first, second)["pushes"] == 0.0
    assert since_counts(events, second, third)["pushes"] == 1.0


def test_since_counts_sign_beats_naive_snapshot_difference() -> None:
    from framework.glimmer.metrics import (
        WINDOW,
        build_metric_snapshot,
        select_winners,
    )

    def snapshot_total(moment: datetime) -> float:
        rows = [
            event
            for event in events
            if moment - WINDOW <= event.time < moment and event.collected_at <= moment
        ]
        return build_metric_snapshot(moment, select_winners(rows)).values.get(
            "screen_hours.code", 0.0
        )

    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    old_time = previous - WINDOW + timedelta(hours=1)
    old = screen_row("e-old", old_time, {"code": 120.0}, collected_at=old_time)
    new_time = previous + timedelta(minutes=30)
    new = screen_row("e-new", new_time, {"code": 30.0}, collected_at=new_time)
    events = (old, new)
    assert since_counts(events, previous, as_of)["code"] == pytest.approx(0.5)
    assert snapshot_total(as_of) - snapshot_total(previous) < 0


def stamped_push(eid: str, moment: datetime, collected: datetime) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "github",
            "type": "github.push",
            "time": moment.isoformat(),
            "source_id": f"push-{eid}",
            "data": {
                "type": "github.push",
                "repo": "madeup/repo",
                "counts": {"commits": 1},
            },
            "tier": "public",
            "collected_at": collected.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def stamped_pr(
    eid: str, moment: datetime, collected: datetime, opened: int = 1
) -> Event:
    return Event.model_validate(
        {
            "id": eid,
            "subject_id": "subject-a",
            "source": "github",
            "type": "github.pr",
            "time": moment.isoformat(),
            "source_id": f"pr-{eid}",
            "data": {
                "type": "github.pr",
                "repo": "madeup/repo",
                "counts": {"opened": opened},
            },
            "tier": "public",
            "collected_at": collected.isoformat(),
            "collector_version": "synthetic@0.1.0",
        }
    )


def test_three_cards_each_push_counts_on_exactly_one_card() -> None:
    # Slots 13:30, 15:30, 18:00 with the 25-minute lead: as_of 13:05,
    # 15:05, 17:35, floors 13:00, 15:00, 17:00.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    first = day.replace(hour=13, minute=5)
    second = day.replace(hour=15, minute=5)
    third = day.replace(hour=17, minute=35)
    events = (
        # In the first card's open hour [13:00, 13:05).
        stamped_push(
            "p-open-1",
            day.replace(hour=13, minute=2),
            day.replace(hour=13, minute=3),
        ),
        # Between the first and second cards.
        stamped_push(
            "p-mid", day.replace(hour=14, minute=0), day.replace(hour=14, minute=1)
        ),
        # In the second card's open hour [15:00, 15:05).
        stamped_push(
            "p-open-2",
            day.replace(hour=15, minute=2),
            day.replace(hour=15, minute=3),
        ),
        # Stamped before the first floor, collected after the first card.
        stamped_push(
            "p-late",
            day.replace(hour=12, minute=30),
            day.replace(hour=13, minute=10),
        ),
    )
    first_card = since_counts(events, first - timedelta(hours=24), first)["pushes"]
    second_card = since_counts(events, first, second)["pushes"]
    third_card = since_counts(events, second, third)["pushes"]
    # p-late is dated 12:30, before the first floor 13:00, so it counts on
    # no card: the second card reads the two dated inside its interval.
    assert first_card == 0.0
    assert second_card == 2.0
    assert third_card == 1.0


def test_recollected_open_hour_counts_whole_on_second_card() -> None:
    # The 13:00 hour is still open at the 13:30 card (floor 13:00), so the
    # first card counts nothing and the second counts the whole hour.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    hour_start = day.replace(hour=13, minute=0)
    events = (
        screen_row("g1", hour_start, {"code": 5.0}, collected_at=hour_start),
        screen_row(
            "g2",
            hour_start,
            {"code": 60.0},
            collected_at=day.replace(hour=14, minute=0),
        ),
    )
    assert since_counts(events, previous - timedelta(hours=24), previous)["code"] == (
        pytest.approx(0.0)
    )
    assert since_counts(events, previous, as_of)["code"] == pytest.approx(1.0)


def test_since_counts_ignore_system_and_other() -> None:
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    moment = day.replace(hour=14, minute=0)
    events = (screen_row("e1", moment, {"system": 60.0, "other": 30.0, "code": 60.0}),)
    counts = since_counts(events, previous, as_of)
    assert "system" not in counts
    assert "other" not in counts
    assert counts["code"] == pytest.approx(1.0)


# -- chart --


def period_moment(as_of: datetime, period: int, hour: int = 12) -> datetime:
    return (as_of - timedelta(hours=60 - 24 * period)).replace(hour=hour, minute=0)


def test_chart_pushes_plus_prs_as_one_series() -> None:
    as_of = slot_at("18:00")
    events = (
        push_row("p1", period_moment(as_of, 0)),
        push_row("p2", period_moment(as_of, 1)),
        push_row("p3", period_moment(as_of, 1)),
        pr_row("r1", period_moment(as_of, 2)),
        screen_row("s1", period_moment(as_of, 2), {"code": 60.0}),
    )
    data = build_chart_data(events, as_of, ())
    assert data.pushes is not None
    assert data.pushes.label == "pushes + PRs"
    assert (data.pushes.earlier, data.pushes.prior, data.pushes.last) == (
        1.0,
        2.0,
        1.0,
    )
    assert "pushes + PRs" not in data.missing


def test_chart_leaves_system_and_other_off() -> None:
    as_of = slot_at("18:00")
    events = (
        screen_row(
            "s1", period_moment(as_of, 2), {"system": 60.0, "other": 30.0, "code": 60.0}
        ),
    )
    data = build_chart_data(events, as_of, ())
    assert [series.label for series in data.screen] == ["code"]


def test_chart_missing_draws_no_data_and_true_zero_keeps_panel() -> None:
    as_of = slot_at("18:00")
    missing = minimal_chart_data()
    assert missing.screen == ()
    assert missing.pushes is None
    assert missing.missing == ("screen", "pushes + PRs")
    assert render_chart_png(missing)
    zeroed = build_chart_data(
        (screen_row("s1", period_moment(as_of, 0), {"code": 60.0}),),
        as_of,
        (),
    )
    code = next(series for series in zeroed.screen if series.label == "code")
    assert code.last == 0.0
    assert "screen" not in zeroed.missing
    assert render_chart_png(zeroed)


def test_push_only_in_open_hour_is_no_data_on_this_card() -> None:
    # A 15:30 slot reads as_of 15:05; a push at 15:02 sits past the 15:00
    # floored window end, so this card has no pushes series.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    as_of = day.replace(hour=15, minute=5)
    events = (
        stamped_push(
            "p-open", day.replace(hour=15, minute=2), day.replace(hour=15, minute=3)
        ),
    )
    data = build_chart_data(events, as_of, ())
    assert data.pushes is None
    assert "pushes + PRs" in data.missing
    assert render_chart_png(data)


def test_screen_row_only_in_open_hour_leaves_window_without_screen() -> None:
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    as_of = day.replace(hour=15, minute=5)
    events = (
        screen_row(
            "s-open",
            day.replace(hour=15, minute=0),
            {"code": 30.0},
            collected_at=day.replace(hour=15, minute=3),
        ),
    )
    data = build_chart_data(events, as_of, ())
    assert data.screen == ()
    assert "screen" in data.missing


def test_recollected_hour_that_shrinks_counts_latest_version() -> None:
    # The 16:00 hour sits inside the card's interval, and the later poll
    # revises it down from 90 to 60 minutes. The card counts the latest
    # version collected by it, 1.0: no clamp is involved any more.
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=15, minute=30)
    as_of = day.replace(hour=18, minute=0)
    hour_start = day.replace(hour=16, minute=0)
    events = (
        screen_row(
            "h1",
            hour_start,
            {"code": 90.0},
            collected_at=day.replace(hour=16, minute=30),
        ),
        screen_row(
            "h2",
            hour_start,
            {"code": 60.0},
            collected_at=day.replace(hour=17, minute=0),
        ),
    )
    assert since_counts(events, previous, as_of)["code"] == pytest.approx(1.0)


def test_unopened_pull_request_counts_nothing() -> None:
    day = datetime(2026, 11, 2, tzinfo=MADRID)
    previous = day.replace(hour=13, minute=30)
    as_of = day.replace(hour=15, minute=30)
    moment = day.replace(hour=14, minute=0)
    events = (pr_row("r-closed", moment, opened=0),)
    assert since_counts(events, previous, as_of)["pushes"] == 0.0


def test_chart_single_period_without_screen_rows_marks_that_period() -> None:
    as_of = slot_at("18:00")
    events = (
        screen_row("s1", period_moment(as_of, 2), {"code": 60.0}),
        push_row("p1", period_moment(as_of, 2)),
    )
    data = build_chart_data(events, as_of, ())
    assert "screen earlier" in data.missing
    assert "screen prior" in data.missing
    assert "screen last" not in data.missing
    assert render_chart_png(data)


def test_chart_tally_comes_through() -> None:
    from framework.telegram.models import TallyItem

    tally = (TallyItem(label="Builder", count=2),)
    data = build_chart_data((), slot_at("18:00"), tally)
    assert data.tally == tally
    assert minimal_chart_data(tally).tally == tally
    assert isinstance(data, ChartData)


def test_tally_leaves_sample_and_unknown_cards_out() -> None:
    slot = slot_at("18:00")
    rows = (
        SlotCardRow(
            card_id="card-known",
            letter="A",
            slot=slot,
            subject_id="subject-a",
            as_of=slot,
            bucket="evening",
            profile_id="builder",
            commitment_id="b-1",
            kind="proposal",
            policy_pick="b-1",
            policy_alternative=None,
        ),
    )
    moment = slot + timedelta(minutes=5)
    tally = build_tally(
        (
            tap("t1", "card-known", "A", moment),
            tap("t2", "card-unknown", "A", moment),
            tap("t3", "card-known", "wrong", moment),
        ),
        rows,
    )
    assert {item.label: item.count for item in tally}["Builder"] == 1


def test_card_build_module_surface() -> None:
    assert card_build.CATEGORIES == ("code", "ai", "comms", "feed", "browse", "media")


def test_statements_cap_three_with_overall_first() -> None:
    """Five claims with overall_state last still open with its first claim."""
    from framework.briefing.schemas import Briefing

    slot = slot_at("15:30")
    start = slot.replace(hour=16, minute=0)
    end = slot.replace(hour=17, minute=0)
    texts = [f"Claim {name} here." for name in ("w1", "n1", "o1", "o2", "w2")]
    sections = [
        {
            "type": "working",
            "claims": [
                {"id": "c-w1", "text": texts[0], "fact_ids": []},
                {"id": "c-w2", "text": texts[4], "fact_ids": []},
            ],
        },
        {
            "type": "not_working",
            "claims": [{"id": "c-n1", "text": texts[1], "fact_ids": []}],
        },
        {
            "type": "overall_state",
            "claims": [
                {"id": "c-o1", "text": texts[2], "fact_ids": []},
                {"id": "c-o2", "text": texts[3], "fact_ids": []},
            ],
        },
        {
            "type": "actions",
            "claims": [],
            "actions": [
                {
                    "id": "act-1",
                    "commitment_id": "b-1",
                    "kind": "build",
                    "text": "Model action wording",
                    "dimension": "love",
                    "proposed_start": start.isoformat(),
                    "proposed_end": end.isoformat(),
                }
            ],
        },
    ]
    loaded = Briefing.model_validate(
        {
            "id": "brf-b-1",
            "profile_id": "builder",
            "subject_id": "subject-a",
            "slot": slot.isoformat(),
            "sections": sections,
        }
    )
    pieces = build_statements([("A", "Builder", loaded)])
    assert pieces[0] == "A · Builder"
    assert pieces[1:] == (texts[2], texts[0], texts[4])
