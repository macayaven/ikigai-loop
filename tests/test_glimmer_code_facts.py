"""Ticket 9b: code facts (largest change per family, zero keys, pass flags).

Every hand-derived expectation is listed with its derivation in
docs/sessions/009b-code-facts.md (D18). The live fixture comes from
evals/glimmer_cases.py. No network, no real model, no real data.
"""

import hashlib
import tempfile
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from evals.glimmer_cases import (
    AS_OF,
    LIVE_CONTENT,
    SUBJECT_ID,
    WINDOW_START,
    RecordingLLM,
    ScriptEntry,
    _dt,
    cal_event,
    feed_aliases,
    feed_batch,
    feed_event,
    live_table_events,
    personal_aliases,
    personal_batch,
    pr_event,
    push_event,
    screen_event,
)
from framework.briefing.context import MetricSnapshot
from framework.glimmer.checks import check_fact
from framework.glimmer.code_facts import (
    COUNT_FLOOR,
    HOURS_FLOOR,
    SCREEN_DISPLAY_NAMES,
    SCREEN_SKIPPED_CATEGORIES,
    CodeFact,
    code_facts,
    format_metric_value,
    is_duplicate_of_code,
)
from framework.glimmer.facts import (
    FactResult,
    LLMUnavailableError,
    extract_facts,
)
from framework.glimmer.metrics import (
    build_metric_snapshot,
    build_period_rollup,
    select_winners,
)
from framework.schemas.events import Event
from framework.store.fact_store import FactStore

PINNED_STATEMENTS = (
    "Media/Video screen hours rose from 0 in prior to 4 in last.",
    "Pushes fell from 3 in earlier to 1 in prior.",
    "Pull requests fell from 1 in prior to 0 in last.",
    "iki-deep calendar hours fell from 3 in prior to 0 in last.",
    "Cancelled iki-deep blocks fell from 1 in prior to 0 in last.",
)


def _code(
    as_of: datetime = AS_OF, events: Sequence[Event] | None = None
) -> tuple[CodeFact, ...]:
    rows = live_table_events() if events is None else events
    winners = select_winners(rows)
    return code_facts(as_of, winners, build_period_rollup(as_of, winners))


def test_fixture_code_facts_exact() -> None:
    events = live_table_events()
    winners = select_winners(events)
    facts = code_facts(AS_OF, winners, build_period_rollup(AS_OF, winners))
    assert [f.statement for f in facts] == list(PINNED_STATEMENTS)
    assert [f.family for f in facts] == [
        "screen_hours",
        "pushes",
        "prs",
        "tag_hours",
        "cancelled",
    ]
    assert [f.member for f in facts] == ["Media/Video", "", "", "iki-deep", "iki-deep"]
    assert [(f.from_period, f.to_period) for f in facts] == [
        ("prior", "last"),
        ("earlier", "prior"),
        ("prior", "last"),
        ("prior", "last"),
        ("prior", "last"),
    ]
    assert [(f.from_value, f.to_value) for f in facts] == [
        (0.0, 4.0),
        (3.0, 1.0),
        (1.0, 0.0),
        (3.0, 0.0),
        (1.0, 0.0),
    ]
    for fact in facts:
        assert len(fact.evidence) >= 1
        assert fact.tier == "private" or fact.tier == "public"
    assert [f.metric_ids for f in facts] == [
        (
            "period.prior.screen_hours.Media/Video",
            "period.last.screen_hours.Media/Video",
        ),
        ("period.earlier.pushes", "period.prior.pushes"),
        ("period.prior.prs", "period.last.prs"),
        ("period.prior.tag_hours.iki-deep", "period.last.tag_hours.iki-deep"),
        ("period.prior.cancelled.iki-deep", "period.last.cancelled.iki-deep"),
    ]


def test_fixture_code_facts_deterministic() -> None:
    assert _code() == _code()


def test_tie_later_pair_wins_prs_and_cancelled() -> None:
    prs = [pr_event(eid="evt_tie_pr", time=_dt(29, 16))]
    cancelled = cal_event(
        eid="evt_tie_cx",
        key="tie-cx@20261029T130000",
        lm="seq1",
        time=_dt(29, 13),
        end=_dt(29, 14),
        tags=("iki-tie",),
        cancelled=True,
    )
    facts = _code(events=[*prs, cancelled])
    by_family = {f.family: f for f in facts}
    assert by_family["prs"].from_period == "prior"
    assert by_family["prs"].statement == (
        "Pull requests fell from 1 in prior to 0 in last."
    )
    assert by_family["cancelled"].from_period == "prior"
    assert by_family["cancelled"].statement == (
        "Cancelled iki-tie blocks fell from 1 in prior to 0 in last."
    )


def test_tie_float_noise_rounding_keeps_later_pair() -> None:
    # Six 10-minute rows total 0.9999999999999999 before D3 rounding; the
    # pinned rule compares the rounded change, so this ties the exact 1.0
    # of the earlier pair and the later pair wins. Without the rounding
    # the noise decides and the earlier pair wins instead.
    prior_row = screen_event(
        eid="evt_flt_prior", time=_dt(29, 14), minutes={"Tie/Cat": 60.0}
    )
    last_rows = [
        screen_event(
            eid=f"evt_flt_last_{i}", time=_dt(30, 14, i), minutes={"Tie/Cat": 10.0}
        )
        for i in range(6)
    ]
    last_rows.append(
        screen_event(eid="evt_flt_last_60", time=_dt(30, 15), minutes={"Tie/Cat": 60.0})
    )
    (fact,) = [
        f for f in _code(events=[prior_row, *last_rows]) if f.family == "screen_hours"
    ]
    assert fact.from_period == "prior"
    assert fact.statement == "Tie/Cat screen hours rose from 1 in prior to 2 in last."


def test_tie_pair_rank_beats_member_order() -> None:
    earlier = screen_event(
        eid="evt_t5_early", time=_dt(28, 14), minutes={"Aaa/Cat": 120.0}
    )
    prior = screen_event(
        eid="evt_t5_prior", time=_dt(29, 14), minutes={"Bbb/Cat": 120.0}
    )
    facts = _code(events=[earlier, prior])
    (fact,) = [f for f in facts if f.family == "screen_hours"]
    assert fact.member == "Bbb/Cat"
    assert (fact.from_period, fact.to_period) == ("prior", "last")


def test_tie_same_pair_member_order() -> None:
    rows = [
        screen_event(eid="evt_t5b_n", time=_dt(30, 14), minutes={"Nnn/Cat": 120.0}),
        screen_event(eid="evt_t5b_m", time=_dt(30, 15), minutes={"Mmm/Cat": 120.0}),
    ]
    facts = _code(events=rows)
    (fact,) = [f for f in facts if f.family == "screen_hours"]
    assert fact.member == "Mmm/Cat"


