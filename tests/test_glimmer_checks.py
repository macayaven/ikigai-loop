"""Ticket 9: one test per drop code, family binding, leak scope, overlap edge."""

import inspect
from datetime import datetime

from evals.glimmer_cases import (
    AS_OF,
    PLUS1,
    SUBJECT_ID,
    WINDOW_START,
    _dt,
    cal_event,
    feed_aliases,
    feed_batch,
    feed_event,
    personal_batch,
    pr_event,
    push_event,
    screen_event,
)
from evals.glimmer_cases import RecordingLLM as CaseLLM
from framework.glimmer.checks import (
    _family_match,
    check_fact,
    highest_tier,
    resolve_aliases,
)
from framework.glimmer.facts import extract_facts
from framework.glimmer.metrics import build_metric_snapshot, select_winners
from framework.schemas.events import Event


def _run(
    statement: str,
    evidence: list[str],
    events: list[Event],
    feed_extra_titles: tuple[str, ...] = (),
) -> str | None:
    winners = select_winners(events)
    winning_ids = frozenset(e.id for e in winners)
    snapshot = build_metric_snapshot(AS_OF, winners)
    titles = [e.data.title for e in events if e.type == "feed.item"]  # type: ignore[union-attr]
    return check_fact(
        statement,
        evidence,
        known_by_id={e.id: e for e in events},
        winning_ids=winning_ids,
        winners=list(winners),
        snapshot=snapshot,
        feed_titles=[*titles, *feed_extra_titles],
        as_of=AS_OF,
        window_start=WINDOW_START,
    )


def test_resolve_aliases_unknown_returns_none() -> None:
    assert resolve_aliases(["e1", "e99"], {"e1": "evt_a"}) is None
    assert resolve_aliases(["e1"], {"e1": "evt_a"}) == ("evt_a",)


def test_evidence_unknown_for_missing_and_superseded_ids() -> None:
    push = push_event(eid="evt_c1", time=_dt(30, 14))
    assert (
        _run("Push activity continued in the last period", ["evt_missing"], [push])
        == "FACT_EVIDENCE_UNKNOWN"
    )
    old = screen_event(
        eid="evt_c1_old",
        time=_dt(30, 18),
        minutes={"Programming": 60.0},
        digest="aaa111",
        collected_at=_dt(30, 19),
    )
    new = screen_event(
        eid="evt_c1_new",
        time=_dt(30, 18),
        minutes={"Programming": 120.0},
        digest="bbb222",
        collected_at=_dt(30, 20),
    )
    assert (
        _run(
            "Programming screen time totalled 2 hours in the last period",
            [old.id],
            [old, new],
        )
        == "FACT_EVIDENCE_UNKNOWN"
    )


def test_evidence_out_of_window_defensive() -> None:
    stale = push_event(eid="evt_c2", time=_dt(27, 10))
    assert (
        _run("Archived push from last week", [stale.id], [stale])
        == "FACT_EVIDENCE_OUT_OF_WINDOW"
    )


def test_alias_in_statement_before_number_check() -> None:
    pushes = [push_event(eid=f"evt_c3_{i}", time=_dt(30, 14, i)) for i in range(7)]
    ids = [e.id for e in pushes]
    # 7 matches the cited count, yet the alias fires first.
    assert _run("Event e7 happened", ids, pushes) == "FACT_ALIAS_IN_STATEMENT"
    assert _run("Event f1 happened", ids, pushes) == "FACT_ALIAS_IN_STATEMENT"


def test_number_unbacked_and_family_binding() -> None:
    screen = screen_event(
        eid="evt_c4_screen", time=_dt(30, 18), minutes={"Programming": 270.0}
    )
    push1 = push_event(eid="evt_c4_p1", time=_dt(30, 14))
    push2 = push_event(eid="evt_c4_p2", time=_dt(30, 15))
    events = [screen, push1, push2]
    assert (
        _run(
            "Focused push session lasted 4.5 hours",
            [push1.id, push2.id],
            events,
        )
        == "FACT_NUMBER_UNBACKED"
    )
    # Same number with a cited row of the right family passes.
    assert (
        _run(
            "Programming screen time totalled 4.5 hours in the last period",
            [e.id for e in events],
            events,
        )
        is None
    )


def test_period_tightened_backing_pass_and_wrong_period_fail() -> None:
    prior_row = screen_event(
        eid="evt_c5_prior", time=_dt(29, 18), minutes={"Programming": 405.0}
    )
    last_row = screen_event(
        eid="evt_c5_last", time=_dt(30, 18), minutes={"Programming": 120.0}
    )
    stmt = (
        "Work/Programming screen hours fell from 6.75 in the prior period "
        "to 2.0 in the last period"
    )
    assert _run(stmt, [prior_row.id, last_row.id], [prior_row, last_row]) is None
    assert _run(stmt, [last_row.id], [prior_row, last_row]) == "FACT_NUMBER_UNBACKED"


