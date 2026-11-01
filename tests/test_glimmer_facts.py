"""Ticket 9: allowlist, collected-at gate, taxonomy, determinism, caps, tiers."""

import pytest

from evals.glimmer_cases import (
    AS_OF,
    MUTANTS,
    SUBJECT_ID,
    WINDOW_START,
    Case,
    RecordingLLM,
    ScriptEntry,
    base_case,
    dropped_event_types,
    personal_aliases,
    personal_batch,
)
from evals.glimmer_cases import _dropped_payload as dropped_payload
from framework.glimmer.facts import FactResult, extract_facts
from framework.schemas.events import Event


def _replay(case: Case) -> tuple[FactResult, RecordingLLM]:
    llm = RecordingLLM(personal=case.personal_texts, feed=case.feed_texts)
    return extract_facts(AS_OF, SUBJECT_ID, list(case.events), llm), llm


def _by_name(prefix: str) -> Case:
    return next(c for c in MUTANTS if c.name.startswith(prefix))


def _single_dropped_case(etype: str) -> Case:
    base = base_case()
    journal = "Push activity continued in the last period"
    tier = "sensitive" if etype in ("health.daily", "app.journal") else "public"
    extra = Event.model_validate(
        {
            "id": "evt_single_drop",
            "subject_id": SUBJECT_ID,
            "source": "synthetic-drop",
            "type": etype,
            "time": "2026-10-30T12:00:00+01:00",
            "source_id": f"drop-{etype}-0",
            "data": {**dropped_payload(etype, journal), "type": etype},
            "tier": tier,
            "collected_at": "2026-10-30T13:00:00+01:00",
            "collector_version": "synthetic@0.1.0",
        }
    )
    return Case(
        name=f"single-{etype}",
        events=base.events + (extra,),
        personal_texts=base.personal_texts,
        feed_texts=base.feed_texts,
        expected_kept=base.expected_kept,
        expected_noop=base.expected_noop,
        expected_dropped=(),
        expected_snapshot=dict(base.expected_snapshot),
        expected_statements=base.expected_statements,
        expected_personal=base.expected_personal,
        expected_feed=base.expected_feed,
    )


@pytest.mark.parametrize("etype", dropped_event_types())
def test_allowlist_drops_each_non_allowed_type_byte_identical(etype: str) -> None:
    base = base_case()
    expected, expected_llm = _replay(base)
    case = _single_dropped_case(etype)
    result, llm = _replay(case)
    assert llm.prompts == expected_llm.prompts
    assert result.snapshot.values == expected.snapshot.values
    assert [f.statement for f in result.facts] == [f.statement for f in expected.facts]
    assert [f.id for f in result.facts] == [f.id for f in expected.facts]
    assert [d.code for d in result.dropped] == []


def test_allowlist_all_dropped_together_byte_identical() -> None:
    base = base_case()
    expected, expected_llm = _replay(base)
    result, llm = _replay(_by_name("F9-"))
    assert llm.prompts == expected_llm.prompts
    assert result.snapshot.values == expected.snapshot.values
    assert [f.id for f in result.facts] == [f.id for f in expected.facts]


def test_dropped_verbatim_text_does_not_drop_kept_statement() -> None:
    result, _ = _replay(_by_name("F9-"))
    assert "Push activity continued in the last period" in [
        f.statement for f in result.facts
    ]


def test_collected_at_gate_replay_identical() -> None:
    base = base_case()
    expected, expected_llm = _replay(base)
    result, llm = _replay(_by_name("F13-"))
    assert llm.prompts == expected_llm.prompts
    assert result.snapshot.values == expected.snapshot.values
    assert [f.id for f in result.facts] == [f.id for f in expected.facts]
    assert result.prompt_hash == expected.prompt_hash
    assert result.cycle_id == expected.cycle_id


def test_truncated_no_retry() -> None:
    result, llm = _replay(_by_name("F14-"))
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_TRUNCATED"
    assert personal.attempts == 1
    assert personal.raw_valid is False
    assert len(llm.personal_prompts) == 1


def test_unavailable_no_retry() -> None:
    result, llm = _replay(_by_name("F15-"))
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_UNAVAILABLE"
    assert personal.attempts == 1
    assert len(llm.personal_prompts) == 1


def test_stub_type_error_raises() -> None:
    llm = RecordingLLM(personal=(ScriptEntry(raise_error="type"),))
    with pytest.raises(TypeError):
        extract_facts(AS_OF, SUBJECT_ID, list(base_case().events), llm)