def test_equal_periods_empty_change_no_fact() -> None:
    rows = [
        screen_event(eid=f"evt_eq_{d}", time=_dt(28 + d, 14), minutes={"Eq/Cat": 60.0})
        for d in range(3)
    ]
    assert _code(events=rows) == ()


def test_empty_window_no_code_facts() -> None:
    winners = select_winners([])
    assert code_facts(AS_OF, winners, build_period_rollup(AS_OF, winners)) == ()
    snapshot = build_metric_snapshot(AS_OF, winners)
    assert snapshot.values == {
        "calendar.busy_hours": 0.0,
        "feed.item.count": 0.0,
        "period.earlier.prs": 0.0,
        "period.earlier.pushes": 0.0,
        "period.last.prs": 0.0,
        "period.last.pushes": 0.0,
        "period.prior.prs": 0.0,
        "period.prior.pushes": 0.0,
    }


def test_one_row_screen_family_rose_from_zero() -> None:
    row = screen_event(eid="evt_one_s", time=_dt(30, 14), minutes={"Only/Cat": 60.0})
    (fact,) = _code(events=[row])
    assert fact.family == "screen_hours"
    assert fact.statement == "Only/Cat screen hours rose from 0 in prior to 1 in last."
    assert fact.evidence == (row.id,)


def test_one_row_pushes_rose_from_zero() -> None:
    row = push_event(eid="evt_one_p", time=_dt(30, 14))
    (fact,) = _code(events=[row])
    assert fact.statement == "Pushes rose from 0 in prior to 1 in last."
    assert fact.evidence == (row.id,)


def test_floors_pinned_by_value() -> None:
    assert HOURS_FLOOR == 0.5
    assert COUNT_FLOOR == 1.0


def test_is_duplicate_of_code_returns_the_fact() -> None:
    facts = _code()
    media = next(f for f in facts if f.member == "Media/Video")
    assert isinstance(media, CodeFact)
    match = is_duplicate_of_code(
        "Media/Video rose by 4 hours from prior to last.", [], facts
    )
    assert match == media
    assert (
        is_duplicate_of_code("Media/Video reached 4 hours in last.", [], facts) is None
    )


def test_is_duplicate_unit_rules() -> None:
    facts = _code()
    # Every fixture fact matches its own statement and evidence, not just
    # the first one.
    assert len(facts) == 5
    for fact in facts:
        assert is_duplicate_of_code(fact.statement, list(fact.evidence), facts) is fact
    # A cancelled fact needs "cancel" in the statement.
    (cancelled,) = [f for f in facts if f.family == "cancelled"]
    assert (
        is_duplicate_of_code(
            "iki-deep blocks fell from 1 in prior to 0 in last.",
            list(cancelled.evidence),
            [cancelled],
        )
        is None
    )
    # A statement naming a period outside the fact is not a repeat.
    (pushes,) = [f for f in facts if f.family == "pushes"]
    assert (pushes.from_period, pushes.to_period) == ("earlier", "prior")
    assert (
        is_duplicate_of_code(
            "Pushes fell from 3 in earlier to 1 in last.",
            list(pushes.evidence),
            [pushes],
        )
        is None
    )
    # One token cannot stand for both values: 3.6 and 4.4 both round to 4,
    # but the single token 4 backs neither value under rule (a), and only
    # one period word is named, so rule (b) cannot match either.
    near_rows = [
        screen_event(
            eid="evt_near_early", time=_dt(28, 14), minutes={"Near/Cat": 216.0}
        ),
        screen_event(
            eid="evt_near_prior", time=_dt(29, 14), minutes={"Near/Cat": 216.0}
        ),
        screen_event(
            eid="evt_near_last", time=_dt(30, 14), minutes={"Near/Cat": 264.0}
        ),
    ]
    (near,) = [f for f in _code(events=near_rows) if f.family == "screen_hours"]
    assert near.statement == (
        "Near/Cat screen hours rose from 3.6 in prior to 4.4 in last."
    )
    assert (
        is_duplicate_of_code(
            "Near/Cat stayed near 4 in last.", list(near.evidence), [near]
        )
        is None
    )
    # Labels match whole tokens: ai appears inside "Fair" but is not named.
    ai_rows = [
        screen_event(eid="evt_fair_prior", time=_dt(29, 14), minutes={"ai": 60.0}),
        screen_event(eid="evt_fair_last", time=_dt(30, 14), minutes={"ai": 120.0}),
    ]
    (ai_fact,) = [f for f in _code(events=ai_rows) if f.family == "screen_hours"]
    assert (
        is_duplicate_of_code(
            "Fair hours rose from 1 in prior to 2 in last.",
            [r.id for r in ai_rows],
            [ai_fact],
        )
        is None
    )
    # Half-up keeps 0.125 as 0.13; half-even would give 0.12 and lose the
    # token, so this case pins the rounding inside the duplicate rule.
    half_rows = [
        screen_event(eid="evt_half_prior", time=_dt(29, 14), minutes={"Half/Cat": 7.5}),
        screen_event(eid="evt_half_last", time=_dt(30, 14), minutes={"Half/Cat": 60.0}),
    ]
    (half,) = [f for f in _code(events=half_rows) if f.family == "screen_hours"]
    assert (
        half.statement == "Half/Cat screen hours rose from 0.13 in prior to 1 in last."
    )
    assert is_duplicate_of_code(half.statement, list(half.evidence), [half]) is half


def test_floor_boundary_rows_and_counts() -> None:
    half = screen_event(
        eid="evt_flr_half", time=_dt(30, 14), minutes={"Floor/Cat": 30.0}
    )
    (fact,) = [f for f in _code(events=[half]) if f.family == "screen_hours"]
    assert (
        fact.statement == "Floor/Cat screen hours rose from 0 in prior to 0.5 in last."
    )
    six = [
        screen_event(
            eid=f"evt_flr_six_{i}", time=_dt(30, 14, i), minutes={"Floor/Cat": 5.0}
        )
        for i in range(6)
    ]
    (fact,) = [f for f in _code(events=six) if f.family == "screen_hours"]
    assert (
        fact.statement == "Floor/Cat screen hours rose from 0 in prior to 0.5 in last."
    )
    low = screen_event(eid="evt_flr_low", time=_dt(30, 14), minutes={"Floor/Cat": 29.4})
    assert [f for f in _code(events=[low]) if f.family == "screen_hours"] == []
    push = push_event(eid="evt_flr_push", time=_dt(30, 14))
    assert [f for f in _code(events=[push]) if f.family == "pushes"] != []
    assert [f for f in _code(events=[half]) if f.family == "pushes"] == []