def test_zero_period_value_backed_by_family_row_in_any_period() -> None:
    last_push = push_event(eid="evt_c6_push", time=_dt(30, 14))
    # No prior push exists, so period.prior.pushes is 0; the zero token
    # is backed by a cited family row in any period. (0 matches no
    # non-period key here: busy/feed zeroes need other families.)
    assert (
        _run(
            "Prior period push count sits at 0 today",
            [last_push.id],
            [last_push],
        )
        is None
    )


def test_private_text_leak_and_dropped_text_ignored() -> None:
    push = push_event(
        eid="evt_c7_push",
        time=_dt(30, 14),
        repo="Synthetic   Garden-Repo",
        tier="private",
    )
    assert (
        _run(
            "Deploys to Synthetic garden-repo went smoothly",
            [push.id],
            [push],
        )
        == "FACT_PRIVATE_TEXT_LEAK"
    )
    # The same wording from a public row is not a leak.
    public = push_event(
        eid="evt_c7_pub", time=_dt(30, 15), repo="Synthetic   Garden-Repo"
    )
    assert (
        _run(
            "Deploys to Synthetic garden-repo went smoothly",
            [public.id],
            [public],
        )
        is None
    )


def test_calendar_category_and_tags_exempt_from_leak() -> None:
    block = cal_event(
        eid="evt_c8_cal",
        key="leak-8@20261030T100000",
        lm="seq1",
        time=_dt(30, 10),
        end=_dt(30, 12),
        tags=("iki-focus",),
    )
    assert (
        _run(
            "Personal focus blocks with iki-focus tags ran 2 hours",
            [block.id],
            [block],
        )
        is None
    )


def test_prior_row_does_not_back_last_period_tag_value() -> None:
    prior_only = cal_event(
        eid="evt_ov_prior",
        key="ov-a@20261029T140000",
        lm="seq1",
        time=_dt(29, 14),
        end=_dt(29, 17),
        tags=("iki-x",),
    )
    overlapping = cal_event(
        eid="evt_ov_span",
        key="ov-b@20261030T120000",
        lm="seq1",
        time=_dt(30, 12),
        end=_dt(30, 15),
        tags=("iki-x",),
    )
    events = [prior_only, overlapping]
    statement = "Iki-x focus ran 2 hours in the last period"
    assert _run(statement, [prior_only.id], events) == "FACT_NUMBER_UNBACKED"
    assert _run(statement, [overlapping.id], events) is None


