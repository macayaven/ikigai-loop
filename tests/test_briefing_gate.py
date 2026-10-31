"""Ticket 8: per-rule unit tests over ``evaluate_briefing`` on raw dicts.

Test names carry the AT ``-k`` keywords: L0 tests use
``l0/schema/duplicate/action_count/missing_section/empty_section``,
text-safety tests use ``secret/pii/private/raw/english``, slot and
interval tests use ``slot/busy/free/repo_target/before_slot/check_slot``,
and L1b tests use
``fact/evidence/number_backing/rounding/metric/delta/parent/determin``.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from evals.briefing_cases import (
    RAW_LITERAL,
    SYNTHETIC_TERM,
    base_case,
    base_case_with_parent,
)
from framework.briefing.context import MetricSnapshot
from framework.briefing.gate import GateResult, evaluate_briefing
from framework.briefing.schemas import Briefing


def _codes(result: GateResult) -> list[str]:
    return [v.code for v in result.violations]


def _fresh(profile: str = "builder") -> tuple[dict[str, Any], Any]:
    case = base_case(profile)
    return copy.deepcopy(case.briefing), case.context


def _section(briefing: dict[str, Any], section_type: str) -> dict[str, Any]:
    return next(s for s in briefing["sections"] if s["type"] == section_type)


def test_l0_schema_invalid_on_extra_field() -> None:
    briefing, context = _fresh()
    briefing["sections"][0]["claims"][0]["proof"] = "nope"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_SCHEMA_INVALID"]
    assert result.passed is False


def test_l0_unknown_section_reports_index() -> None:
    briefing, context = _fresh()
    _section(briefing, "working")["type"] = "mystery"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_UNKNOWN_SECTION"]
    assert result.violations[0].location == "sections[1]"


def test_l0_missing_section() -> None:
    briefing, context = _fresh()
    briefing["sections"] = [s for s in briefing["sections"] if s["type"] != "working"]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_MISSING_SECTION"]
    assert result.violations[0].location == "sections[working]"


def test_l0_duplicate_section() -> None:
    briefing, context = _fresh()
    working = copy.deepcopy(_section(briefing, "working"))
    working["claims"][0]["id"] = "claim-w-copy"
    briefing["sections"].insert(2, working)
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_DUPLICATE_SECTION"]
    assert result.violations[0].location == "sections[working]"


def test_l0_section_count_guard() -> None:
    briefing, context = _fresh()
    working = copy.deepcopy(_section(briefing, "working"))
    briefing["sections"].extend([working, copy.deepcopy(working)])
    result = evaluate_briefing(briefing, context)
    assert "L0_DUPLICATE_SECTION" in _codes(result)
    assert "L0_SECTION_COUNT" in _codes(result)


def test_l0_empty_section_overall_state() -> None:
    briefing, context = _fresh()
    _section(briefing, "overall_state")["claims"] = []
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_EMPTY_SECTION"]


def test_l0_empty_section_since_last_present() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    _section(briefing, "since_last")["claims"] = []
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L0_EMPTY_SECTION"]


def test_l0_empty_section_working_may_be_empty() -> None:
    briefing, context = _fresh()
    _section(briefing, "working")["claims"] = []
    assert evaluate_briefing(briefing, context).passed is True


def test_action_count_too_many() -> None:
    briefing, context = _fresh()
    actions = _section(briefing, "actions")["actions"]
    actions.extend([copy.deepcopy(actions[0]), copy.deepcopy(actions[0])])
    actions[2]["id"] = "act-extra-a"
    actions[3]["id"] = "act-extra-b"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_ACTION_COUNT"]


def test_action_count_zero() -> None:
    briefing, context = _fresh()
    _section(briefing, "actions")["actions"] = []
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_ACTION_COUNT"]


def test_action_count_other_section() -> None:
    briefing, context = _fresh()
    stray = copy.deepcopy(_section(briefing, "actions")["actions"][0])
    stray["id"] = "act-stray-1"
    _section(briefing, "working")["actions"].append(stray)
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_ACTION_COUNT"]
    assert result.violations[0].location == "sections[working]"


def test_duplicate_id_second_occurrence() -> None:
    briefing, context = _fresh()
    _section(briefing, "working")["claims"][0]["id"] = "claim-o1"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_DUPLICATE_ID"]
    assert result.violations[0].location == "sections[working].claims[claim-o1]"


def test_l0_invalid_short_circuits_l1_l1b() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T13:00:00"
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Contact synthetic@example.invalid for notes"
    claim["fact_ids"] = ["fact:synthetic-missing"]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_SCHEMA_INVALID"]


def test_schema_validated_object_accepted() -> None:
    briefing, context = _fresh()
    validated = Briefing.model_validate(briefing)
    assert evaluate_briefing(validated, context).passed is True


def test_secret_long_token_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Rotate ghp_abcdefghijklmnop now"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_SECRET"]
    assert "ghp_" not in result.violations[0].message


def test_secret_short_after_prefix_passes() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Rotate sk-short now"
    assert evaluate_briefing(briefing, context).passed is True


def test_secret_bearer_long_token_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Send Bearer abcdefghijklmnop now"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_SECRET"]


def test_secret_assignment_label_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " The token= sparrowfeather stays here"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_SECRET"]


def test_pii_email_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Contact synthetic@example.invalid for notes"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_PII"]
    assert "synthetic@" not in result.violations[0].message


def test_pii_strict_phone_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Call +34600000000 tomorrow"
    result = evaluate_briefing(briefing, context)
    assert "L1_PII" in _codes(result)


def test_private_term_match() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += f" Notes mention {SYNTHETIC_TERM} here"
    context = context.model_copy(update={"private_terms": (SYNTHETIC_TERM,)})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_PRIVATE_TERM"]
    assert SYNTHETIC_TERM not in result.violations[0].message


def test_private_terms_unavailable_fail_closed() -> None:
    briefing, context = _fresh()
    context = context.model_copy(update={"private_terms_available": False})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_PRIVATE_TERMS_UNAVAILABLE"]


def test_private_terms_loaded_from_synthetic_dir(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    terms_file = tmp_path / "deny-terms.txt"
    terms_file.write_text(
        f"\n{SYNTHETIC_TERM}\n   \n{SYNTHETIC_TERM}\n"
        "# a synthetic comment\nOther-Term\n",
        encoding="utf-8",
    )
    (tmp_path / "other-criteria.txt").write_text("ignored-term\n", encoding="utf-8")
    loaded = load_private_terms(
        {"HIDDEN_CRITERIA_DIR": str(tmp_path)},
        allow_missing_for_tests=True,
    )
    assert loaded.available is True
    assert loaded.terms == (SYNTHETIC_TERM, "Other-Term")


def test_private_terms_missing_dir_fail_closed(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    loaded = load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path / "absent")})
    assert loaded.available is False
    assert loaded.terms == ()


def test_private_terms_missing_file_fail_closed(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    (tmp_path / "other-criteria.txt").write_text("nope\n", encoding="utf-8")
    loaded = load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path)})
    assert loaded.available is False
    assert loaded.terms == ()


def test_private_terms_empty_file_fail_closed(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    (tmp_path / "deny-terms.txt").write_text(
        "\n   \n# nothing here\n", encoding="utf-8"
    )
    loaded = load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path)})
    assert loaded.available is False


def test_private_terms_bullet_lines_fail_closed(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    (tmp_path / "deny-terms.txt").write_text(
        f"{SYNTHETIC_TERM}\n- synthetic bullet\n", encoding="utf-8"
    )
    loaded = load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path)})
    assert loaded.available is False
    (tmp_path / "deny-terms.txt").write_text(
        f"{SYNTHETIC_TERM}\n* synthetic star\n", encoding="utf-8"
    )
    assert load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path)}).available is False


def test_private_terms_non_utf8_fail_closed(tmp_path: object) -> None:
    from pathlib import Path

    from framework.briefing.context import load_private_terms

    assert isinstance(tmp_path, Path)
    (tmp_path / "deny-terms.txt").write_bytes(b"\xff\xfe\x00nope\n")
    loaded = load_private_terms({"HIDDEN_CRITERIA_DIR": str(tmp_path)})
    assert loaded.available is False
    assert loaded.terms == ()


def test_private_term_short_whole_word_only() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Running late today"
    context = context.model_copy(update={"private_terms": ("run",)})
    assert evaluate_briefing(briefing, context).passed is True
    briefing2, _ = _fresh()
    claim2 = _section(briefing2, "working")["claims"][0]
    claim2["text"] += " Go for a run today"
    result = evaluate_briefing(briefing2, context)
    assert _codes(result) == ["L1_PRIVATE_TERM"]


def test_raw_value_ref_arm() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Resting average is 62 beats"
    claim["metric_refs"] = [{"metric_id": "raw.health.resting_hr", "value": 62.0}]
    values = dict(context.metrics.values)
    values["raw.health.resting_hr"] = 62.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_RAW_VALUE"]


def test_raw_value_literal_arm() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += f" Meeting {RAW_LITERAL} moved along"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_RAW_VALUE"]
    assert RAW_LITERAL not in result.violations[0].message


def test_english_phrases_pass() -> None:
    briefing, context = _fresh()
    overall = _section(briefing, "overall_state")
    overall["claims"] = [
        {
            "id": "claim-e1",
            "text": "A task-based routine keeps evenings calm",
            "fact_ids": ["fact:synthetic-1"],
            "metric_refs": [],
        },
        {
            "id": "claim-e2",
            "text": "The plan is risk-free and fully reversible",
            "fact_ids": ["fact:synthetic-2"],
            "metric_refs": [],
        },
    ]
    assert evaluate_briefing(briefing, context).passed is True


def test_slot_start_inclusive_passes() -> None:
    briefing, context = _fresh()
    assert briefing["slot"] == "2026-10-31T13:00:00+01:00"
    assert evaluate_briefing(briefing, context).passed is True


def test_slot_end_exclusive_fails() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T23:30:00+01:00"
    result = evaluate_briefing(briefing, context)
    assert "L1_SLOT_OUTSIDE_ALLOWED_HOURS" in _codes(result)


def test_slot_nine_am_fails() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T09:00:00+01:00"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_SLOT_OUTSIDE_ALLOWED_HOURS"]


def test_check_slot_false_skips_only_slot() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T09:00:00+01:00"
    context = context.model_copy(update={"check_slot": False})
    assert evaluate_briefing(briefing, context).passed is True


def test_before_slot_fires() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T18:00:00+01:00"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_BEFORE_SLOT"]


def test_before_slot_exact_start_passes() -> None:
    briefing, context = _fresh()
    actions = _section(briefing, "actions")["actions"]
    actions[0]["proposed_start"] = briefing["slot"]
    actions[0]["proposed_end"] = "2026-10-31T14:00:00+01:00"
    assert evaluate_briefing(briefing, context).passed is True


def test_check_slot_false_keeps_before_slot() -> None:
    briefing, context = _fresh()
    briefing["slot"] = "2026-10-31T18:00:00+01:00"
    context = context.model_copy(update={"check_slot": False})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_BEFORE_SLOT"]


def test_busy_overlap_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["proposed_start"] = "2026-10-31T15:15:00+01:00"
    action["proposed_end"] = "2026-10-31T15:45:00+01:00"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_IN_BUSY_INTERVAL"]


def test_busy_boundary_touch_passes() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["proposed_start"] = "2026-10-31T14:00:00+01:00"
    action["proposed_end"] = "2026-10-31T15:00:00+01:00"
    assert evaluate_briefing(briefing, context).passed is True


def test_free_coverage_gap_fires() -> None:
    from framework.briefing.context import TimeInterval

    briefing, context = _fresh()
    context = context.model_copy(
        update={
            "free_intervals": (
                TimeInterval(
                    start="2026-10-31T13:00:00+01:00",  # type: ignore[arg-type]
                    end="2026-10-31T14:00:00+01:00",  # type: ignore[arg-type]
                ),
            )
        }
    )
    result = evaluate_briefing(briefing, context)
    assert "L1_ACTION_NOT_FREE" in _codes(result)


def test_busy_suppresses_not_free() -> None:
    from framework.briefing.context import TimeInterval

    briefing, context = _fresh()
    actions = _section(briefing, "actions")["actions"]
    actions[0]["proposed_start"] = "2026-10-31T15:15:00+01:00"
    actions[0]["proposed_end"] = "2026-10-31T15:45:00+01:00"
    actions[1]["proposed_start"] = "2026-10-31T13:00:00+01:00"
    actions[1]["proposed_end"] = "2026-10-31T13:30:00+01:00"
    context = context.model_copy(
        update={
            "free_intervals": (
                TimeInterval(
                    start="2026-10-31T13:00:00+01:00",  # type: ignore[arg-type]
                    end="2026-10-31T14:00:00+01:00",  # type: ignore[arg-type]
                ),
            )
        }
    )
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_IN_BUSY_INTERVAL"]


def test_repo_target_fires() -> None:
    briefing, context = _fresh()
    _section(briefing, "actions")["actions"][0]["text"] = "Fix ikigai-loop docs tonight"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_TARGETS_REPO"]


def test_repo_target_claims_not_scanned() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Nothing about ikigai_loop here matters"
    result = evaluate_briefing(briefing, context)
    assert "L1_ACTION_TARGETS_REPO" not in _codes(result)


def test_pii_and_fact_collected_together() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Contact synthetic@example.invalid for notes"
    claim["fact_ids"] = ["fact:synthetic-missing"]
    result = evaluate_briefing(briefing, context)
    assert "L1_PII" in _codes(result)
    assert "L1B_UNKNOWN_FACT" in _codes(result)


def test_evidence_empty_claim_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["fact_ids"] = []
    claim["metric_refs"] = []
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_CLAIM_WITHOUT_EVIDENCE"]


def test_fact_unknown_id_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["fact_ids"] = ["fact:synthetic-missing"]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_UNKNOWN_FACT"]


def test_fact_other_subject_fires() -> None:
    briefing, context = _fresh()
    facts = copy.deepcopy(context.facts)
    other = facts["fact:synthetic-1"].model_copy(update={"subject_id": "subject-other"})
    context = context.model_copy(update={"facts": {**facts, other.id: other}})
    result = evaluate_briefing(briefing, context)
    assert "L1B_UNKNOWN_FACT" in _codes(result)


def test_number_backing_unbacked_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Scored 42 points in the synthetic trial"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_NUMBER_WITHOUT_METRIC_REF"]


def test_number_backing_rounded_passes() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Output quality sits at 21.2 this week"
    claim["metric_refs"] = [{"metric_id": "agg.quality", "value": 21.1544}]
    values = dict(context.metrics.values)
    values["agg.quality"] = 21.1544
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert evaluate_briefing(briefing, context).passed is True


def test_rounding_snapshot_wrong_still_fails() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Output quality sits at 21.2 this week"
    claim["metric_refs"] = [{"metric_id": "agg.quality", "value": 21.1544}]
    values = dict(context.metrics.values)
    values["agg.quality"] = 99.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_METRIC_VALUE_MISMATCH"]


def test_number_backing_absolute_passes() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Energy is down 5 from last time"
    claim["metric_refs"] = [{"metric_id": "agg.energy", "value": -5.0}]
    values = dict(context.metrics.values)
    values["agg.energy"] = -5.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert evaluate_briefing(briefing, context).passed is True


def test_metric_unknown_id_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Recorded 7 synthetic events"
    claim["metric_refs"] = [{"metric_id": "agg.absent", "value": 7.0}]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_UNKNOWN_METRIC"]


def test_metric_snapshot_mismatch_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Completed 99 synthetic tasks"
    claim["metric_refs"] = [{"metric_id": "agg.tasks_done", "value": 99.0}]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_METRIC_VALUE_MISMATCH"]


def test_delta_correct_passes() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    assert evaluate_briefing(briefing, case.context).passed is True


def test_delta_wrong_fails() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][0]
    claim["text"] = "Focus total moved by 11 since the parent briefing"
    claim["metric_refs"] = [{"metric_id": "agg.focus_minutes", "value": -11.0}]
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L1B_DELTA_MISMATCH"]


def test_delta_missing_side_fails() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    parent_values = dict(case.context.parent_metrics.values)  # type: ignore[union-attr]
    del parent_values["agg.focus_minutes"]
    context = case.context.model_copy(
        update={"parent_metrics": MetricSnapshot(values=parent_values)}
    )
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_DELTA_MISMATCH"]


def test_parent_mismatch_fires() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    briefing["parent_briefing_id"] = "brf-builder-other"
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L1B_PARENT_MISMATCH"]


def test_parent_missing_since_last_fires() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    briefing["sections"] = [
        s for s in briefing["sections"] if s["type"] != "since_last"
    ]
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L1B_MISSING_SINCE_LAST"]


def test_parent_since_last_without_parent_fires() -> None:
    briefing, context = _fresh()
    briefing["sections"].insert(
        1,
        {
            "type": "since_last",
            "claims": [
                {
                    "id": "claim-sx",
                    "text": "Nothing changed in the synthetic log",
                    "fact_ids": ["fact:synthetic-1"],
                    "metric_refs": [],
                }
            ],
            "actions": [],
        },
    )
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_SINCE_LAST_WITHOUT_PARENT"]


def test_deterministic_repeat_and_reorder() -> None:
    briefing, context = _fresh()
    first = evaluate_briefing(briefing, context)
    second = evaluate_briefing(copy.deepcopy(briefing), context)
    assert _codes(first) == _codes(second)
    reordered = copy.deepcopy(briefing)
    reordered["sections"] = list(reversed(reordered["sections"]))
    assert _codes(evaluate_briefing(reordered, context)) == _codes(first)


REJECTED_QUANTITIES = [
    ("total-steps", "You walked a total of 2000 steps."),
    ("leading-steps", "2000 steps yesterday."),
    ("increments", "You logged steps in 2000 increments."),
    ("colon-h", "Sleep:9h last night."),
    ("colon-word", "Slept sleep:9 hours."),
    ("hyphen-id", "hrv-99 today."),
    ("glued-id", "steps9065 yesterday."),
    ("colon-time", "Slept 8:30 hours."),
    ("lower-month", "You may 9 hours rest."),
    ("dotted", "1.2.3 hours."),
    ("spelled-word", "Slept nine hours."),
]


@pytest.mark.parametrize("case_id,text", REJECTED_QUANTITIES)
def test_number_backing_rejects_bare_quantities(case_id: str, text: str) -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    result = evaluate_briefing(briefing, context)
    assert (case_id, _codes(result)) == (
        case_id,
        ["L1B_NUMBER_WITHOUT_METRIC_REF"],
    )


def test_number_backing_still_passes_dates_and_ordinals() -> None:
    for text in (
        "On 2026-10-30 at 13:30",
        "On Oct 30",
        "Planned for May 9",
        "Notes from the 3rd session",
    ):
        briefing, context = _fresh()
        claim = _section(briefing, "working")["claims"][0]
        claim["text"] = text
        assert evaluate_briefing(briefing, context).passed is True, text


def test_raw_value_case_and_space_variants() -> None:
    for text in (
        f"Meeting {RAW_LITERAL} moved along",
        f"Meeting {RAW_LITERAL.lower()} moved along",
        f"Meeting {RAW_LITERAL.upper()} moved along",
        f"Meeting {RAW_LITERAL.replace(' ', '  ')} moved along",
    ):
        briefing, context = _fresh()
        claim = _section(briefing, "working")["claims"][0]
        claim["text"] += f" {text}"
        result = evaluate_briefing(briefing, context)
        assert _codes(result) == ["L1_RAW_VALUE"], text


def test_secret_ts_net_hostname_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Sync via mytestbox.ts.net tonight"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_SECRET"]


def test_l0_unknown_section_unhashable_type() -> None:
    briefing, context = _fresh()
    _section(briefing, "working")["type"] = ["working"]
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_UNKNOWN_SECTION"]


def test_l0_unknown_section_non_string_type() -> None:
    briefing, context = _fresh()
    _section(briefing, "working")["type"] = 5
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L0_UNKNOWN_SECTION"]


def test_l0_schema_invalid_non_mapping_top_level() -> None:
    _, context = _fresh()
    for raw in (["sections"], "nope", None, 42):
        result = evaluate_briefing(raw, context)  # type: ignore[arg-type]
        assert _codes(result) == ["L0_SCHEMA_INVALID"], repr(raw)