def test_floor_tag_hours_uses_hours_floor() -> None:
    # 45 minutes is 0.75 hours, above the hours floor; 29 minutes is below
    # it. The tag family must use HOURS_FLOOR, not the count floor.
    long_block = cal_event(
        eid="evt_flr_long",
        key="flr-long@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 14, 45),
        tags=("iki-flr",),
    )
    (fact,) = [f for f in _code(events=[long_block]) if f.family == "tag_hours"]
    assert fact.statement == (
        "iki-flr calendar hours rose from 0 in prior to 0.75 in last."
    )
    short_block = cal_event(
        eid="evt_flr_short",
        key="flr-short@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 14, 29),
        tags=("iki-flr",),
    )
    assert [f for f in _code(events=[short_block]) if f.family == "tag_hours"] == []


def test_no_tag_cancelled_row_creates_no_member() -> None:
    untagged = cal_event(
        eid="evt_nt_plain",
        key="nt-plain@20261029T130000",
        lm="seq1",
        time=_dt(29, 13),
        end=_dt(29, 14),
        tags=(),
        cancelled=True,
    )
    push = push_event(eid="evt_nt_push", time=_dt(30, 14))
    facts = _code(events=[untagged, push])
    assert [f for f in facts if f.family == "cancelled"] == []
    for fact in facts:
        assert untagged.id not in fact.evidence


def test_format_metric_value_round_trips() -> None:
    from framework.briefing.gate import _ref_backs_token
    from framework.glimmer.checks import _backs

    for value, text in (
        (4.0, "4"),
        (1.7500000001, "1.75"),
        (0.3333, "0.33"),
        (2.5, "2.5"),
        (6.75, "6.75"),
        (0.0, "0"),
        (1.7333333333333332, "1.73"),
        (3.4499999999999993, "3.45"),
        (4.749999999999999, "4.75"),
        (10.0, "10"),
        (20.0, "20"),
        (100.0, "100"),
        (0.995, "1"),
        (0.004, "0"),
        # Half-up, not half-even: half-even would give "0.12" and "1.00".
        (0.125, "0.13"),
        (1.005, "1.01"),
    ):
        assert format_metric_value(value) == text, value
        places = len(text.split(".")[1]) if "." in text else 0
        assert _backs(value, places, abs(Decimal(text))), (value, text)
        assert _ref_backs_token(value, places, abs(Decimal(text))), (value, text)
    assert format_metric_value(3.0) == "3"


def test_template_statements_byte_for_byte() -> None:
    screen = screen_event(eid="evt_tpl_s", time=_dt(30, 14), minutes={"T/Cat": 60.0})
    push = push_event(eid="evt_tpl_p", time=_dt(30, 14))
    pr = pr_event(eid="evt_tpl_r", time=_dt(30, 14))
    block = cal_event(
        eid="evt_tpl_b",
        key="tpl-b@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 15),
        tags=("iki-t",),
    )
    cancelled = cal_event(
        eid="evt_tpl_c",
        key="tpl-c@20261030T160000",
        lm="seq1",
        time=_dt(30, 16),
        end=_dt(30, 17),
        tags=("iki-t",),
        cancelled=True,
    )
    by_family = {
        f.family: f for f in _code(events=[screen, push, pr, block, cancelled])
    }
    assert by_family["screen_hours"].statement == (
        "T/Cat screen hours rose from 0 in prior to 1 in last."
    )
    assert by_family["pushes"].statement == "Pushes rose from 0 in prior to 1 in last."
    assert by_family["prs"].statement == (
        "Pull requests rose from 0 in prior to 1 in last."
    )
    assert by_family["tag_hours"].statement == (
        "iki-t calendar hours rose from 0 in prior to 1 in last."
    )
    assert by_family["cancelled"].statement == (
        "Cancelled iki-t blocks rose from 0 in prior to 1 in last."
    )
    for fact in by_family.values():
        assert ("rose" in fact.statement) != ("fell" in fact.statement)
    falling = screen_event(eid="evt_tpl_f", time=_dt(28, 14), minutes={"T/Cat": 60.0})
    (fact,) = [f for f in _code(events=[falling]) if f.family == "screen_hours"]
    assert fact.statement == "T/Cat screen hours fell from 1 in earlier to 0 in prior."


def _gate_briefing(
    statement: str,
    fact_ids: list[str],
    refs: list[tuple[str, float]],
    facts: dict,
    extra_metrics: dict | None = None,
):  # type: ignore[no-untyped-def]
    from evals.briefing_cases import base_case as briefing_base_case

    case = briefing_base_case("builder")
    import copy

    briefing = copy.deepcopy(case.briefing)
    briefing["sections"][0]["claims"].append(
        {
            "id": "claim-code-1",
            "text": statement,
            "fact_ids": fact_ids,
            "metric_refs": [
                {"metric_id": metric_id, "value": value} for metric_id, value in refs
            ],
        }
    )
    metrics = dict(case.context.metrics.values)
    if extra_metrics is not None:
        metrics.update(extra_metrics)
    context = case.context.model_copy(
        update={
            "metrics": MetricSnapshot(values=metrics),
            "facts": {**case.context.facts, **facts},
        }
    )
    return briefing, context


def _live_result() -> tuple[list[Event], FactResult, tuple[CodeFact, ...]]:
    events = live_table_events()
    winners = select_winners(events)
    code = code_facts(AS_OF, winners, build_period_rollup(AS_OF, winners))
    llm = RecordingLLM(personal=(ScriptEntry(text=LIVE_CONTENT),))
    return events, extract_facts(AS_OF, SUBJECT_ID, events, llm), code


def test_gate_round_trip_refs_only_and_with_fact() -> None:
    from framework.briefing.gate import evaluate_briefing

    _events, result, code = _live_result()
    assert [f.statement for f in result.facts[:5]] == list(PINNED_STATEMENTS)
    by_id = {f.id: f for f in result.facts}
    for fact in code:
        refs = [
            (metric_id, result.snapshot.values[metric_id])
            for metric_id in fact.metric_ids
        ]
        briefing, context = _gate_briefing(
            fact.statement, [], refs, {}, dict(result.snapshot.values)
        )
        passed = evaluate_briefing(briefing, context)
        assert passed.violations == (), (fact.statement, passed.violations)
        kept = next(f for f in result.facts if f.statement == fact.statement)
        briefing, context = _gate_briefing(
            fact.statement,
            [kept.id],
            refs,
            {kept.id: by_id[kept.id]},
            dict(result.snapshot.values),
        )
        passed = evaluate_briefing(briefing, context)
        assert passed.violations == (), (fact.statement, passed.violations)


def test_gate_direction_swap_and_third_period_rejected() -> None:
    from framework.briefing.gate import evaluate_briefing

    _, result, code = _live_result()
    fact = code[0]
    refs = [(m, result.snapshot.values[m]) for m in fact.metric_ids]
    swapped = fact.statement.replace("rose", "fell")
    assert swapped != fact.statement
    briefing, context = _gate_briefing(
        swapped, [], refs, {}, dict(result.snapshot.values)
    )
    failed = evaluate_briefing(briefing, context)
    assert [v.code for v in failed.violations] == ["L1B_DIRECTION_MISMATCH"]
    third = fact.statement.replace("prior", "earlier")
    briefing, context = _gate_briefing(
        third, [], refs, {}, dict(result.snapshot.values)
    )
    failed = evaluate_briefing(briefing, context)
    assert [v.code for v in failed.violations] == ["L1B_PERIOD_WORD_MISSING"]
    # Known gate limit, documented not asserted as a rejection: exchanging
    # the two cited period words with each other still passes, because the
    # gate compares the named set with the cited set and reads direction
    # from the refs ordered by period.