def test_invalid_twice_noop() -> None:
    result, llm = _replay(_by_name("F7-"))
    personal, feed = result.passes
    assert personal.noop_reason == "NOOP_INVALID_LLM_OUTPUT"
    assert personal.attempts == 2
    assert personal.raw_valid is False
    assert len(llm.personal_prompts) == 2
    assert llm.personal_prompts[1].startswith(llm.personal_prompts[0])
    assert "Your previous answer was not valid." in llm.personal_prompts[1]
    assert feed.kept == 1


def test_repair_retry_then_valid() -> None:
    result, llm = _replay(_by_name("F8-"))
    personal, _ = result.passes
    assert personal.kept == 1
    assert personal.attempts == 2
    assert personal.raw_valid is True
    assert len(llm.personal_prompts) == 2
    assert "Your previous answer was not valid." in llm.personal_prompts[1]


def test_deterministic_replay_identical() -> None:
    case = base_case()
    first, _ = _replay(case)
    second, _ = _replay(case)
    assert first == second
    assert first.prompt_hash == second.prompt_hash
    assert [f.id for f in first.facts] == [f.id for f in second.facts]


def test_unknown_alias_drops() -> None:
    result, _ = _replay(_by_name("F1-"))
    assert [d.code for d in result.dropped] == ["FACT_EVIDENCE_UNKNOWN"]
    assert result.facts == ()


def test_alias_in_statement_drops() -> None:
    result, _ = _replay(_by_name("F18-"))
    assert [d.code for d in result.dropped] == [
        "FACT_ALIAS_IN_STATEMENT",
        "FACT_ALIAS_IN_STATEMENT",
    ]
    assert result.facts == ()


def test_tier_minted_as_highest_evidence_tier() -> None:
    from evals.glimmer_cases import KNOWN_GOOD

    g1 = next(c for c in KNOWN_GOOD if c.name == "G1-base")
    result, _ = _replay(g1)
    assert [f.tier for f in result.facts] == ["private", "public", "public"]
    g5 = next(c for c in KNOWN_GOOD if c.name == "G5-minted-tier")
    result, _ = _replay(g5)
    assert [f.tier for f in result.facts] == ["private"]


def test_max_facts_cap_overflow() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event

    push = push_event(eid="evt_cap_push", time=dt(30, 14))
    aliases = personal_aliases((push,))
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
            "statement": f"Steady maintenance work continued quietly {w}",
            "evidence": [aliases[push.id]],
        }
        for w in words
    ]
    llm = RecordingLLM(personal=(personal_batch(*drafts),))
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert len(result.facts) == 12
    assert [d.code for d in result.dropped] == ["FACT_OVER_LIMIT"]
    personal, _ = result.passes
    assert personal.kept == 12


