"""Ticket 11: meta-eval over the 37 proposal cases (P1-P37).

Each case replays its scripted outcomes through ``propose`` and asserts the
exact kind, attempt count, first-attempt codes, and commitment.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from evals.proposal_cases import (
    CASES,
    CASES_BY_NAME,
    check_case_names,
    first_codes,
    result_commitment,
    run_case,
    run_hour_case,
    run_refusal_case,
)


def test_case_count_is_37() -> None:
    check_case_names()
    assert len(CASES) == 37


def _check(case_name: str) -> None:
    case = CASES_BY_NAME[case_name]
    result = run_case(case)
    assert result.kind == case.expected_kind, (result.kind, result.reason_codes)
    assert len(result.attempts) == case.expected_attempts, [
        (attempt.number, attempt.codes) for attempt in result.attempts
    ]
    assert first_codes(result) == case.expected_codes, [
        attempt.codes for attempt in result.attempts
    ]
    assert result_commitment(result) == case.expected_commitment


def test_case_P01() -> None:
    _check("P1")
    result = run_case(CASES_BY_NAME["P1"])
    assert result.kind == "proposal"
    assert result.briefing is not None
    assert result.reason_codes == ()
    assert result.prompt_hash != ""
    assert len(result.attempts[0].codes) == 0
    assert result.attempts[0].parsed_ok is True
    assert result.attempts[0].blocked is False


def test_case_P02() -> None:
    _check("P2")


def test_case_P02_retry_feedback() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P2"]
    client = build_client(case)
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=client,
        models=MODELS,
        policy=case.policy,
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert len(client.requests) == 2
    retry_text = client.requests[1].prompt
    assert "L1B_UNKNOWN_FACT" in retry_text
    assert "sections[overall_state].claims[c-overall_state-1]" in retry_text
    assert "c-working-2" in retry_text
    assert "complete new draft" in retry_text
    assert "The evening walk covered the garden loop" not in retry_text


def test_case_P03() -> None:
    _check("P3")
    result = run_case(CASES_BY_NAME["P3"])
    assert result.fallback is not None
    assert "FALLBACK_AFTER_GATE_FAILURE" in result.fallback.reason_codes
    assert "L1B_UNKNOWN_METRIC" in result.fallback.reason_codes
    assert result.fallback.commitment.id == "cm-builder-notes"


def test_case_P04() -> None:
    _check("P4")
    result = run_case(CASES_BY_NAME["P4"])
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_UNPARSEABLE",)
    assert all(attempt.parsed_ok is False for attempt in result.attempts)


def test_case_P05() -> None:
    _check("P5")
    result = run_case(CASES_BY_NAME["P5"])
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_MODEL_UNAVAILABLE",)
    assert result.attempts[0].codes == (("MODEL_UNAVAILABLE", "status 500"),)


def test_case_P06() -> None:
    _check("P6")
    result = run_case(CASES_BY_NAME["P6"])
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED",)
    assert result.attempts[0].blocked is True


def test_case_P07() -> None:
    _check("P7")
    result = run_case(CASES_BY_NAME["P7"])
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED",)


def test_case_P08() -> None:
    _check("P8")
    result = run_case(CASES_BY_NAME["P8"])
    assert result.reason_codes == ("NOOP_NO_FREE_HOUR",)
    assert result.hour is None


def test_case_P09() -> None:
    _check("P9")
    result = run_case(CASES_BY_NAME["P9"])
    assert result.attempts[0].codes == (
        ("L1_ACTION_NOT_COMMITTED", "sections[actions].actions[act-1]"),
    )


def test_case_P10() -> None:
    _check("P10")


def test_case_P11() -> None:
    from framework.proposal.core import ContributorModelRefused

    case = CASES_BY_NAME["P11"]
    exc = run_refusal_case(case)
    assert isinstance(exc, ContributorModelRefused)


def test_case_P12() -> None:
    from evals.proposal_cases import build_client, first_codes, result_commitment

    p1_client = build_client(CASES_BY_NAME["P1"])
    p12_client = build_client(CASES_BY_NAME["P12"])
    p1_result = run_case(CASES_BY_NAME["P1"], p1_client)
    p12_result = run_case(CASES_BY_NAME["P12"], p12_client)
    assert p12_result.kind == p1_result.kind == "proposal"
    assert len(p12_result.attempts) == len(p1_result.attempts) == 1
    assert first_codes(p12_result) == first_codes(p1_result) == ()
    assert result_commitment(p12_result) == result_commitment(p1_result)
    p1_schema = p1_client.requests[0].response_schema
    p12_schema = p12_client.requests[0].response_schema
    import json

    assert json.dumps(p1_schema, sort_keys=True) == json.dumps(
        p12_schema, sort_keys=True
    )
    prompt = p12_client.requests[0].prompt
    for marker in (
        "<<<METRIC_DATA",
        "METRIC_DATA>>>",
        "<<<FACT_DATA",
        "FACT_DATA>>>",
        "<<<COMMITMENT_DATA",
        "COMMITMENT_DATA>>>",
    ):
        assert prompt.count(marker) == 1, marker


def test_case_P13() -> None:
    case = CASES_BY_NAME["P13"]
    hour = run_hour_case(case)
    assert hour is not None
    assert hour.start.isoformat() == "2026-10-31T15:15:00+01:00"
    assert hour.end.isoformat() == "2026-10-31T16:15:00+01:00"


def test_case_P14() -> None:
    _check("P14")
    result = run_case(CASES_BY_NAME["P14"])
    assert result.reason_codes == ("NOOP_NO_ELIGIBLE_COMMITMENT",)


def test_case_P15() -> None:
    _check("P15")
    result = run_case(CASES_BY_NAME["P15"])
    assert result.fallback is not None
    assert "L1B_UNKNOWN_METRIC" in result.fallback.reason_codes


def test_case_P16() -> None:
    _check("P16")
    result = run_case(CASES_BY_NAME["P16"])
    assert result.briefing is not None
    assert result.briefing.parent_briefing_id == "brf-builder-parent"
    since_last = next(s for s in result.briefing.sections if s.type == "since_last")
    assert len(since_last.claims) >= 1


def test_case_P17() -> None:
    _check("P17")


def test_case_P18() -> None:
    _check("P18")
    result = run_case(CASES_BY_NAME["P18"])
    assert result.briefing is not None
    assert result.briefing.parent_briefing_id is None
    assert all(s.type != "since_last" for s in result.briefing.sections)


def test_case_P19() -> None:
    _check("P19")


def test_case_P20() -> None:
    _check("P20")


def test_case_P21() -> None:
    _check("P21")


def test_case_P22() -> None:
    _check("P22")


def test_case_P23() -> None:
    _check("P23")


def test_case_P24() -> None:
    _check("P24")


def test_case_P25() -> None:
    _check("P25")


def test_case_P26() -> None:
    _check("P26")


def test_case_P27() -> None:
    _check("P27")


def test_case_P28() -> None:
    _check("P28")


def test_case_P29() -> None:
    _check("P29")


def test_case_P30() -> None:
    _check("P30")
    result = run_case(CASES_BY_NAME["P30"])
    assert result.briefing is not None
    since_last = next(s for s in result.briefing.sections if s.type == "since_last")
    ref = since_last.claims[0].metric_refs[0]
    assert ref.metric_id == "period.last.pushes"
    assert ref.value == 1.0


def test_case_P31() -> None:
    _check("P31")


def test_case_P32() -> None:
    _check("P32")


def test_case_P33() -> None:
    _check("P33")
    result = run_case(CASES_BY_NAME["P33"])
    assert "PARENT_WITHOUT_DELTAS" in result.reason_codes
    assert result.briefing is not None
    assert result.briefing.parent_briefing_id is None


def test_case_P34() -> None:
    _check("P34")
    result = run_case(CASES_BY_NAME["P34"])
    assert result.reason_codes == ("NOOP_SLOT_OUTSIDE_ALLOWED_HOURS",)


def test_case_P35() -> None:
    _check("P35")


def test_case_P36() -> None:
    _check("P36")
    result = run_case(CASES_BY_NAME["P36"])
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_NO_EVIDENCE",)
    assert result.fallback.commitment.id == "cm-builder-notes"


def test_case_P37() -> None:
    _check("P37")


def test_stale_cycle_code_present_and_absent() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    fresh = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert "CYCLE_STALE" not in fresh.reason_codes
    assert fresh.cycle_age_s == 0.0
    stale = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF - timedelta(hours=13),
        offered={},
    )
    assert stale.kind == "proposal"
    assert "CYCLE_STALE" in stale.reason_codes


def test_fallback_tie_break_by_id_and_window_noop() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.briefing.context import TimeInterval
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P3"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    offered = {"cm-builder-parser": slot}
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered=offered,
    )
    assert result.kind == "fallback"
    assert result.fallback is not None
    assert result.fallback.commitment.id == "cm-builder-notes"
    older = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={
            "cm-builder-parser": slot - timedelta(hours=25),
            "cm-builder-notes": slot - timedelta(hours=1),
        },
    )
    assert older.kind == "fallback"
    assert older.fallback is not None
    assert older.fallback.commitment.id == "cm-builder-parser"
    foreign = TimeInterval(
        start=datetime.fromisoformat("2026-10-31T09:00:00+01:00"),
        end=datetime.fromisoformat("2026-10-31T10:00:00+01:00"),
    )
    foreign_result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=foreign,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert foreign_result.kind == "noop"
    assert "NOOP_FALLBACK_WINDOW" in foreign_result.reason_codes


def test_stale_gate_failure_fallback_exact_codes() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P3"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF - timedelta(hours=13),
        offered={},
    )
    assert result.kind == "fallback"
    assert result.reason_codes == (
        "FALLBACK_AFTER_GATE_FAILURE",
        "L1B_UNKNOWN_METRIC",
        "CYCLE_STALE",
    )


def test_stale_blocked_noop_exact_codes() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    marked = case.eligible[0].model_copy(
        update={"title": "Tidy the ikigai-loop backlog"}
    )
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=(marked, case.eligible[1]),
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF - timedelta(hours=13),
        offered={},
    )
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED", "CYCLE_STALE")


def test_stale_fallback_window_noop_exact_codes() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.briefing.context import TimeInterval
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P3"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    assert hour is not None
    foreign = TimeInterval(
        start=datetime.fromisoformat("2026-10-31T09:00:00+01:00"),
        end=datetime.fromisoformat("2026-10-31T10:00:00+01:00"),
    )
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=foreign,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF - timedelta(hours=13),
        offered={},
    )
    assert result.kind == "noop"
    assert result.reason_codes == (
        "NOOP_FALLBACK_WINDOW",
        "L1_ACTION_BEFORE_SLOT",
        "L1_ACTION_NOT_FREE",
        "CYCLE_STALE",
    )


def test_parent_without_deltas_blocked_noop_exact_codes() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P33"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    marked = case.eligible[0].model_copy(
        update={"title": "Tidy the ikigai-loop backlog"}
    )
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=(marked, case.eligible[1]),
        context=context,
        client=build_client(case),
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED", "PARENT_WITHOUT_DELTAS")


def test_repo_title_blocks_before_any_send() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    marked = case.eligible[0].model_copy(
        update={"title": "Tidy the ikigai-loop backlog"}
    )
    client = build_client(case)
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=(marked, case.eligible[1]),
        context=context,
        client=client,
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED",)
    assert len(result.attempts) == 1
    assert result.attempts[0].blocked is True
    assert result.attempts[0].codes == (("L1_ACTION_TARGETS_REPO", "prompt"),)
    assert client.calls == 0
    assert client.requests == []


def test_spark_at_low_is_recorded() -> None:
    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        build_client,
        build_context,
    )
    from framework.proposal.core import ModelParams, propose
    from framework.proposal.hour import pick_hour

    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    spark = ModelParams(
        first_model="muse-spark-1.3",
        first_effort="low",
        retry_model="muse-spark-1.3",
        retry_effort="low",
    )
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=build_client(case),
        models=spark,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert result.kind == "proposal"
    assert result.attempts[0].model_requested == "muse-spark-1.3"
    assert result.attempts[0].effort == "low"


def _propose_overall_texts(first: str, second: str):  # type: ignore[no-untyped-def]
    import json

    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        GOOD_WORKING,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        ScriptedWonderClient,
        build_context,
        text_entry,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    def _draft(text: str) -> str:
        return json.dumps(
            {
                "commitment_id": "cm-builder-parser",
                "overall_state": [
                    {
                        "text": text,
                        "fact_ids": [],
                        "metric_refs": ["period.last.pushes"],
                    }
                ],
                "working": GOOD_WORKING,
                "not_working": [],
            }
        )

    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    client = ScriptedWonderClient((text_entry(_draft(first)), text_entry(second)))
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=client,
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    return result, client


def test_proposal_claim_too_long_by_words_retries() -> None:
    from evals.proposal_cases import GOOD_DRAFT

    long_text = "Pushes were 3 in last" + " true" * 38
    assert len(long_text.split()) > 40
    assert len(long_text) <= 320
    result, client = _propose_overall_texts(long_text, GOOD_DRAFT)
    assert result.kind == "proposal"
    assert len(result.attempts) == 2
    assert tuple(code for code, _ in result.attempts[0].codes) == (
        "PROPOSAL_CLAIM_TOO_LONG",
    )
    assert result.attempts[0].codes[0][1].startswith("sections[overall_state].claims[")
    retry_text = client.requests[1].prompt
    assert "PROPOSAL_CLAIM_TOO_LONG" in retry_text
    assert "write one sentence of at most 20 words" in retry_text
    assert long_text not in retry_text
    assert result.attempts[1].codes == ()


def test_proposal_claim_too_long_by_characters() -> None:
    from evals.proposal_cases import GOOD_DRAFT

    long_text = "Pushes were 3 in last " + "x" * 12878
    assert len(long_text) == 12900
    result, client = _propose_overall_texts(long_text, GOOD_DRAFT)
    assert result.kind == "proposal"
    assert len(result.attempts) == 2
    assert tuple(code for code, _ in result.attempts[0].codes) == (
        "PROPOSAL_CLAIM_TOO_LONG",
    )
    assert "write one sentence of at most 20 words" in client.requests[1].prompt


def test_blocked_retry_keeps_first_attempt() -> None:
    from dataclasses import replace

    from evals.proposal_cases import ScriptEntry, run_case

    p2 = CASES_BY_NAME["P2"]
    case = replace(
        p2,
        name="f2-blocked",
        script=(
            p2.script[0],
            ScriptEntry(kind="blocked", codes=("L1_RAW_VALUE",)),
        ),
    )
    result = run_case(case)
    assert result.kind == "noop"
    assert result.reason_codes == ("NOOP_OUTBOUND_BLOCKED",)
    assert len(result.attempts) == 2
    first, second = result.attempts
    assert first.number == 1
    assert tuple(code for code, _ in first.codes) == ("L1B_UNKNOWN_FACT",)
    assert first.raw_text != ""
    assert first.completion_tokens == 13
    assert second.number == 2
    assert second.blocked is True
    assert second.codes == (("L1_RAW_VALUE", "prompt"),)


def test_unavailable_retry_keeps_first_attempt() -> None:
    from dataclasses import replace

    from evals.proposal_cases import run_case, unavailable_entry

    p2 = CASES_BY_NAME["P2"]
    case = replace(
        p2,
        name="f2-unavailable",
        script=(p2.script[0], unavailable_entry("status 500")),
    )
    result = run_case(case)
    assert result.kind == "fallback"
    assert result.fallback is not None
    assert result.fallback.reason_codes == ("FALLBACK_MODEL_UNAVAILABLE",)
    assert len(result.attempts) == 2
    first, second = result.attempts
    assert first.number == 1
    assert tuple(code for code, _ in first.codes) == ("L1B_UNKNOWN_FACT",)
    assert first.raw_text != ""
    assert second.number == 2
    assert second.codes == (("MODEL_UNAVAILABLE", "status 500"),)


def test_failed_retry_counts_in_first_draft_report(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    from evals.proposal_cases import ScriptEntry, run_case, unavailable_entry
    from framework.store.proposal_store import ProposalStore

    p2 = CASES_BY_NAME["P2"]
    blocked = replace(
        p2,
        name="f2-blocked",
        script=(p2.script[0], ScriptEntry(kind="blocked", codes=("L1_RAW_VALUE",))),
    )
    unavailable = replace(
        p2,
        name="f2-unavailable",
        script=(p2.script[0], unavailable_entry("status 500")),
    )
    for case in (blocked, unavailable):
        store = ProposalStore(db_path=tmp_path / f"{case.name}.db")
        try:
            store.record(run_case(case), snapshot={})
            report = store.first_draft_report()
            (stats,) = [
                m
                for m in report.models
                if (m.model, m.effort) == ("muse-wonder-1.0", "high")
            ]
            assert stats.first_drafts == 1, case.name
            assert stats.first_draft_failed == 1, case.name
            assert stats.retries == 1, case.name
        finally:
            store.close()


def test_unofferable_metrics_never_reach_deltas() -> None:
    import json
    from dataclasses import replace

    from evals.proposal_cases import GOOD_WORKING, run_case, text_entry

    p16 = CASES_BY_NAME["P16"]
    draft = json.dumps(
        {
            "commitment_id": "cm-builder-parser",
            "overall_state": [
                {
                    "text": "The synthetic focus session finished yesterday",
                    "fact_ids": ["fact:synthetic-1"],
                    "metric_refs": [],
                }
            ],
            "working": GOOD_WORKING,
            "not_working": [],
        }
    )
    case = replace(
        p16,
        name="f3-delta-offer",
        script=(text_entry(draft),),
        snapshot=(
            ("unknown.family.metric", 2.0),
            ("period.last.screen_hours.3d-print", 2.0),
            ("weird<<<id", 2.0),
        ),
        parent_snapshot=(
            ("unknown.family.metric", 1.0),
            ("period.last.screen_hours.3d-print", 1.0),
            ("weird<<<id", 1.0),
        ),
    )
    result = run_case(case)
    assert result.kind == "proposal"
    assert len(result.attempts) == 1
    assert "PARENT_WITHOUT_DELTAS" in result.reason_codes
    assert result.briefing is not None
    assert result.briefing.parent_briefing_id is None
    assert all(s.type != "since_last" for s in result.briefing.sections)


def test_proposal_claim_not_plain_shapes_retry() -> None:
    from evals.proposal_cases import GOOD_DRAFT

    shapes = [
        "Pushes were 3 in last per [notes](https://example.com/push-log)",
        "Pushes were 3 in last per https://example.com/push-log today",
        "Pushes were 3 in last per www.example.com/push-log today",
        "Pushes were 3 in last <b>today</b>",
        "Pushes were 3 in last\ntoday",
        "Pushes were 3 in last\rtoday",
    ]
    for text in shapes:
        result, client = _propose_overall_texts(text, GOOD_DRAFT)
        assert result.kind == "proposal", text
        assert len(result.attempts) == 2, text
        assert "PROPOSAL_CLAIM_NOT_PLAIN" in tuple(
            code for code, _ in result.attempts[0].codes
        ), text
        retry_text = client.requests[1].prompt
        assert "PROPOSAL_CLAIM_NOT_PLAIN" in retry_text, text
        assert "write plain sentences with no links or markup" in retry_text, text
        assert text not in retry_text, text


def test_runaway_claim_text_takes_unparseable_path() -> None:
    import json

    from evals.proposal_cases import (
        AS_OF,
        CYCLE_ID,
        LIMITS,
        MODELS,
        PROFILE_ID,
        STALE_AFTER_S,
        SUBJECT_ID,
        ScriptedWonderClient,
        build_context,
        text_entry,
    )
    from framework.proposal.core import propose
    from framework.proposal.hour import pick_hour

    huge = "x" * 2_000_000
    draft = json.dumps(
        {
            "commitment_id": "cm-builder-parser",
            "overall_state": [{"text": huge, "fact_ids": [], "metric_refs": []}],
            "working": [],
            "not_working": [],
        }
    )
    case = CASES_BY_NAME["P1"]
    slot = datetime.fromisoformat(case.slot_iso)
    context = build_context(case)
    hour = pick_hour(slot, context.busy_intervals, LIMITS)
    client = ScriptedWonderClient((text_entry(draft), text_entry(draft)))
    result = propose(
        profile_id=PROFILE_ID,
        subject_id=SUBJECT_ID,
        slot=slot,
        as_of=AS_OF,
        cycle_id=CYCLE_ID,
        run=1,
        hour=hour,
        eligible=case.eligible,
        context=context,
        client=client,
        models=MODELS,
        policy="",
        stale_after_s=STALE_AFTER_S,
        cycle_as_of=AS_OF,
        offered={},
    )
    assert result.kind == "fallback"
    assert len(result.attempts) == 2
    for attempt in result.attempts:
        assert attempt.codes == (("DRAFT_UNPARSEABLE", "draft"),)


def _collect_schema_enums(schema: object) -> set[str]:
    """Every string inside an ``enum`` list anywhere in the schema."""
    found: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            enum = node.get("enum")
            if isinstance(enum, list):
                for item in enum:
                    if isinstance(item, str):
                        found.add(item)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(schema)
    return found


def test_response_schema_enums_appear_in_prompt() -> None:
    from evals.proposal_cases import CASES_BY_NAME, build_client, run_case

    for case_name in ("P1", "P16"):
        case = CASES_BY_NAME[case_name]
        client = build_client(case)
        result = run_case(case, client)
        assert result.kind == "proposal", case_name
        assert len(client.requests) == 1, case_name
        request = client.requests[0]
        enums = _collect_schema_enums(request.response_schema)
        assert enums, case_name
        for value in enums:
            assert value in request.prompt, (case_name, value)