def test_gate_screen_to_zero_needs_its_zero_key() -> None:
    from framework.briefing.gate import evaluate_briefing

    row = screen_event(eid="evt_zero3", time=_dt(29, 14), minutes={"Solo/Cat": 180.0})
    winners = select_winners([row])
    snapshot = build_metric_snapshot(AS_OF, winners)
    assert snapshot.values["period.last.screen_hours.Solo/Cat"] == 0.0
    statement = "Solo/Cat screen hours fell from 3 in prior to 0 in last."
    refs = [
        ("period.prior.screen_hours.Solo/Cat", 3.0),
        ("period.last.screen_hours.Solo/Cat", 0.0),
    ]
    briefing, context = _gate_briefing(statement, [], refs, {})
    context = context.model_copy(
        update={"metrics": MetricSnapshot(values=dict(snapshot.values))}
    )
    assert evaluate_briefing(briefing, context).violations == ()
    stripped = {key: value for key, value in snapshot.values.items() if value != 0.0}
    context = context.model_copy(update={"metrics": MetricSnapshot(values=stripped)})
    failed = evaluate_briefing(briefing, context)
    assert [v.code for v in failed.violations] == ["L1B_UNKNOWN_METRIC"]
    # The iki-deep tag claim over the fixture is the same regression: its
    # "to 0 in last" ref cites period.last.tag_hours.iki-deep, a key that
    # does not exist before the zero-key change.
    _, live, _ = _live_result()
    assert live.snapshot.values["period.last.tag_hours.iki-deep"] == 0.0


def _check(statement: str, evidence: list[str], events: list) -> str | None:  # type: ignore[no-untyped-def]
    winners = select_winners(events)
    return check_fact(
        statement,
        evidence,
        known_by_id={e.id: e for e in events},
        winning_ids=frozenset(e.id for e in winners),
        winners=list(winners),
        snapshot=build_metric_snapshot(AS_OF, winners),
        feed_titles=[],
        as_of=AS_OF,
        window_start=WINDOW_START,
    )


def test_zero_backing_strict_both_directions() -> None:
    push = push_event(eid="evt_zb_push", time=_dt(30, 14))
    assert _check("Prior period push count sits at 0 today", [push.id], [push]) is None
    prior_row = screen_event(
        eid="evt_zb_prior", time=_dt(29, 18), minutes={"Programming": 405.0}
    )
    last_row = screen_event(
        eid="evt_zb_last", time=_dt(30, 18), minutes={"Programming": 120.0}
    )
    events = [prior_row, last_row]
    stmt = (
        "Work/Programming screen hours fell from 6.75 in the prior period "
        "to 2.0 in the last period"
    )
    assert _check(stmt, [last_row.id], events) == "FACT_NUMBER_UNBACKED"


def test_feed_title_cannot_remove_code_fact() -> None:
    title = "My screen hours rose from 0 to 4 this week"
    item = feed_event(
        eid="evt_ft_feed",
        item="item-ft",
        day="2026-10-30",
        time=_dt(30, 9),
        title=title,
    )
    events = [*live_table_events(), item]
    by_alias = {f"e{i + 1}": e.id for i, e in enumerate(events)}
    last_media = [by_alias[f"e{i}"] for i in range(34, 42)]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {"statement": title, "evidence": [aliases[e] for e in last_media]},
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    # The code fact is checked with no feed titles, so it survives the
    # headline that shares its 5-word run; the model copy drops on it.
    assert PINNED_STATEMENTS[0] in [f.statement for f in result.facts]
    assert "FACT_FEED_HEADLINE_OVERLAP" in [d.code for d in result.dropped]


def test_code_drop_visible_and_excluded_from_ids() -> None:
    row = screen_event(
        eid="evt_cd_row", time=_dt(30, 14), minutes={"Top10/Video": 120.0}
    )
    aliases = personal_aliases((row,))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Screen time continued in the last period",
                    "evidence": [aliases[row.id]],
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [row], llm)
    assert [d.code for d in result.dropped] == ["CODE_FACT_NUMBER_UNBACKED"]
    assert result.code_fact_ids == ()
    assert [f.statement for f in result.facts] == [
        "Screen time continued in the last period"
    ]
    # The dropped code fact reaches neither the block nor the prompt: only
    # kept code facts are listed, so the block holds the empty state.
    (prompt,) = llm.personal_prompts
    assert "Top10/Video screen hours rose" not in prompt
    assert (
        "CODE FACTS (already reported by code; do not restate them):\n- none\n"
        in prompt
    )


def test_evidence_cap_reserves_each_period() -> None:
    prior_row = screen_event(
        eid="evt_cap_prior", time=_dt(29, 14), minutes={"Cap/Cat": 60.0}
    )
    last_rows = [
        screen_event(
            eid=f"evt_cap_last_{i:02d}", time=_dt(30, 14, i), minutes={"Cap/Cat": 20.0}
        )
        for i in range(9)
    ]
    events = [prior_row, *last_rows]
    (fact,) = [f for f in _code(events=events) if f.family == "screen_hours"]
    assert fact.statement == "Cap/Cat screen hours rose from 1 in prior to 3 in last."
    assert len(fact.evidence) == 8
    assert prior_row.id in fact.evidence
    ordered = sorted(
        fact.evidence,
        key=lambda eid: next(e for e in events if e.id == eid).time,
        reverse=True,
    )
    assert list(fact.evidence) == ordered


def test_evidence_reservation_matters_through_extract_facts() -> None:
    # Nine rows in the later period would fill a plain global top-8 on
    # their own; the earlier period's non-zero value then has no cited row
    # inside its period and the fact drops. The reservation keeps it.
    prior_row = screen_event(
        eid="evt_res_prior", time=_dt(29, 14), minutes={"Res/Cat": 60.0}
    )
    last_rows = [
        screen_event(
            eid=f"evt_res_last_{i:02d}", time=_dt(30, 14, i), minutes={"Res/Cat": 20.0}
        )
        for i in range(9)
    ]
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(
        AS_OF, SUBJECT_ID, [prior_row, *last_rows], llm, feed_pass=False
    )
    assert [f.statement for f in result.facts] == [
        "Res/Cat screen hours rose from 1 in prior to 3 in last."
    ]
    assert prior_row.id in result.facts[0].evidence