def test_prompt_event_cap_uses_most_recent_200() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event as push

    events = [
        push(eid=f"evt_cap_{i:03d}", time=dt(28 + (i // 80), 14 + (i % 8), i % 60))
        for i in range(205)
    ]
    events = sorted(events, key=lambda e: (e.time, e.id))
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    (prompt,) = llm.personal_prompts
    assert prompt.count('"alias":"e') == 200
    assert '"alias":"e200"' in prompt
    assert '"alias":"e201"' not in prompt
    assert events[0].time.isoformat() not in prompt
    assert events[5].time.isoformat() in prompt
    assert result.passes[0].noop_reason == "NOOP_MODEL_RETURNED_NO_FACTS"


def test_prompt_literal_braces_unchanged() -> None:
    from framework.glimmer.prompt import build_feed_prompt, build_personal_prompt

    base = base_case()
    from framework.glimmer.metrics import build_period_rollup
    from framework.schemas.events import Event

    tricky = Event.model_validate(
        {
            "id": "evt_brace_push",
            "subject_id": SUBJECT_ID,
            "source": "github",
            "type": "github.push",
            "time": "2026-10-30T14:00:00+01:00",
            "source_id": "push-brace",
            "data": {
                "type": "github.push",
                "repo": "synthetic/repo",
                "counts": {"{period_json}": 1},
            },
            "tier": "public",
            "collected_at": "2026-10-30T15:00:00+01:00",
            "collector_version": "synthetic@0.1.0",
        }
    )
    snapshot_result, _ = _replay(base)
    rollup = build_period_rollup(AS_OF, list(base.events))
    personal = build_personal_prompt(
        AS_OF, WINDOW_START, snapshot_result.snapshot, rollup, [("e1", tricky)]
    )
    assert "{period_json}" in personal
    feed_item = Event.model_validate(
        {
            "id": "evt_brace_feed",
            "subject_id": SUBJECT_ID,
            "source": "feed",
            "type": "feed.item",
            "time": "2026-10-30T09:00:00+01:00",
            "source_id": "hf:brace@2026-10-30",
            "data": {
                "type": "feed.item",
                "title": "Notes on {feed_lines} handling",
                "url": "https://example.invalid/hf-brace",
                "source": "hf",
                "score": 1.0,
            },
            "tier": "public",
            "collected_at": "2026-10-30T10:00:00+01:00",
            "collector_version": "synthetic@0.1.0",
        }
    )
    feed_prompt = build_feed_prompt([("f1", feed_item)])
    assert "{feed_lines}" in feed_prompt


def test_empty_content_length_is_truncated_no_retry() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event

    push = push_event(eid="evt_empty_len", time=dt(30, 14))
    llm = RecordingLLM(personal=(Entry(text="", finish_reason="length"),))
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_TRUNCATED"
    assert personal.attempts == 1
    assert [a.content for a in result.responses] == [""]


def test_duplicate_aliases_do_not_inflate_cited_count() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases, push_event

    push = push_event(eid="evt_dup_push", time=dt(30, 14))
    aliases = personal_aliases((push,))
    llm = RecordingLLM(
        personal=(
            Entry(
                text=personal_batch(
                    {
                        "statement": "Exactly 7 pushes landed in the last period",
                        "evidence": [aliases[push.id]] * 7,
                    }
                ).text
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert [d.code for d in result.dropped] == ["FACT_NUMBER_UNBACKED"]
    assert result.facts == ()


def test_kept_evidence_has_no_duplicates() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases, push_event

    push = push_event(eid="evt_nodup_push", time=dt(30, 14))
    aliases = personal_aliases((push,))
    llm = RecordingLLM(
        personal=(
            Entry(
                text=personal_batch(
                    {
                        "statement": "1 push continued in the last period",
                        "evidence": [aliases[push.id]] * 2,
                    }
                ).text
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert len(result.facts) == 1
    assert list(result.facts[0].evidence) == [push.id]


def test_blank_statement_takes_repair_retry() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases, push_event

    push = push_event(eid="evt_blank_stmt", time=dt(30, 14))
    aliases = personal_aliases((push,))
    llm = RecordingLLM(
        personal=(
            Entry(
                text=personal_batch(
                    {
                        "statement": "   ",
                        "evidence": [aliases[push.id]],
                    }
                ).text
            ),
            personal_batch(
                {
                    "statement": "1 push continued in the last period",
                    "evidence": [aliases[push.id]],
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert len(result.facts) == 1
    personal, _ = result.passes
    assert personal.attempts == 2
    assert personal.raw_valid is True


def test_blank_topic_takes_repair_retry() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import feed_aliases, feed_batch, feed_event

    item = feed_event(
        eid="evt_blank_topic",
        item="item-blank",
        day="2026-10-30",
        time=dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    feeds = feed_aliases((item,))
    llm = RecordingLLM(
        feed=(
            Entry(text=feed_batch({"evidence": [feeds[item.id]], "topic": "   "}).text),
            Entry(
                text=feed_batch(
                    {"evidence": [feeds[item.id]], "topic": "neural pruning tools"}
                ).text
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    assert [f.statement for f in result.facts] == [
        "1 feed items about neural pruning tools"
    ]
    _, feed = result.passes
    assert feed.attempts == 2


def test_topic_internal_whitespace_collapses_to_one_line() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import feed_aliases, feed_batch, feed_event

    item = feed_event(
        eid="evt_ws_topic",
        item="item-ws",
        day="2026-10-30",
        time=dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    feeds = feed_aliases((item,))
    llm = RecordingLLM(
        feed=(
            feed_batch(
                {"evidence": [feeds[item.id]], "topic": "neural\npruning\ttools"}
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    assert [f.statement for f in result.facts] == [
        "1 feed items about neural pruning tools"
    ]


def test_window_includes_start_excludes_as_of() -> None:
    from evals.glimmer_cases import personal_batch, push_event

    opening = push_event(eid="evt_edge_start", time=WINDOW_START)
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [opening], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_MODEL_RETURNED_NO_FACTS"
    assert personal.attempts == 1
    assert result.snapshot.values.get("period.earlier.pushes") == 1.0
    assert len(llm.personal_prompts) == 1

    closing = push_event(eid="evt_edge_end", time=AS_OF)
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [closing], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_NO_PERSONAL_EVENTS"
    assert personal.attempts == 0
    assert "github.push.count" not in result.snapshot.values
    assert llm.prompts == []


def test_other_subject_row_reaches_neither_prompt_nor_snapshot() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_batch, push_event, screen_event

    mine = push_event(eid="evt_mine_push", time=dt(30, 14))
    foreign_screen = screen_event(
        eid="evt_foreign_screen",
        time=dt(30, 15),
        minutes={"ForeignCat9q": 120.0},
    )
    foreign_screen = foreign_screen.model_copy(
        update={"subject_id": "subject-2", "source_id": "foreign-src-9q"}
    )
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [mine, foreign_screen], llm)
    assert result.snapshot.values.get("github.push.count") == 1.0
    assert "screen_hours.ForeignCat9q" not in result.snapshot.values
    assert len(llm.personal_prompts) == 1
    (prompt,) = llm.personal_prompts
    assert "ForeignCat9q" not in prompt
    assert "foreign-src-9q" not in prompt
    assert "subject-2" not in prompt
    assert '"alias":"e2"' not in prompt


def test_duplicate_statement_and_evidence_drops_second() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases, personal_batch, push_event

    push = push_event(eid="evt_dupe_push", time=dt(30, 14))
    aliases = personal_aliases((push,))
    draft = {
        "statement": "1 push continued in the last period",
        "evidence": [aliases[push.id]],
    }
    llm = RecordingLLM(personal=(personal_batch(draft, draft),))
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    assert len(result.facts) == 1
    assert [d.code for d in result.dropped] == ["FACT_DUPLICATE"]


def test_duplicate_with_swapped_evidence_order_drops_second() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_aliases, personal_batch, push_event

    first = push_event(eid="evt_swap_a", time=dt(30, 14))
    second = push_event(eid="evt_swap_b", time=dt(30, 15))
    aliases = personal_aliases((first, second))
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "2 pushes continued in the last period",
                    "evidence": [aliases[first.id], aliases[second.id]],
                },
                {
                    "statement": "2 pushes continued in the last period",
                    "evidence": [aliases[second.id], aliases[first.id]],
                },
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [first, second], llm)
    assert len(result.facts) == 1
    assert [d.code for d in result.dropped] == ["FACT_DUPLICATE"]


def test_feed_cap_keeps_seven_per_source_with_tiebreaks() -> None:
    import json as json_lib

    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import feed_batch, feed_event

    rows = []
    for i in range(8):
        rows.append(
            feed_event(
                eid=f"evt_cap_qa_{i}",
                item=f"qa-{i}",
                day="2026-10-30",
                time=dt(30, 9 + (i // 2), (i % 2) * 10),
                title=f"Qa title number {i}",
                source="qa",
                score=float(800 - 100 * i) if i < 6 else 200.0,
            )
        )
    # Scores: 800..300, then two 200s at different times; earlier drops.
    rows.append(
        feed_event(
            eid="evt_cap_qb_hi",
            item="qb-hi",
            day="2026-10-30",
            time=dt(30, 9),
            title="Qb top title here",
            source="qb",
            score=0.9,
        )
    )
    for i in range(5):
        rows.append(
            feed_event(
                eid=f"evt_cap_qb_{i}",
                item=f"qb-{i}",
                day="2026-10-30",
                time=dt(30, 10 + i),
                title=f"Qb title number {i}",
                source="qb",
                score=0.8 - 0.1 * i,
            )
        )
    # Lowest qb score (0.1) is shared by the two rows below at the same
    # instant; the higher id drops.
    rows.append(
        feed_event(
            eid="evt_cap_qb_tie_b",
            item="qb-tie-b",
            day="2026-10-30",
            time=dt(30, 20),
            title="Qb tie dropped id title",
            source="qb",
            score=0.1,
        )
    )
    rows.append(
        feed_event(
            eid="evt_cap_qb_tie_a",
            item="qb-tie-a",
            day="2026-10-30",
            time=dt(30, 20),
            title="Qb tie kept id title",
            source="qb",
            score=0.1,
        )
    )
    llm = RecordingLLM(feed=(feed_batch(),))
    extract_facts(AS_OF, SUBJECT_ID, rows, llm)
    (prompt,) = llm.feed_prompts
    body = prompt.split("<<<FEED_DATA\n", 1)[1].split("\nFEED_DATA>>>", 1)[0]
    titles = [json_lib.loads(line)["title"] for line in body.splitlines()]
    assert len(titles) == 14
    assert "Qa title number 6" not in titles
    assert "Qa title number 7" in titles
    assert "Qb tie dropped id title" not in titles
    assert "Qb tie kept id title" in titles
    assert "Qb top title here" in titles


def test_topic_citing_one_item_twice_counts_one() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import feed_aliases, feed_batch, feed_event

    item = feed_event(
        eid="evt_double_cite",
        item="item-double",
        day="2026-10-30",
        time=dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    feeds = feed_aliases((item,))
    llm = RecordingLLM(
        feed=(
            feed_batch(
                {
                    "evidence": [feeds[item.id], feeds[item.id]],
                    "topic": "neural pruning tools",
                }
            ),
        )
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    assert [f.statement for f in result.facts] == [
        "1 feed items about neural pruning tools"
    ]


def test_prompts_carry_no_store_bytes() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import (
        feed_batch,
        feed_event,
        personal_batch,
        push_event,
    )

    push = push_event(eid="evt_bytes_push", time=dt(30, 14))
    push = push.model_copy(
        update={
            "id": "evt-bytes-unique-9q",
            "source_id": "push-bytes-unique-9q",
            "collected_at": dt(30, 7),
        }
    )
    item = feed_event(
        eid="evt_bytes_feed",
        item="item-bytes-9q",
        day="2026-10-30",
        time=dt(30, 9),
        title="Ordinary synthetic title words here",
    )
    item = item.model_copy(
        update={
            "source_id": "hf:item-bytes-9q@2026-10-30",
            "subject_id": SUBJECT_ID,
        }
    )
    llm = RecordingLLM(
        personal=(
            personal_batch(
                {
                    "statement": "1 push continued in the last period",
                    "evidence": ["e1"],
                }
            ),
        ),
        feed=(feed_batch(),),
    )
    extract_facts(AS_OF, SUBJECT_ID, [push, item], llm)
    (personal_prompt,) = llm.personal_prompts
    for distinctive in (
        "evt-bytes-unique-9q",
        "push-bytes-unique-9q",
        "2026-10-30T07:00:00+01:00",
        SUBJECT_ID,
    ):
        assert distinctive not in personal_prompt, distinctive
    assert '"tier"' not in personal_prompt
    (feed_prompt,) = llm.feed_prompts
    assert "https://example.invalid/hf-item-bytes-9q" not in feed_prompt
    assert SUBJECT_ID not in feed_prompt


def test_utc_times_render_in_as_of_offset() -> None:
    from datetime import UTC, datetime

    from evals.glimmer_cases import make_event
    from framework.glimmer.metrics import build_metric_snapshot, build_period_rollup
    from framework.glimmer.prompt import build_personal_prompt

    block = make_event(
        eid="evt_utc_block",
        source="calendar-personal",
        source_id="utc-1@20261030T120000@seq1",
        type="calendar.event.created",
        time=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        data={
            "start": "2026-10-30T12:00:00+00:00",
            "end": "2026-10-30T13:00:00+00:00",
            "busy": True,
            "category": "personal",
            "tags": [],
            "is_new": False,
        },
        tier="private",
    )
    snapshot = build_metric_snapshot(AS_OF, [block])
    rollup = build_period_rollup(AS_OF, [block])
    prompt = build_personal_prompt(
        AS_OF, WINDOW_START, snapshot, rollup, [("e1", block)]
    )
    assert "2026-10-30T13:00:00+01:00" in prompt
    assert "2026-10-30T14:00:00+01:00" in prompt
    assert "12:00:00+00:00" not in prompt
    assert "13:00:00+00:00" not in prompt


def test_snapshot_rounds_to_two_places_in_prompt_only() -> None:
    import json as json_lib

    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import personal_batch, screen_event

    row = screen_event(
        eid="evt_round_row", time=dt(30, 14), minutes={"Comms/Chat": 76.0}
    )
    llm = RecordingLLM(personal=(personal_batch(),))
    result = extract_facts(AS_OF, SUBJECT_ID, [row], llm)
    assert result.snapshot.values["screen_hours.Comms/Chat"] == 76.0 / 60.0
    (prompt,) = llm.personal_prompts
    metrics_block = prompt.split("METRICS (JSON):\n", 1)[1].split("\n\nPERIODS", 1)[0]
    assert json_lib.loads(metrics_block)["screen_hours.Comms/Chat"] == 1.27
    assert '"screen_hours.Comms/Chat":1.27' in prompt
    assert '"screen_hours":{"Comms/Chat":1.27}' in prompt


def test_deeply_nested_brackets_are_invalid() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event

    push = push_event(eid="evt_deep_brackets", time=dt(30, 14))
    llm = RecordingLLM(
        personal=(Entry(text="[" * 100000), Entry(text="[" * 100000)),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_INVALID_LLM_OUTPUT"
    assert personal.attempts == 2


def test_empty_content_other_reason_takes_repair_retry() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event

    push = push_event(eid="evt_empty_retry", time=dt(30, 14))
    llm = RecordingLLM(
        personal=(Entry(text=""), Entry(text="")),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [push], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_INVALID_LLM_OUTPUT"
    assert personal.attempts == 2


def test_failed_personal_pass_keeps_feed_facts() -> None:
    result, _ = _replay(_by_name("F7-"))
    assert len(result.facts) == 1
    assert result.noop_reason is None


_LIVE_CONTENT = (
    '{"facts": [\n'
    '  {"statement": "Github pushes decreased from 3 in earlier to 1 in prior'
    ' and to 0 in last.", "evidence": ["e6", "e14", "e17", "e22"]},\n'
    '  {"statement": "Work/Programming screen hours decreased from 7.0 in earlier'
    ' to 4.75 in prior.", "evidence": ["e11", "e13", "e15", "e16", "e19",'
    ' "e20", "e21", "e23"]},\n'
    '  {"statement": "Work/Programming screen hours decreased from 4.75 in prior'
    ' to 1.75 in last.", "evidence": ["e19", "e20", "e21", "e23", "e42",'
    ' "e43", "e44"]},\n'
    '  {"statement": "Comms/Chat screen hours increased from 1.27 in prior'
    ' to 3.45 in last.", "evidence": ["e28", "e29", "e30", "e42", "e43",'
    ' "e44"]},\n'
    '  {"statement": "In prior period, 1 calendar block with tag iki-deep was'
    ' cancelled and 1 github push occurred.", "evidence": ["e27", "e22"]}\n'
    "]}"
)

# (fixture alias, type, time, data) transcribed from the live-run fixture.
_LIVE_ROWS: tuple[tuple[str, str, str, dict[str, object]], ...] = (
    (
        "e1",
        "screen.hour",
        "2026-10-28T14:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e2",
        "screen.hour",
        "2026-10-28T15:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e3",
        "screen.hour",
        "2026-10-28T16:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e4",
        "screen.hour",
        "2026-10-28T17:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e5",
        "screen.hour",
        "2026-10-28T18:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e6",
        "github.push",
        "2026-10-28T18:30:00+01:00",
        {"repo": "example-user/demo-repo", "counts": {"commits": 2}},
    ),
    (
        "e7",
        "screen.hour",
        "2026-10-28T19:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 10, "Work/Programming": 40},
        },
    ),
    (
        "e8",
        "calendar.event.created",
        "2026-10-28T20:00:00+01:00",
        {
            "busy": True,
            "category": "personal",
            "end": "2026-10-28T21:00:00+01:00",
            "is_new": False,
            "start": "2026-10-28T20:00:00+01:00",
            "tags": ["iki-family"],
        },
    ),
    (
        "e9",
        "screen.hour",
        "2026-10-28T21:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 6, "Media/Video": 5}},
    ),
    (
        "e10",
        "screen.hour",
        "2026-10-28T22:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 6, "Media/Video": 5}},
    ),
    (
        "e11",
        "screen.hour",
        "2026-10-29T09:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e12",
        "calendar.event.created",
        "2026-10-29T10:00:00+01:00",
        {
            "busy": True,
            "category": "work",
            "end": "2026-10-29T13:00:00+01:00",
            "is_new": False,
            "start": "2026-10-29T10:00:00+01:00",
            "tags": ["iki-deep"],
        },
    ),
    (
        "e13",
        "screen.hour",
        "2026-10-29T10:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e14",
        "github.push",
        "2026-10-29T11:00:00+01:00",
        {"repo": "example-user/demo-repo", "counts": {"commits": 3}},
    ),
    (
        "e15",
        "screen.hour",
        "2026-10-29T11:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e16",
        "screen.hour",
        "2026-10-29T12:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e17",
        "github.push",
        "2026-10-29T12:30:00+01:00",
        {"repo": "example-user/demo-repo", "counts": {"commits": 1}},
    ),
    (
        "e18",
        "calendar.event.created",
        "2026-10-29T15:00:00+01:00",
        {
            "busy": True,
            "category": "work",
            "end": "2026-10-29T18:00:00+01:00",
            "is_new": False,
            "start": "2026-10-29T15:00:00+01:00",
            "tags": ["iki-deep"],
        },
    ),
    (
        "e19",
        "screen.hour",
        "2026-10-29T15:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e20",
        "screen.hour",
        "2026-10-29T16:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e21",
        "screen.hour",
        "2026-10-29T17:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e22",
        "github.push",
        "2026-10-29T17:40:00+01:00",
        {"repo": "example-user/demo-repo", "counts": {"commits": 4}},
    ),
    (
        "e23",
        "screen.hour",
        "2026-10-29T18:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e24",
        "github.pr",
        "2026-10-29T18:10:00+01:00",
        {"repo": "example-user/demo-repo", "counts": {"opened": 1}},
    ),
    (
        "e25",
        "screen.hour",
        "2026-10-29T19:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 8, "Work/Programming": 45},
        },
    ),
    (
        "e26",
        "calendar.event.created",
        "2026-10-30T09:00:00+01:00",
        {
            "busy": True,
            "category": "work",
            "end": "2026-10-30T09:30:00+01:00",
            "is_new": False,
            "start": "2026-10-30T09:00:00+01:00",
            "tags": [],
        },
    ),
    (
        "e27",
        "calendar.event.cancelled",
        "2026-10-30T10:00:00+01:00",
        {
            "busy": True,
            "category": "work",
            "end": "2026-10-30T12:00:00+01:00",
            "is_new": False,
            "start": "2026-10-30T10:00:00+01:00",
            "tags": ["iki-deep"],
        },
    ),
    (
        "e28",
        "screen.hour",
        "2026-10-30T10:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e29",
        "screen.hour",
        "2026-10-30T11:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e30",
        "screen.hour",
        "2026-10-30T12:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e31",
        "screen.hour",
        "2026-10-30T13:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e32",
        "screen.hour",
        "2026-10-30T14:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e33",
        "screen.hour",
        "2026-10-30T15:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 12, "Work/Programming": 20},
        },
    ),
    (
        "e34",
        "screen.hour",
        "2026-10-30T16:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e35",
        "screen.hour",
        "2026-10-30T17:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e36",
        "screen.hour",
        "2026-10-30T18:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e37",
        "screen.hour",
        "2026-10-30T19:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e38",
        "screen.hour",
        "2026-10-30T20:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e39",
        "screen.hour",
        "2026-10-30T21:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e40",
        "screen.hour",
        "2026-10-30T22:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e41",
        "screen.hour",
        "2026-10-30T23:00:00+01:00",
        {"device": "mac", "minutes_by_category": {"Comms/Chat": 12, "Media/Video": 30}},
    ),
    (
        "e42",
        "screen.hour",
        "2026-10-31T10:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 25, "Work/Programming": 15},
        },
    ),
    (
        "e43",
        "screen.hour",
        "2026-10-31T11:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 25, "Work/Programming": 15},
        },
    ),
    (
        "e44",
        "screen.hour",
        "2026-10-31T12:00:00+01:00",
        {
            "device": "mac",
            "minutes_by_category": {"Comms/Chat": 25, "Work/Programming": 15},
        },
    ),
)


def _live_table_events() -> list[Event]:
    """Real ``Event`` objects for the live-run fixture rows above."""
    from datetime import UTC, datetime

    events: list[Event] = []
    for index, (alias, etype, time_iso, data) in enumerate(_LIVE_ROWS, start=1):
        moment = datetime.fromisoformat(time_iso)
        utc_iso = moment.astimezone(UTC).isoformat()
        if etype.startswith("calendar.event."):
            source, tier = "calendar-personal", "private"
            source_id = f"uid-{index}@{utc_iso}@seq1"
            if etype == "calendar.event.cancelled":
                source_id += "#cancelled"
        elif etype == "screen.hour":
            source, tier = "activitywatch", "private"
            source_id = f"mac:{utc_iso}:d{index}"
        else:
            source, tier = "github", "public"
            source_id = str(7000 + index)
        payload = dict(data)
        payload["type"] = etype
        events.append(
            Event.model_validate(
                {
                    "id": f"evt_{index:04d}",
                    "subject_id": SUBJECT_ID,
                    "source": source,
                    "type": etype,
                    "time": time_iso,
                    "source_id": source_id,
                    "data": payload,
                    "tier": tier,
                    "collected_at": "2026-10-31T12:59:00+01:00",
                    "collector_version": "synthetic-live@0.1.0",
                }
            )
        )
        assert alias == f"e{index}", alias
    return events


def test_live_model_output_all_five_kept() -> None:
    import json as json_lib

    from evals.glimmer_cases import ScriptEntry as Entry

    events = _live_table_events()
    llm = RecordingLLM(personal=(Entry(text=_LIVE_CONTENT),))
    result = extract_facts(AS_OF, SUBJECT_ID, events, llm)
    assert len(result.facts) == 5
    assert result.dropped == ()
    assert result.is_noop is False
    assert [f.tier for f in result.facts] == [
        "public",
        "private",
        "private",
        "private",
        "private",
    ]
    # Prompt aliases name the same rows as the fixture aliases.
    (prompt,) = llm.personal_prompts
    body = prompt.split("<<<EVENT_DATA\n", 1)[1].split("\nEVENT_DATA>>>", 1)[0]
    by_alias = {
        json_lib.loads(line)["alias"]: json_lib.loads(line)
        for line in body.splitlines()
    }
    assert len(by_alias) == 44
    for index, (alias, etype, time_iso, _) in enumerate(_LIVE_ROWS, start=1):
        assert by_alias[alias]["type"] == etype, alias
        assert by_alias[alias]["time"] == time_iso, alias


def test_zoned_as_of_excludes_row_72h30m_old() -> None:
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from evals.glimmer_cases import push_event

    madrid = ZoneInfo("Europe/Madrid")
    as_of = datetime(2026, 10, 26, 12, tzinfo=madrid)
    stale_time = (as_of.astimezone(UTC) - timedelta(hours=72, minutes=30)).astimezone(
        madrid
    )
    stale = push_event(
        eid="evt_dst_stale",
        time=stale_time,
        collected_at=as_of - timedelta(hours=1),
    )
    llm = RecordingLLM(personal=(), feed=())
    result = extract_facts(as_of, SUBJECT_ID, [stale], llm)
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_NO_PERSONAL_EVENTS"
    assert personal.attempts == 0
    assert "github.push.count" not in result.snapshot.values
    assert llm.prompts == []


def test_live_table_zero_keep_statements() -> None:
    from framework.glimmer.checks import check_fact
    from framework.glimmer.metrics import build_metric_snapshot, select_winners

    events = _live_table_events()
    winners = select_winners(events)
    assert len(winners) == 44
    winning_ids = frozenset(e.id for e in winners)
    snapshot = build_metric_snapshot(AS_OF, winners)
    by_alias = {f"e{i + 1}": e.id for i, e in enumerate(events)}

    def _check(statement: str, aliases: list[str]) -> str | None:
        ids = [by_alias[a] for a in aliases]
        return check_fact(
            statement,
            ids,
            known_by_id={e.id: e for e in events},
            winning_ids=winning_ids,
            winners=list(winners),
            snapshot=snapshot,
            feed_titles=[],
            as_of=AS_OF,
            window_start=WINDOW_START,
        )

    last_media = [f"e{i}" for i in range(34, 42)]
    assert (
        _check(
            "Media/Video screen hours rose from 0 in prior to 4.0 in last.", last_media
        )
        is None
    )
    assert (
        _check(
            "Media/Video screen hours rose from 0.0 in prior to 4.0 in last.",
            last_media,
        )
        is None
    )
    assert (
        _check("Media/Video went from 0 hours in prior to 4 hours in last.", last_media)
        is None
    )
    assert (
        _check(
            "Cancelled iki-deep blocks rose from 0 in earlier to 1 in prior.", ["e27"]
        )
        is None
    )
    assert (
        _check("Cancelled iki-deep blocks fell from 1 in prior to 0 in last.", ["e27"])
        is None
    )
    assert _check("Github PRs rose from 0 in earlier to 1 in prior.", ["e24"]) is None
    assert (
        _check("iki-deep calendar hours fell from 3.0 in prior to 0 in last.", ["e18"])
        is None
    )


def test_empty_window_stub_never_called() -> None:
    from evals.glimmer_cases import KNOWN_GOOD

    g4 = next(c for c in KNOWN_GOOD if c.name == "G4-empty-window")
    result, llm = _replay(g4)
    assert llm.prompts == []
    assert result.is_noop is True
    assert result.noop_reason == "NOOP_NO_FACTS"
    assert result.prompt_hash


def test_feed_deeply_nested_brackets_are_invalid() -> None:
    from evals.glimmer_cases import ScriptEntry as Entry
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import feed_event

    item = feed_event(
        eid="evt_feed_deep_brackets",
        item="item-feed-deep",
        day="2026-10-30",
        time=dt(30, 9),
        title="Synthetic transformer pruning benchmark results",
    )
    llm = RecordingLLM(
        feed=(Entry(text="[" * 100000), Entry(text="[" * 100000)),
    )
    result = extract_facts(AS_OF, SUBJECT_ID, [item], llm)
    _, feed = result.passes
    assert feed.noop_reason == "NOOP_INVALID_LLM_OUTPUT"
    assert feed.attempts == 2


def test_unavailable_latency_reaches_pass_total() -> None:
    from evals.glimmer_cases import _dt as dt
    from evals.glimmer_cases import push_event
    from framework.glimmer.facts import LLMResponse, LLMUnavailableError

    push = push_event(eid="evt_err_ms_push", time=dt(30, 14))

    class _Raise:
        def complete(self, prompt: str) -> LLMResponse:
            raise LLMUnavailableError("timeout", latency_ms=1234)

    result = extract_facts(AS_OF, SUBJECT_ID, [push], _Raise())
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_UNAVAILABLE"
    assert personal.attempts == 1
    assert personal.latency_ms == 1234

    class _InvalidThenRaise:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt: str) -> LLMResponse:
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    text="not json",
                    model_id="m",
                    latency_ms=100,
                    finish_reason="stop",
                    completion_tokens=None,
                )
            raise LLMUnavailableError("timeout", latency_ms=1234)

    result = extract_facts(AS_OF, SUBJECT_ID, [push], _InvalidThenRaise())
    personal, _ = result.passes
    assert personal.noop_reason == "NOOP_LLM_UNAVAILABLE"
    assert personal.attempts == 2
    assert personal.latency_ms == 1334