def test_rounding_is_half_up_to_token_places() -> None:
    quarter = screen_event(
        eid="evt_rnd_q", time=_dt(30, 14), minutes={"Programming": 75.0}
    )
    assert (
        _run(
            "Programming ran 1.3 hours in the last period",
            [quarter.id],
            [quarter],
        )
        is None
    )
    assert (
        _run(
            "Programming ran 1.2 hours in the last period",
            [quarter.id],
            [quarter],
        )
        == "FACT_NUMBER_UNBACKED"
    )
    half = screen_event(
        eid="evt_rnd_h", time=_dt(30, 15), minutes={"Programming": 150.0}
    )
    assert (
        _run(
            "Programming ran 3 hours in the last period",
            [half.id],
            [half],
        )
        is None
    )
    assert (
        _run(
            "Programming ran 2 hours in the last period",
            [half.id],
            [half],
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_cited_repo_digits_are_not_numbers() -> None:
    pushes = [
        push_event(
            eid=f"evt_repo_{i}",
            time=_dt(28, 14 + i),
            repo="example-user/tools-v2",
        )
        for i in range(3)
    ]
    pushes.append(
        push_event(
            eid="evt_repo_prior",
            time=_dt(29, 14),
            repo="example-user/tools-v2",
        )
    )
    ids = [e.id for e in pushes]
    assert (
        _run(
            "Pushes to example-user/tools-v2 fell from 3 in earlier to 1 in prior.",
            ids,
            pushes,
        )
        is None
    )
    assert (
        _run(
            "Pushes to example-user/tools-v9 fell from 3 in earlier to 1 in prior.",
            ids,
            pushes,
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_absurd_precision_token_is_not_backed() -> None:
    screen = screen_event(
        eid="evt_host_prec", time=_dt(30, 18), minutes={"Programming": 120.0}
    )
    assert (
        _run(
            "Programming screen time totalled "
            "1.123456789012345678901234567890 hours in the last period",
            [screen.id],
            [screen],
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_non_ascii_headline_overlap_drops() -> None:
    push = push_event(eid="evt_host_push", time=_dt(30, 14))
    cyrillic = feed_event(
        eid="evt_host_cyr",
        item="item-cyr",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Синтетический нейронный садовый робот контроль",
    )
    assert (
        _run(
            "Синтетический нейронный садовый робот контроль",
            [push.id],
            [push, cyrillic],
        )
        == "FACT_FEED_HEADLINE_OVERLAP"
    )
    accented = feed_event(
        eid="evt_host_acc",
        item="item-acc",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Café naïve façade résumé über alles",
    )
    assert (
        _run(
            "Notes on café naïve façade résumé über",
            [push.id],
            [push, accented],
        )
        == "FACT_FEED_HEADLINE_OVERLAP"
    )
    short = feed_event(
        eid="evt_host_short",
        item="item-short",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Café naïve façade résumé",
    )
    assert (
        _run(
            "Notes on café naïve façade résumé",
            [push.id],
            [push, short],
        )
        is None
    )


def test_feed_headline_overlap_5_words_and_4_words_pass() -> None:
    item = feed_event(
        eid="evt_c9_feed",
        item="item-c9",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Synthetic neural garden robot control systems",
    )
    push = push_event(eid="evt_c9_push", time=_dt(30, 14))
    events = [item, push]
    assert (
        _run(
            "Neural garden robot control systems advanced this week",
            [push.id],
            events,
        )
        == "FACT_FEED_HEADLINE_OVERLAP"
    )
    assert (
        _run(
            "Garden robot control systems advanced this week now",
            [push.id],
            events,
        )
        is None
    )


def test_period_tag_hours_requires_overlap_not_start() -> None:
    # Block starts in the prior period but extends into last; a statement
    # about last-period tag hours citing it is backed by overlap. The 0.5
    # token matches no cited count, so only the period key backs it.
    block = cal_event(
        eid="evt_c10_block",
        key="span-10@20261030T100000",
        lm="seq1",
        time=_dt(30, 10),
        end=datetime(2026, 10, 30, 13, 30, tzinfo=PLUS1),
        tags=("iki-span",),
    )
    events = [block]
    assert (
        _run(
            "Iki-span focus ran 0.5 hours in the last period",
            [block.id],
            events,
        )
        is None
    )
    # A token no key holds still drops, whatever the prose claims.
    assert (
        _run(
            "Iki-span focus ran 2 hours in the earlier period",
            [block.id],
            events,
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_cancelled_row_backs_only_cancelled_keys() -> None:
    good = cal_event(
        eid="evt_c11_good",
        key="trip-11@20261029T150000",
        lm="seq1",
        time=_dt(29, 15),
        end=_dt(29, 17),
        tags=("iki-trip",),
    )
    cancelled = cal_event(
        eid="evt_c11_cancelled",
        key="trip-11b@20261029T180000",
        lm="seq1",
        time=_dt(29, 18),
        end=_dt(29, 19),
        tags=("iki-trip",),
        cancelled=True,
    )
    events = [good, cancelled]
    # tag_hours.iki-trip is 2.0, but the only cited row is cancelled:
    # under the fix it backs no tag_hours key (and no busy key either).
    assert (
        _run(
            "Iki-trip focus ran 2 hours in the prior period",
            [cancelled.id],
            events,
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_cancelled_period_uses_row_start_time() -> None:
    # Row A starts in prior but ends in last; the rollup counts cancelled
    # blocks by start time, and the check must agree with it.
    crossing = cal_event(
        eid="evt_c11b_cross",
        key="trip-11c@20261030T123000",
        lm="seq1",
        time=_dt(30, 12, 30),
        end=_dt(30, 13, 30),
        tags=("iki-trip",),
        cancelled=True,
    )
    late = cal_event(
        eid="evt_c11b_late",
        key="trip-11d@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 15),
        tags=("iki-trip",),
        cancelled=True,
    )
    events = [crossing, late]
    # Digit 1 matches no cited count (2 rows of one type), so only
    # the period.cancelled key can back it, and only by start-time
    # assignment: the crossing row starts in prior but ends in last.
    assert (
        _run(
            "1 iki-trip block was cancelled in the prior period",
            [crossing.id, late.id],
            events,
        )
        is None
    )


def test_family_match_has_single_screen_hours_branch() -> None:
    source = inspect.getsource(_family_match)
    assert source.count('startswith("screen_hours.")') == 1


def test_highest_tier_ordering() -> None:
    public = push_event(eid="evt_c12_pub", time=_dt(30, 14))
    private = push_event(
        eid="evt_c12_priv", time=_dt(30, 15), tier="private", repo="synthetic/other"
    )
    assert highest_tier([public, private]) == "private"
    assert highest_tier([public]) == "public"
    assert highest_tier([]) == "public"


def test_feed_topic_shape_too_many_words() -> None:
    item = feed_event(
        eid="evt_c13_feed",
        item="item-c13",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    words = "alpha beta gamma delta epsilon zeta eta"
    assert len(words.split()) == 7
    llm = CaseLLM(feed=(feed_batch({"evidence": ["f1"], "topic": words}),))
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    assert [d.code for d in result.dropped] == ["FACT_FEED_TOPIC_SHAPE"]
    assert result.facts == ()


def test_calendar_block_count_needs_snapshot_backing() -> None:
    first = cal_event(
        eid="evt_fam_1",
        key="fam-a@20261030T100000",
        lm="seq1",
        time=_dt(30, 10),
        end=_dt(30, 11),
        tags=("iki-a",),
        busy=False,
    )
    second = cal_event(
        eid="evt_fam_2",
        key="fam-b@20261030T110000",
        lm="seq1",
        time=_dt(30, 11),
        end=_dt(30, 12),
        tags=("iki-b",),
        busy=False,
    )
    third = cal_event(
        eid="evt_fam_3",
        key="fam-c@20261030T120000",
        lm="seq1",
        time=_dt(30, 12),
        end=_dt(30, 13),
        tags=("iki-c",),
        busy=False,
        kind="updated",
    )
    push = push_event(eid="evt_fam_push", time=_dt(30, 14))
    events = [first, second, third, push]
    # No snapshot metric counts calendar blocks, so the 3 drops now that
    # cited-row counts only back numbers for feed citations.
    assert (
        _run(
            "3 calendar blocks and 1 push in the last period",
            [e.id for e in events],
            events,
        )
        == "FACT_NUMBER_UNBACKED"
    )
    assert (
        _run(
            "1 push in the last period",
            [push.id],
            events,
        )
        is None
    )


def test_feed_topic_shape_number_token() -> None:
    items = [
        feed_event(
            eid=f"evt_c14_{i}",
            item=f"item-c14-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    feeds = feed_aliases(tuple(items))
    llm = CaseLLM(
        feed=(
            feed_batch(
                {
                    "evidence": [feeds[e.id] for e in items],
                    "topic": "top 3 tricks",
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, items, llm)
    assert [d.code for d in result.dropped] == ["FACT_FEED_TOPIC_SHAPE"]
    assert result.facts == ()


def _zero_period_table() -> dict[str, Event]:
    """Media 0 in prior / 4.0 in last; Work non-zero everywhere; iki-deep
    3.0 in prior / 0 in last; one cancelled iki-deep and one PR in prior."""
    earlier = screen_event(
        eid="evt_z_earlier",
        time=_dt(28, 14),
        minutes={"Work/Programming": 60.0, "Media/Video": 30.0},
    )
    prior_screen = screen_event(
        eid="evt_z_prior", time=_dt(29, 14), minutes={"Work/Programming": 60.0}
    )
    last = screen_event(
        eid="evt_z_last",
        time=_dt(30, 14),
        minutes={"Work/Programming": 60.0, "Media/Video": 240.0},
    )
    deep = cal_event(
        eid="evt_z_deep",
        key="deep-z@20261029T150000",
        lm="seq1",
        time=_dt(29, 15),
        end=_dt(29, 18),
        tags=("iki-deep",),
    )
    cancelled = cal_event(
        eid="evt_z_cancelled",
        key="deep-zc@20261029T130000",
        lm="seq1",
        time=_dt(29, 13),
        end=_dt(29, 14),
        tags=("iki-deep",),
        cancelled=True,
    )
    pr = pr_event(eid="evt_z_pr", time=_dt(29, 16))
    events = [earlier, prior_screen, last, deep, cancelled, pr]
    return {e.id: e for e in events}


def test_zero_screen_value_kept_with_family_row_in_last() -> None:
    table = _zero_period_table()
    last = table["evt_z_last"]
    for statement in (
        "Media/Video screen hours rose from 0 in prior to 4.0 in last.",
        "Media/Video screen hours rose from 0.0 in prior to 4.0 in last.",
        "Media/Video went from 0 hours in prior to 4 hours in last.",
    ):
        assert _run(statement, [last.id], list(table.values())) is None, statement


def test_zero_tag_value_kept_with_family_row_in_prior() -> None:
    table = _zero_period_table()
    assert (
        _run(
            "iki-deep calendar hours fell from 3.0 in prior to 0 in last.",
            [table["evt_z_deep"].id],
            list(table.values()),
        )
        is None
    )


def test_zero_cancelled_value_kept_with_family_row() -> None:
    table = _zero_period_table()
    cancelled = table["evt_z_cancelled"]
    assert (
        _run(
            "Cancelled iki-deep blocks rose from 0 in earlier to 1 in prior.",
            [cancelled.id],
            list(table.values()),
        )
        is None
    )
    assert (
        _run(
            "Cancelled iki-deep blocks fell from 1 in prior to 0 in last.",
            [cancelled.id],
            list(table.values()),
        )
        is None
    )


def test_zero_pr_value_kept_with_family_row() -> None:
    table = _zero_period_table()
    assert (
        _run(
            "Github PRs rose from 0 in earlier to 1 in prior.",
            [table["evt_z_pr"].id],
            list(table.values()),
        )
        is None
    )


def test_zero_token_without_absent_or_zero_family_key_drops() -> None:
    table = _zero_period_table()
    # Work/Programming is non-zero in every period, so neither token backs.
    assert (
        _run(
            "Work/Programming fell from 7.0 in earlier to 0 in last.",
            [table["evt_z_prior"].id],
            list(table.values()),
        )
        == "FACT_NUMBER_UNBACKED"
    )
    # A zero PR token citing only a screen row has no PR family behind it.
    assert (
        _run(
            "PRs were 0 in last.",
            [table["evt_z_prior"].id],
            list(table.values()),
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_cited_repo_spelled_number_is_masked() -> None:
    tower = push_event(
        eid="evt_repo7_tower", time=_dt(30, 14), repo="example-user/seven-tower"
    )
    tower_ids = [tower.id]
    tower_events = [tower]
    assert (
        _run(
            "Pushes to example-user/seven-tower happened in last.",
            tower_ids,
            tower_events,
        )
        is None
    )
    assert (
        _run(
            "Pushes went to example-user/seven-tower.",
            tower_ids,
            tower_events,
        )
        is None
    )
    assert (
        _run(
            "Pushes to seven-tower happened in last.",
            tower_ids,
            tower_events,
        )
        is None
    )
    assert (
        _run(
            "Pushes to Example-User/Seven-Tower happened in last.",
            tower_ids,
            tower_events,
        )
        is None
    )
    assert (
        _run(
            "Seven pushes to example-user/seven-tower happened in last.",
            tower_ids,
            tower_events,
        )
        == "FACT_NUMBER_UNBACKED"
    )
    assert (
        _run(
            "Pushes to other-user/seven-tower happened in last.",
            tower_ids,
            tower_events,
        )
        == "FACT_NUMBER_UNBACKED"
    )
    bare = push_event(eid="evt_repo7_bare", time=_dt(30, 14), repo="example-user/seven")
    bare_ids = [bare.id]
    bare_events = [bare]
    assert (
        _run(
            "Pushes to example-user/seven happened in last.",
            bare_ids,
            bare_events,
        )
        is None
    )
    assert (
        _run(
            "Seven pushes to example-user/seven happened in last.",
            bare_ids,
            bare_events,
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_bare_repo_segment_with_digit_is_known_id() -> None:
    push = push_event(
        eid="evt_mask_toolsv2", time=_dt(30, 14), repo="example-user/toolsv2"
    )
    assert (
        _run(
            "Pushes to toolsv2 happened in last.",
            [push.id],
            [push],
        )
        is None
    )


def test_numeric_repo_segment_is_not_a_name() -> None:
    push = push_event(eid="evt_mask_314", time=_dt(30, 14), repo="example-user/3.14")
    assert (
        _run(
            "Pushes were 3.14 in last.",
            [push.id],
            [push],
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_headline_overlap_reads_unmasked_statement() -> None:
    push = push_event(
        eid="evt_mask_overlap",
        time=_dt(30, 14),
        repo="example-user/seven-tower",
    )
    assert (
        _run(
            "Pushes to example-user/seven-tower ships a new release.",
            [push.id],
            [push],
            feed_extra_titles=("example-user/seven-tower ships a new release",),
        )
        == "FACT_FEED_HEADLINE_OVERLAP"
    )


def test_private_repo_name_still_leaks() -> None:
    push = push_event(
        eid="evt_repo7_priv",
        time=_dt(30, 14),
        repo="example-user/seven-tower",
        tier="private",
    )
    assert (
        _run(
            "Pushes to example-user/seven-tower happened in last.",
            [push.id],
            [push],
        )
        == "FACT_PRIVATE_TEXT_LEAK"
    )


def test_spelled_numbers_backed_by_snapshot_count() -> None:
    pushes = [push_event(eid=f"evt_sp_{i}", time=_dt(30, 14, i)) for i in range(2)]
    ids = [e.id for e in pushes]
    assert _run("Two pushes happened in last.", ids, pushes) is None
    assert _run("Seven pushes happened in last.", ids, pushes) == "FACT_NUMBER_UNBACKED"


def test_feed_topic_shape_spelled_numbers() -> None:
    items = [
        feed_event(
            eid=f"evt_c14s_{i}",
            item=f"item-c14s-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    for topic in ("Two-stage retrieval", "Top ten tricks"):
        feeds = feed_aliases(tuple(items))
        llm = CaseLLM(
            feed=(
                feed_batch(
                    {
                        "evidence": [feeds[e.id] for e in items],
                        "topic": topic,
                    }
                ),
            )
        )
        result = extract_facts(AS_OF, SUBJECT_ID, items, llm)
        assert [d.code for d in result.dropped] == ["FACT_FEED_TOPIC_SHAPE"], topic
        assert result.facts == (), topic
    for topic in ("One-shot learning", "Local inference"):
        feeds = feed_aliases(tuple(items))
        llm = CaseLLM(
            feed=(
                feed_batch(
                    {
                        "evidence": [feeds[e.id] for e in items],
                        "topic": topic,
                    }
                ),
            )
        )
        result = extract_facts(AS_OF, SUBJECT_ID, items, llm)
        assert result.dropped == (), topic
        assert len(result.facts) == 1, topic


def test_personal_batch_without_tier_field_validates() -> None:
    push = push_event(eid="evt_c15_push", time=_dt(30, 14))
    llm = CaseLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Push activity continued in the last period",
                    "evidence": ["e1"],
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert len(result.facts) == 2
    assert result.facts[0].statement == "Pushes rose from 0 in prior to 1 in last."
    assert result.facts[1].tier == "public"


def _c26_screen_rows(first_minutes: float) -> list[Event]:
    """11 screen rows in `last`, each holding Cat/A and Cat/B minutes."""
    return [
        screen_event(
            eid=f"evt_c26_{i}",
            time=_dt(30, 14, i),
            minutes={"Cat/A": first_minutes, "Cat/B": 10.0},
        )
        for i in range(11)
    ]


def test_cited_count_backs_numbers_only_for_feed() -> None:
    rows = _c26_screen_rows(10.0)
    cited = [e.id for e in rows[:4]]
    # Cat/A and Cat/B each total 110 minutes (1.83 hours), so no snapshot
    # value rounds to 4: the 4 is only the cited count, and it must drop.
    # Restoring either old clause (type_counts or len(cited)) keeps it.
    assert (
        _run(
            "In the last period, 4 events included both Cat/A and Cat/B screen time.",
            cited,
            rows,
        )
        == "FACT_NUMBER_UNBACKED"
    )


def test_cited_count_drop_reaches_extract_facts() -> None:
    from evals.glimmer_cases import personal_aliases, personal_batch

    rows = _c26_screen_rows(10.0)
    aliases = personal_aliases(tuple(rows))
    llm = CaseLLM(
        personal=(
            personal_batch(
                {
                    "statement": (
                        "In the last period, 4 events included both Cat/A "
                        "and Cat/B screen time."
                    ),
                    "evidence": [aliases[e.id] for e in rows[:4]],
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, rows, llm)
    assert [d.code for d in result.dropped] == ["FACT_NUMBER_UNBACKED"]
    assert [f.statement for f in result.facts] == [
        "Cat/A screen hours rose from 0 in prior to 1.83 in last."
    ]


def test_feed_cited_count_still_backs_numbers() -> None:
    items = [
        feed_event(
            eid=f"evt_c26f_{i}",
            item=f"item-c26f-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    cited = [e.id for e in items[:2]]
    assert _run("2 feed items about pruning", cited, items) is None
    assert _run("5 feed items about pruning", cited, items) == "FACT_NUMBER_UNBACKED"


def test_feed_topic_count_through_extract_facts() -> None:
    from evals.glimmer_cases import feed_aliases, feed_batch

    items = [
        feed_event(
            eid=f"evt_c26g_{i}",
            item=f"item-c26g-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    feeds = feed_aliases(tuple(items))
    llm = CaseLLM(
        feed=(
            feed_batch(
                {
                    "evidence": [feeds[items[0].id], feeds[items[1].id]],
                    "topic": "pruning",
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, items, llm)
    assert [f.statement for f in result.facts] == ["2 feed items about pruning"]


def test_mixed_feed_and_push_citation_backs_no_count() -> None:
    from evals.glimmer_cases import feed_event as make_feed

    items = [
        make_feed(
            eid=f"evt_c26m_{i}",
            item=f"item-c26m-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    push = push_event(eid="evt_c26m_push", time=_dt(30, 14))
    events = [*items, push]
    # Three feed rows sit in the window on purpose: with only two,
    # feed.item.count == 2 would back the token through the snapshot.
    # Replacing all() with any() below keeps this statement.
    assert (
        _run("2 things happened", [items[0].id, push.id], events)
        == "FACT_NUMBER_UNBACKED"
    )


def test_empty_citation_backs_no_zero() -> None:
    push = push_event(eid="evt_c26z_push", time=_dt(30, 14))
    assert _run("0 things happened", [], [push]) == "FACT_NUMBER_UNBACKED"


def test_snapshot_hours_still_back_a_bare_count() -> None:
    # Known limit: a number has no unit, so 4.03 Cat/A hours back the
    # "4 events" statement. D19 removes only the cited-count source.
    rows = _c26_screen_rows(22.0)
    assert (
        _run(
            "In the last period, 4 events included both Cat/A and Cat/B screen time.",
            [e.id for e in rows[:4]],
            rows,
        )
        is None
    )


def test_model_skipped_screen_is_subset_of_code_skipped() -> None:
    from framework.glimmer.checks import _MODEL_SKIPPED_SCREEN
    from framework.glimmer.code_facts import SCREEN_SKIPPED_CATEGORIES

    assert _MODEL_SKIPPED_SCREEN == frozenset({"system"})
    assert _MODEL_SKIPPED_SCREEN <= SCREEN_SKIPPED_CATEGORIES


def test_model_system_screen_fact_dropped() -> None:
    prior = screen_event(
        eid="evt_sys_prior", time=_dt(29, 18), minutes={"System": 60.0}
    )
    last = screen_event(eid="evt_sys_last", time=_dt(30, 18), minutes={"System": 120.0})
    events = [prior, last]
    assert (
        _run(
            "System screen hours rose from 1 in prior to 2 in last",
            [prior.id, last.id],
            events,
        )
        == "FACT_SCREEN_SYSTEM_CATEGORY"
    )
    code_only = screen_event(
        eid="evt_sys_code", time=_dt(30, 18), minutes={"code": 60.0}
    )
    assert (
        _run("System apps took over my screen", [code_only.id], [code_only])
        == "FACT_SCREEN_SYSTEM_CATEGORY"
    )
    assert (
        _run(
            "Code screen hours rose in last while other categories fell",
            [code_only.id],
            [code_only],
        )
        is None
    )
    items = [
        feed_event(
            eid=f"evt_sysf_{i}",
            item=f"item-sysf-{i}",
            day="2026-10-30",
            time=_dt(30, 9 + i),
            title=title,
        )
        for i, title in enumerate(
            (
                "Synthetic transformer pruning benchmark results",
                "Synthetic container scheduler release notes",
                "Synthetic vector index library update",
            )
        )
    ]
    assert (
        _run(
            "3 feed items about operating system design",
            [e.id for e in items],
            items,
        )
        is None
    )


def _number_binding_pushes() -> tuple[Event, Event, Event]:
    prior_push = push_event(eid="evt_nbp_prior", time=_dt(29, 14))
    last_one = push_event(eid="evt_nbp_last1", time=_dt(30, 14))
    last_two = push_event(eid="evt_nbp_last2", time=_dt(30, 15))
    return prior_push, last_one, last_two


def test_number_bound_to_named_period() -> None:
    prior_push, last_one, last_two = _number_binding_pushes()
    events = [prior_push, last_one, last_two]
    last_ids = [last_one.id, last_two.id]
    assert _run("Pushes were 0 in last", last_ids, events) == "FACT_NUMBER_UNBACKED"
    assert _run("Pushes were 2 in earlier", last_ids, events) == "FACT_NUMBER_UNBACKED"
    prior_screen = screen_event(
        eid="evt_nbp_screen_prior",
        time=_dt(29, 18),
        minutes={"Programming": 405.0},
    )
    last_screen = screen_event(
        eid="evt_nbp_screen_last",
        time=_dt(30, 18),
        minutes={"Programming": 120.0},
    )
    assert (
        _run(
            "Programming screen hours fell from 2 in prior to 6.75 in last",
            [prior_screen.id, last_screen.id],
            [prior_screen, last_screen],
        )
        == "FACT_NUMBER_UNBACKED"
    )
    all_ids = [prior_push.id, last_one.id, last_two.id]
    assert _run("In prior pushes were 1, in last 2", all_ids, events) is None
    assert (
        _run("In prior pushes were 2, in last 2", all_ids, events)
        == "FACT_NUMBER_UNBACKED"
    )
    assert _run("Earlier and last held 0 and 2 pushes", all_ids, events) is None
    assert (
        _run("Earlier and last held 2 and 0 pushes", all_ids, events)
        == "FACT_NUMBER_UNBACKED"
    )
    assert _run("Pushes fell from 2 in last to 1 in prior", all_ids, events) is None
    assert (
        _run("Pushes were 2 in earlier and 2 in last", all_ids, events)
        == "FACT_NUMBER_UNBACKED"
    )
    assert _run("Push count sits at 0 today", [last_one.id], events) is None
    tagged = cal_event(
        eid="evt_nbp_tagged",
        key="nbp-iki-last@20261030T100000",
        lm="seq1",
        time=_dt(30, 10),
        end=_dt(30, 12),
        tags=("iki-last",),
    )
    assert _run("iki-last focus ran 2 hours", [tagged.id], [tagged]) is None
    repo_pushes = [
        push_event(
            eid=f"evt_nbp_repo_{i}",
            time=_dt(30, 14, i),
            repo="synthetic/earlier",
        )
        for i in range(2)
    ]
    assert (
        _run(
            "In synthetic/earlier pushes were 2",
            [e.id for e in repo_pushes],
            repo_pushes,
        )
        is None
    )


def test_code_fact_template_shapes_still_pass() -> None:
    from evals.glimmer_cases import personal_batch as _batch

    scr_prior = screen_event(
        eid="evt_tpl_screen_prior",
        time=_dt(29, 18),
        minutes={"Programming": 405.0},
    )
    scr_last = screen_event(
        eid="evt_tpl_screen_last",
        time=_dt(30, 18),
        minutes={"Programming": 120.0},
    )
    push_one = push_event(eid="evt_tpl_push1", time=_dt(30, 14))
    push_two = push_event(eid="evt_tpl_push2", time=_dt(30, 15))
    opened = pr_event(eid="evt_tpl_pr", time=_dt(30, 16))
    block = cal_event(
        eid="evt_tpl_block",
        key="tpl-focus@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 16),
        tags=("iki-focus",),
    )
    cancelled = cal_event(
        eid="evt_tpl_cancelled",
        key="tpl-x@20261029T150000",
        lm="seq1",
        time=_dt(29, 15),
        end=_dt(29, 16),
        tags=("iki-x",),
        cancelled=True,
    )
    events = [scr_prior, scr_last, push_one, push_two, opened, block, cancelled]
    expected = (
        "Programming screen hours rose from 0 in earlier to 6.75 in prior.",
        "Pushes rose from 0 in prior to 2 in last.",
        "Pull requests rose from 0 in prior to 1 in last.",
        "iki-focus calendar hours rose from 0 in prior to 2 in last.",
        "Cancelled iki-x blocks fell from 1 in prior to 0 in last.",
    )
    llm = CaseLLM(personal=(_batch(),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert [d.code for d in result.dropped] == []
    assert [f.statement for f in result.facts] == list(expected)
    assert result.code_fact_ids == tuple(f.id for f in result.facts)


def test_one_feed_item_singular() -> None:
    from evals.glimmer_cases import feed_aliases as _feed_aliases
    from evals.glimmer_cases import feed_batch as _feed_batch

    item = feed_event(
        eid="evt_sing_one",
        item="item-sing-one",
        day="2026-10-30",
        time=_dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    feeds = _feed_aliases((item,))
    llm = CaseLLM(
        feed=(
            _feed_batch(
                {"evidence": [feeds[item.id]], "topic": "neural pruning tools"}
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    assert [f.statement for f in result.facts] == [
        "1 feed item about neural pruning tools"
    ]
    second = feed_event(
        eid="evt_sing_two",
        item="item-sing-two",
        day="2026-10-30",
        time=_dt(30, 10),
        title="Synthetic container scheduler release notes",
    )
    pair = (item, second)
    pair_feeds = _feed_aliases(pair)
    llm_pair = CaseLLM(
        feed=(
            _feed_batch(
                {
                    "evidence": [pair_feeds[e.id] for e in pair],
                    "topic": "neural pruning tools",
                }
            ),
        )
    )
    pair_result = extract_facts(AS_OF, SUBJECT_ID, list(pair), llm_pair)
    assert [f.statement for f in pair_result.facts] == [
        "2 feed items about neural pruning tools"
    ]
    llm_repeat = CaseLLM(
        feed=(
            _feed_batch(
                {"evidence": [feeds[item.id]], "topic": "neural pruning tools"}
            ),
        )
    )
    repeat = extract_facts(AS_OF, SUBJECT_ID, [item], llm_repeat)
    assert repeat.prompt_hash == result.prompt_hash
    assert repeat.cycle_id == result.cycle_id


def test_statement_naming_no_period_keeps_old_rule() -> None:
    prior_push, last_one, last_two = _number_binding_pushes()
    events = [prior_push, last_one, last_two]
    last_ids = [last_one.id, last_two.id]
    all_ids = [prior_push.id, last_one.id, last_two.id]
    # Derived by hand: period.last.pushes is 2.0, period.prior.pushes is 1.0,
    # github.push.count is 3.0. No period named, so the period keys stay
    # eligible and the cited last rows back the 2; the whole-window count
    # backs the 3; nothing backs a 7.
    assert _run("Pushes were 2", last_ids, events) is None
    assert _run("Pushes were 3", all_ids, events) is None
    assert _run("Pushes were 7", last_ids, events) == "FACT_NUMBER_UNBACKED"


def test_total_does_not_back_a_paired_number() -> None:
    prior_push, last_one, last_two = _number_binding_pushes()
    events = [prior_push, last_one, last_two]
    last_ids = [last_one.id, last_two.id]
    # Derived by hand: period.last.pushes is 2.0 and github.push.count is
    # 3.0. The 3 pairs to last, which holds 2.0, and the whole-window
    # total must not back a period-paired number.
    assert _run("Pushes were 3 in last", last_ids, events) == "FACT_NUMBER_UNBACKED"
    assert _run("Pushes were 2 in last", last_ids, events) is None