def test_evidence_exact_ids_reserve_newest_and_fill_newest() -> None:
    # Prior holds 1 hour (3 rows of 20 minutes), last holds 3 hours (9 rows
    # of 20 minutes), earlier holds 0: prior to last (2) beats earlier to
    # prior (1). The reservation takes the newest row of each period, then
    # the fill takes the newest rows overall, up to 8.
    prior_rows = [
        screen_event(
            eid=f"evt_ex_prior_{i}", time=_dt(29, 14, i), minutes={"Ex/Cat": 20.0}
        )
        for i in range(3)
    ]
    last_rows = [
        screen_event(
            eid=f"evt_ex_last_{i:02d}", time=_dt(30, 14, i), minutes={"Ex/Cat": 20.0}
        )
        for i in range(9)
    ]
    (fact,) = [
        f for f in _code(events=[*prior_rows, *last_rows]) if f.family == "screen_hours"
    ]
    assert fact.statement == "Ex/Cat screen hours rose from 1 in prior to 3 in last."
    assert list(fact.evidence) == [
        "evt_ex_last_08",
        "evt_ex_last_07",
        "evt_ex_last_06",
        "evt_ex_last_05",
        "evt_ex_last_04",
        "evt_ex_last_03",
        "evt_ex_last_02",
        "evt_ex_prior_2",
    ]


def test_evidence_time_tie_sorts_by_id() -> None:
    # Reservation takes z for prior and a for last, so a enters before b;
    # only the final (time, id) sort puts b ahead of a.
    tie_a = cal_event(
        eid="evt_tie_a",
        key="tie-a@20261029T100000",
        lm="seq-a",
        time=_dt(29, 10),
        end=_dt(30, 15),
        tags=("iki-tie",),
    )
    tie_b = cal_event(
        eid="evt_tie_b",
        key="tie-b@20261029T100000",
        lm="seq-b",
        time=_dt(29, 10),
        end=_dt(29, 14),
        tags=("iki-tie",),
    )
    tie_z = cal_event(
        eid="evt_tie_z",
        key="tie-z@20261029T160000",
        lm="seq-z",
        time=_dt(29, 16),
        end=_dt(29, 17),
        tags=("iki-tie",),
    )
    (fact,) = [
        f for f in _code(events=[tie_a, tie_b, tie_z]) if f.family == "tag_hours"
    ]
    assert (
        fact.statement == "iki-tie calendar hours fell from 26 in prior to 2 in last."
    )
    assert list(fact.evidence) == ["evt_tie_z", "evt_tie_b", "evt_tie_a"]


def test_evidence_block_started_before_from_period() -> None:
    # The block starts in earlier but overlaps prior for 3 hours and earlier
    # for 2: prior to last (3) beats earlier to prior (1). Only clipped
    # overlap can put it in the prior pool, since its time is in earlier.
    block = cal_event(
        eid="evt_cross_block",
        key="cross-1@20261029T110000",
        lm="seq1",
        time=_dt(29, 11),
        end=_dt(29, 16),
        tags=("iki-cross",),
    )
    (fact,) = [f for f in _code(events=[block]) if f.family == "tag_hours"]
    assert fact.statement == (
        "iki-cross calendar hours fell from 3 in prior to 0 in last."
    )
    assert list(fact.evidence) == [block.id]
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [block], llm)
    assert [f.statement for f in result.facts] == [fact.statement]


def test_evidence_cancelled_and_tag_pools_stay_separate() -> None:
    # Each row carries its own logical key and the shared tag iki-keep.
    # Cancelled: earlier 1, prior 2, last 0, so prior to last (2) beats
    # earlier to prior (1). Tag hours: earlier 0, prior 1, last 0, a tie
    # the later pair wins.
    cancelled = [
        cal_event(
            eid="evt_keep_x_early",
            key="keep-x-early@20261028T150000",
            lm="seq1",
            time=_dt(28, 15),
            end=_dt(28, 16),
            tags=("iki-keep",),
            cancelled=True,
        ),
        cal_event(
            eid="evt_keep_x_prior_0",
            key="keep-x-p0@20261029T150000",
            lm="seq1",
            time=_dt(29, 15),
            end=_dt(29, 16),
            tags=("iki-keep",),
            cancelled=True,
        ),
        cal_event(
            eid="evt_keep_x_prior_1",
            key="keep-x-p1@20261029T160000",
            lm="seq1",
            time=_dt(29, 16),
            end=_dt(29, 17),
            tags=("iki-keep",),
            cancelled=True,
        ),
    ]
    live = cal_event(
        eid="evt_keep_live",
        key="keep-live@20261029T180000",
        lm="seq1",
        time=_dt(29, 18),
        end=_dt(29, 19),
        tags=("iki-keep",),
    )
    by_family = {f.family: f for f in _code(events=[*cancelled, live])}
    assert set(by_family) == {"cancelled", "tag_hours"}
    assert by_family["cancelled"].statement == (
        "Cancelled iki-keep blocks fell from 2 in prior to 0 in last."
    )
    assert list(by_family["cancelled"].evidence) == [
        "evt_keep_x_prior_1",
        "evt_keep_x_prior_0",
    ]
    assert by_family["tag_hours"].statement == (
        "iki-keep calendar hours fell from 1 in prior to 0 in last."
    )
    assert list(by_family["tag_hours"].evidence) == ["evt_keep_live"]


def test_evidence_every_code_fact_cites_a_row() -> None:
    events = live_table_events()
    for fact in _code(events=events):
        assert len(fact.evidence) >= 1
    push = push_event(eid="evt_e1_push", time=_dt(30, 14))
    pr = pr_event(eid="evt_e1_pr", time=_dt(30, 15))
    block = cal_event(
        eid="evt_e1_block",
        key="e1@20261030T140000",
        lm="seq1",
        time=_dt(30, 14),
        end=_dt(30, 15),
        tags=("iki-one",),
    )
    cancelled = cal_event(
        eid="evt_e1_cx",
        key="e1x@20261030T160000",
        lm="seq1",
        time=_dt(30, 16),
        end=_dt(30, 17),
        tags=("iki-one",),
        cancelled=True,
    )
    screen = screen_event(
        eid="evt_e1_screen", time=_dt(30, 18), minutes={"Solo/Cat": 60.0}
    )
    for fact in _code(events=[push, pr, block, cancelled, screen]):
        assert len(fact.evidence) >= 1


def test_evidence_zero_minute_row_never_cited() -> None:
    prior_row = screen_event(
        eid="evt_zm_prior", time=_dt(29, 14), minutes={"Media/Video": 60.0}
    )
    zero_row = screen_event(
        eid="evt_zm_zero",
        time=_dt(30, 14),
        minutes={"Media/Video": 0.0, "Work/Programming": 30.0},
    )
    real_row = screen_event(
        eid="evt_zm_real", time=_dt(30, 15), minutes={"Media/Video": 120.0}
    )
    (fact,) = [
        f
        for f in _code(events=[prior_row, zero_row, real_row])
        if f.family == "screen_hours" and f.member == "Media/Video"
    ]
    assert zero_row.id not in fact.evidence
    assert set(fact.evidence) == {prior_row.id, real_row.id}


def test_evidence_crossing_block_cited_through_overlap() -> None:
    # One long block is the only row behind both compared values: its
    # start sits in the earlier period, so only clipped overlap makes it a
    # candidate in the prior pool. One evidence id, fact kept.
    block = cal_event(
        eid="evt_ov_long",
        key="ov-long@20261029T120000",
        lm="seq1",
        time=_dt(29, 12),
        end=_dt(30, 15),
        tags=("iki-span",),
    )
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [block], llm, feed_pass=False)
    assert [f.statement for f in result.facts] == [
        "iki-span calendar hours rose from 1 in earlier to 24 in prior."
    ]
    assert list(result.facts[0].evidence) == [block.id]


def test_evidence_block_in_both_pools_gives_one_id() -> None:
    block = cal_event(
        eid="evt_both_long",
        key="both-long@20261029T140000",
        lm="seq1",
        time=_dt(29, 14),
        end=_dt(30, 14),
        tags=("iki-both",),
    )
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [block], llm, feed_pass=False)
    assert [f.statement for f in result.facts] == [
        "iki-both calendar hours rose from 0 in earlier to 23 in prior."
    ]
    assert list(result.facts[0].evidence) == [block.id]


def _duplicate_result(
    statement: str, evidence_ids: list[str], events: list[Event]
) -> FactResult:
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": statement,
                    "evidence": [aliases[eid] for eid in evidence_ids],
                }
            ),
        ),
        feed=(feed_batch(),),
    )
    return extract_facts(AS_OF, SUBJECT_ID, events, llm)


def _live_aliases() -> tuple[list[Event], dict[str, str]]:
    events = live_table_events()
    return events, personal_aliases(tuple(events))


def test_duplicate_verbatim_and_rewordings_drop() -> None:
    events, _ = _live_aliases()
    by_alias = {f"e{i + 1}": e.id for i, e in enumerate(events)}
    last_media = [by_alias[f"e{i}"] for i in range(34, 42)]
    cases = [
        "Media/Video screen hours rose from 0 in prior to 4 in last.",
        "In last, Media/Video screen hours reached 4, up from 0 in prior.",
        "Video screen time went from zero in prior to 4.0 in last.",
        "Media/Video rose from 0 to 4 hours in last.",
        "Media/Video rose from 0 to 4 hours.",
        "Media/Video rose by 4 hours from prior to last.",
        "Media/Video rose by 4 hours, from 0 in prior to 4 in last.",
        "Media/Video fell from 0 in prior to 4 in last.",
        "Media/Video rose from none in prior to 4 in last.",
    ]
    for statement in cases:
        result = _duplicate_result(statement, last_media, events)
        assert [d.code for d in result.dropped] == ["FACT_DUPLICATE_OF_CODE"], statement


def test_duplicate_change_only_statement_drops() -> None:
    earlier = screen_event(
        eid="evt_ch_early", time=_dt(28, 14), minutes={"Work/Programming": 285.0}
    )
    prior = screen_event(
        eid="evt_ch_prior", time=_dt(29, 14), minutes={"Work/Programming": 285.0}
    )
    last = screen_event(
        eid="evt_ch_last", time=_dt(30, 14), minutes={"Work/Programming": 105.0}
    )
    events = [earlier, prior, last]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "Work/Programming fell by 3 hours from prior to last.",
                    "evidence": [aliases[prior.id], aliases[last.id]],
                }
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert [d.code for d in result.dropped] == ["FACT_DUPLICATE_OF_CODE"]


def test_duplicate_non_matches_reach_normal_checks() -> None:
    events, _ = _live_aliases()
    by_alias = {f"e{i + 1}": e.id for i, e in enumerate(events)}
    last_media = [by_alias[f"e{i}"] for i in range(34, 42)]
    cases = [
        # (statement, evidence, expected dropped codes)
        (
            "Media/Video fell from 0.17 in earlier to 0 in prior.",
            last_media,
            ["FACT_NUMBER_UNBACKED"],
        ),
        (
            "Media/Video reached 4 hours in last.",
            last_media,
            [],
        ),
        (
            "Work/Programming rose from 0 in prior to 4 in last.",
            [by_alias["e42"], by_alias["e43"]],
            ["FACT_NUMBER_UNBACKED"],
        ),
        (
            "Media/Video rose from 0 in prior to 4 in last, across 8 rows.",
            last_media,
            ["FACT_NUMBER_UNBACKED"],
        ),
        (
            "Media/Video rose from 0 in prior to 3.5 in last.",
            last_media,
            ["FACT_NUMBER_UNBACKED"],
        ),
        (
            "Cancelled iki-deep blocks fell from 3 in prior to 0 in last.",
            [by_alias["e27"]],
            ["FACT_NUMBER_UNBACKED"],
        ),
    ]
    for statement, evidence, expected in cases:
        result = _duplicate_result(statement, evidence, events)
        assert "FACT_DUPLICATE_OF_CODE" not in [d.code for d in result.dropped]
        assert [d.code for d in result.dropped] == expected, statement


def test_duplicate_live_statements_stay_kept() -> None:
    events = live_table_events()
    llm = RecordingLLM(personal=(ScriptEntry(text=LIVE_CONTENT),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert len(result.facts) == 10
    assert result.dropped == ()


def test_cap_model_facts_around_code_facts() -> None:
    events = live_table_events()
    aliases = personal_aliases(tuple(events))
    by_alias = {f"e{i + 1}": e.id for i, e in enumerate(events)}
    words = [
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
        "kilo",
        "lima",
        "mike",
    ]
    drafts = [
        {
            "statement": f"Steady maintenance work continued quietly {word}",
            "evidence": [aliases[by_alias["e22"]]],
        }
        for word in words
    ]
    llm = RecordingLLM(personal=(personal_batch(*drafts),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert len(result.facts) == 17
    assert [f.statement for f in result.facts[:5]] == list(PINNED_STATEMENTS)
    assert [d.code for d in result.dropped] == ["FACT_OVER_LIMIT"]
    personal, _ = result.passes
    assert personal.kept == 12


class _RaisingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise LLMUnavailableError("synthetic outage")


def _fixture_with_feed() -> list[Event]:
    items = [
        feed_event(
            eid="evt_c2_a",
            item="item-c2-a",
            day="2026-10-30",
            time=_dt(30, 9),
            title="Synthetic transformer pruning benchmark results",
        ),
        feed_event(
            eid="evt_c2_b",
            item="item-c2-b",
            day="2026-10-30",
            time=_dt(30, 10),
            title="Synthetic container scheduler release notes",
            source="hn",
            score=120.0,
        ),
    ]
    return [*live_table_events(), *items]


def test_unavailable_model_still_returns_code_facts() -> None:
    llm = _RaisingLLM()
    result = extract_facts(AS_OF, SUBJECT_ID, _fixture_with_feed(), llm)
    assert [f.statement for f in result.facts] == list(PINNED_STATEMENTS)
    assert result.is_noop is False
    assert list(result.code_fact_ids) == [f.id for f in result.facts]
    personal, feed = result.passes
    assert personal.noop_reason == "NOOP_LLM_UNAVAILABLE"
    assert feed.noop_reason == "NOOP_LLM_UNAVAILABLE"


def test_truncated_and_invalid_passes_keep_code_facts() -> None:
    events = _fixture_with_feed()
    feeds = feed_aliases(tuple(e for e in events if e.type == "feed.item"))
    feed_ids = [e.id for e in events if e.type == "feed.item"]
    llm = RecordingLLM(
        personal=(ScriptEntry(text="cut off", finish_reason="length"),),
        feed=(
            feed_batch(
                {
                    "evidence": [feeds[eid] for eid in feed_ids],
                    "topic": "model compression methods",
                }
            ),
        ),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_TRUNCATED"
    assert [f.statement for f in result.facts[:5]] == list(PINNED_STATEMENTS)
    assert result.facts[5].statement == "2 feed items about model compression methods"
    llm = RecordingLLM(
        personal=(ScriptEntry(text="nope"), ScriptEntry(text="still nope")),
        feed=(feed_batch(),),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    personal, feed = result.passes
    assert personal.noop_reason == "NOOP_INVALID_LLM_OUTPUT"
    assert feed.noop_reason == "NOOP_MODEL_RETURNED_NO_FACTS"
    assert [f.statement for f in result.facts] == list(PINNED_STATEMENTS)


def test_skipped_passes_make_no_call() -> None:
    events = _fixture_with_feed()
    # The stub routes by call order, so each skipped case scripts only the
    # pass that runs.
    llm = RecordingLLM(feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm, personal_pass=False)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_PERSONAL_SKIPPED"
    assert personal.attempts == 0
    assert llm.personal_prompts == []
    assert len(llm.feed_prompts) == 1
    assert [f.statement for f in result.facts] == list(PINNED_STATEMENTS)
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm, feed_pass=False)
    _, skipped_feed = result.passes
    assert skipped_feed.noop_reason == "NOOP_FEED_SKIPPED"
    assert skipped_feed.attempts == 0
    assert llm.feed_prompts == []
    assert len(llm.personal_prompts) == 1


def test_skipped_pass_with_nothing_to_read_reports_skipped() -> None:
    items = [
        feed_event(
            eid="evt_sk_a",
            item="item-sk-a",
            day="2026-10-30",
            time=_dt(30, 9),
            title="Synthetic transformer pruning benchmark results",
        )
    ]
    llm = RecordingLLM(feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, items, llm, personal_pass=False)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_PERSONAL_SKIPPED"
    push = push_event(eid="evt_sk_push", time=_dt(30, 14))
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm, feed_pass=False)
    _, feed = result.passes
    assert feed.noop_reason == "NOOP_FEED_SKIPPED"


def test_both_passes_off_never_calls_model() -> None:
    llm = _RaisingLLM()
    result = extract_facts(
        AS_OF,
        SUBJECT_ID,
        live_table_events(),
        llm,
        personal_pass=False,
        feed_pass=False,
    )
    assert llm.calls == 0
    assert [f.statement for f in result.facts] == list(PINNED_STATEMENTS)
    assert result.prompt_hash == hashlib.sha256(b"\x00").hexdigest()


def test_code_only_rerun_appends_run_under_same_cycle() -> None:
    first = extract_facts(
        AS_OF,
        SUBJECT_ID,
        [push_event(eid="evt_r1", time=_dt(30, 14))],
        _RaisingLLM(),
        personal_pass=False,
        feed_pass=False,
    )
    second = extract_facts(
        AS_OF,
        SUBJECT_ID,
        [
            push_event(eid="evt_r2a", time=_dt(30, 14)),
            push_event(eid="evt_r2b", time=_dt(30, 15)),
        ],
        _RaisingLLM(),
        personal_pass=False,
        feed_pass=False,
    )
    assert first.cycle_id == second.cycle_id
    assert first.snapshot.values != second.snapshot.values
    with tempfile.TemporaryDirectory() as tmp:
        store = FactStore(db_path=Path(tmp) / "rerun.db")
        try:
            assert store.record_cycle(first) == 1
            assert store.record_cycle(second) == 2
            assert store.runs(first.cycle_id) == [1, 2]
        finally:
            store.close()


def test_deterministic_code_only_cycles_replay_to_one_run() -> None:
    first = extract_facts(AS_OF, SUBJECT_ID, live_table_events(), _RaisingLLM())
    second = extract_facts(AS_OF, SUBJECT_ID, live_table_events(), _RaisingLLM())
    assert [f.statement for f in first.facts] == [f.statement for f in second.facts]
    assert first.code_fact_ids == second.code_fact_ids
    assert first.snapshot.values == second.snapshot.values
    assert first.cycle_id == second.cycle_id
    with tempfile.TemporaryDirectory() as tmp:
        store = FactStore(db_path=Path(tmp) / "determ.db")
        try:
            assert store.record_cycle(first) == 1
            assert store.record_cycle(second) == 1
        finally:
            store.close()


def test_screen_skips_other_and_system() -> None:
    assert SCREEN_SKIPPED_CATEGORIES == frozenset({"other", "system"})
    assert SCREEN_DISPLAY_NAMES == {"ai": "AI"}
    row = screen_event(
        eid="evt_skip_big",
        time=_dt(30, 14),
        minutes={"system": 300.0, "other": 240.0, "code": 180.0},
    )
    (fact,) = [f for f in _code(events=[row]) if f.family == "screen_hours"]
    assert fact.member == "code"
    assert fact.statement == "code screen hours rose from 0 in prior to 3 in last."


def test_screen_skips_only_skipped_changes_means_no_screen_fact() -> None:
    row = screen_event(
        eid="evt_skip_only",
        time=_dt(30, 14),
        minutes={"system": 300.0, "other": 240.0},
    )
    push = push_event(eid="evt_skip_push", time=_dt(30, 14))
    facts = _code(events=[row, push])
    assert [f for f in facts if f.family == "screen_hours"] == []
    assert [f for f in facts if f.family == "pushes"] != []
    winners = select_winners([row, push])
    snapshot = build_metric_snapshot(AS_OF, winners)
    assert snapshot.values["period.last.screen_hours.system"] == 5.0
    assert snapshot.values["period.prior.screen_hours.system"] == 0.0
    assert snapshot.values["period.last.screen_hours.other"] == 4.0


def test_screen_skips_system_row_is_valid_code_evidence() -> None:
    row = screen_event(
        eid="evt_skip_ev",
        time=_dt(30, 14),
        minutes={"system": 30.0, "code": 30.0},
    )
    (fact,) = [f for f in _code(events=[row]) if f.family == "screen_hours"]
    assert fact.member == "code"
    assert fact.evidence == (row.id,)


def test_ai_template_display_name_and_raw_ids() -> None:
    prior_row = screen_event(eid="evt_ai_prior", time=_dt(29, 14), minutes={"ai": 60.0})
    last_row = screen_event(eid="evt_ai_last", time=_dt(30, 14), minutes={"ai": 120.0})
    events = [prior_row, last_row]
    (fact,) = [f for f in _code(events=events) if f.family == "screen_hours"]
    assert fact.member == "ai"
    assert fact.statement == "AI screen hours rose from 1 in prior to 2 in last."
    assert fact.metric_ids == (
        "period.prior.screen_hours.ai",
        "period.last.screen_hours.ai",
    )
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert [f.statement for f in result.facts] == [fact.statement]


def test_ai_template_claim_passes_gate_and_swap_fails() -> None:
    from framework.briefing.gate import evaluate_briefing

    # Built from real output like test_gate_round_trip_refs_only_and_with_fact:
    # 60 minutes of ai in prior and 120 in last give exactly the AI fact.
    prior_row = screen_event(
        eid="evt_ai3_prior", time=_dt(29, 14), minutes={"ai": 60.0}
    )
    last_row = screen_event(eid="evt_ai3_last", time=_dt(30, 14), minutes={"ai": 120.0})
    events = [prior_row, last_row]
    winners = select_winners(events)
    (fact,) = code_facts(AS_OF, winners, build_period_rollup(AS_OF, winners))
    assert fact.statement == "AI screen hours rose from 1 in prior to 2 in last."
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    (kept,) = result.facts
    assert kept.statement == fact.statement
    by_id = {kept.id: kept}
    refs = [
        (metric_id, result.snapshot.values[metric_id]) for metric_id in fact.metric_ids
    ]
    assert [value for _, value in refs] == [1.0, 2.0]
    for fact_ids, facts in (([], {}), ([kept.id], by_id)):
        briefing, context = _gate_briefing(
            fact.statement, fact_ids, refs, facts, dict(result.snapshot.values)
        )
        passed = evaluate_briefing(briefing, context)
        assert passed.violations == (), (fact_ids, passed.violations)
    swapped = fact.statement.replace("rose", "fell")
    briefing, context = _gate_briefing(
        swapped, [], refs, {}, dict(result.snapshot.values)
    )
    failed = evaluate_briefing(briefing, context)
    assert [v.code for v in failed.violations] == ["L1B_DIRECTION_MISMATCH"]


def test_ai_template_duplicate_and_system_model_fact() -> None:
    prior_row = screen_event(
        eid="evt_ai2_prior", time=_dt(29, 14), minutes={"ai": 60.0}
    )
    last_row = screen_event(eid="evt_ai2_last", time=_dt(30, 14), minutes={"ai": 120.0})
    events = [prior_row, last_row]
    aliases = personal_aliases(tuple(events))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "AI rose from 1 to 2 hours in last.",
                    "evidence": [aliases[prior_row.id], aliases[last_row.id]],
                }
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert [d.code for d in result.dropped] == ["FACT_DUPLICATE_OF_CODE"]
    system_row = screen_event(
        eid="evt_sys_only", time=_dt(30, 14), minutes={"system": 60.0}
    )
    aliases = personal_aliases((system_row,))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "system screen hours rose from 0 in prior to 1 in last.",
                    "evidence": [aliases[system_row.id]],
                }
            ),
        ),
        feed=(feed_batch(),),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [system_row], llm)
    assert [f.statement for f in result.facts] == [
        "system screen hours rose from 0 in prior to 1 in last."
    ]


def test_pr_fact_evidence_holds_only_opened_rows() -> None:
    opened = pr_event(eid="evt_pr9d_eo", time=_dt(30, 14))
    merged = pr_event(eid="evt_pr9d_em", time=_dt(30, 15), counts={"merged": 1})
    (fact,) = [f for f in _code(events=[opened, merged]) if f.family == "prs"]
    assert fact.statement == "Pull requests rose from 0 in prior to 1 in last."
    assert fact.evidence == (opened.id,)
    assert (fact.from_value, fact.to_value) == (0.0, 1.0)


def test_opened_prior_merged_last_pr_fact_falls_to_zero() -> None:
    opened = pr_event(eid="evt_pr9d_fo", time=_dt(29, 14))
    merged = pr_event(eid="evt_pr9d_fm", time=_dt(30, 15), counts={"merged": 1})
    (fact,) = [f for f in _code(events=[opened, merged]) if f.family == "prs"]
    assert fact.statement == "Pull requests fell from 1 in prior to 0 in last."
    assert fact.evidence == (opened.id,)


def test_merged_only_rows_yield_no_pr_code_fact() -> None:
    merged = pr_event(eid="evt_pr9d_nm", time=_dt(30, 15), counts={"merged": 1})
    assert [f for f in _code(events=[merged]) if f.family == "prs"] == []
    snapshot = build_metric_snapshot(AS_OF, [merged])
    assert "github.pr.count" not in snapshot.values


def test_closed_reopened_and_zero_opened_yield_no_pr_code_fact() -> None:
    rows = [
        pr_event(eid="evt_pr9d_nc", time=_dt(30, 14), counts={"closed": 1}),
        pr_event(eid="evt_pr9d_nr", time=_dt(30, 14), counts={"reopened": 1}),
        pr_event(eid="evt_pr9d_nz", time=_dt(30, 14), counts={"opened": 0}),
    ]
    assert [f for f in _code(events=rows) if f.family == "prs"] == []


def test_pr_opened_fact_passes_briefing_gate_both_citation_forms() -> None:
    from framework.briefing.gate import evaluate_briefing

    opened = pr_event(eid="evt_pr9d_go", time=_dt(30, 14))
    merged = pr_event(eid="evt_pr9d_gm", time=_dt(30, 15), counts={"merged": 1})
    events = [opened, merged]
    (fact,) = [f for f in _code(events=events) if f.family == "prs"]
    llm = RecordingLLM(personal=(personal_batch(),), feed=(feed_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    by_id = {f.id: f for f in result.facts}
    refs = [
        (metric_id, result.snapshot.values[metric_id]) for metric_id in fact.metric_ids
    ]
    briefing, context = _gate_briefing(
        fact.statement, [], refs, {}, dict(result.snapshot.values)
    )
    passed = evaluate_briefing(briefing, context)
    assert passed.violations == (), (fact.statement, passed.violations)
    kept = next(f for f in result.facts if f.statement == fact.statement)
    briefing, context = _gate_briefing(
        fact.statement,
        [kept.id],
        refs,
        {kept.id: by_id[kept.id]},
        dict(result.snapshot.values),
    )
    passed = evaluate_briefing(briefing, context)
    assert passed.violations == (), (fact.statement, passed.violations)
