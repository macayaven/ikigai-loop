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
from datetime import datetime
from typing import Any

import pytest

from evals.briefing_cases import (
    RAW_LITERAL,
    SYNTHETIC_TERM,
    base_case,
    base_case_with_parent,
)
from framework.briefing.context import MetricSnapshot, TimeInterval
from framework.briefing.gate import (
    GateResult,
    action_window_codes,
    evaluate_briefing,
    text_check_codes,
)
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
    from framework.briefing.schemas import Commitment

    briefing, context = _fresh()
    commitment = Commitment.model_validate(
        {
            "id": "cm-synthetic-repo",
            "profile_id": "builder",
            "title": "Fix ikigai-loop docs tonight",
            "kind": "build",
            "dimension": "good_at",
            "evidence": "tap",
        }
    )
    context = context.model_copy(
        update={
            "commitments": (commitment,),
            "commitments_available": True,
        }
    )
    actions = _section(briefing, "actions")["actions"]
    action = actions[0]
    action["commitment_id"] = "cm-synthetic-repo"
    action["kind"] = "build"
    action["text"] = "Fix ikigai-loop docs tonight"
    action["dimension"] = "good_at"
    del actions[1]
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
    claim["text"] = "Programming quality sits at 21.2 this week"
    claim["metric_refs"] = [
        {"metric_id": "screen_hours.Work/Programming", "value": 21.1544}
    ]
    values = dict(context.metrics.values)
    values["screen_hours.Work/Programming"] = 21.1544
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert evaluate_briefing(briefing, context).passed is True


def test_rounding_snapshot_wrong_still_fails() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Programming quality sits at 21.2 this week"
    claim["metric_refs"] = [
        {"metric_id": "screen_hours.Work/Programming", "value": 21.1544}
    ]
    values = dict(context.metrics.values)
    values["screen_hours.Work/Programming"] = 99.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_METRIC_VALUE_MISMATCH"]


def test_number_backing_absolute_passes() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][0]
    assert claim["text"] == "Programming is down 10 since the parent briefing"
    assert claim["metric_refs"] == [
        {"metric_id": "screen_hours.Work/Programming", "value": -10.0}
    ]
    assert evaluate_briefing(briefing, case.context).passed is True


def test_metric_unknown_id_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushed 7 times in the synthetic trial"
    claim["metric_refs"] = [{"metric_id": "github.push.count", "value": 7.0}]
    values = dict(context.metrics.values)
    del values["github.push.count"]
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1B_UNKNOWN_METRIC"]


def test_metric_snapshot_mismatch_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushed 99 tasks in the synthetic trial"
    claim["metric_refs"] = [{"metric_id": "github.push.count", "value": 99.0}]
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
    claim["text"] = "Programming total moved by 11 since the parent briefing"
    claim["metric_refs"] = [
        {"metric_id": "screen_hours.Work/Programming", "value": -11.0}
    ]
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L1B_DELTA_MISMATCH"]


def test_delta_missing_side_fails() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    parent_values = dict(case.context.parent_metrics.values)  # type: ignore[union-attr]
    del parent_values["screen_hours.Work/Programming"]
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


def _label_fresh(text: str, metric_id: str, value: float) -> tuple[dict[str, Any], Any]:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    claim["metric_refs"] = [{"metric_id": metric_id, "value": value}]
    values = dict(context.metrics.values)
    values[metric_id] = value
    return briefing, context.model_copy(
        update={"metrics": MetricSnapshot(values=values)}
    )


def test_commitment_whitespace_and_case_variants_pass() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["text"] = "  BUILD the Synthetic Parser SKETCH  "
    assert evaluate_briefing(briefing, context).passed is True


def test_commitment_trailing_period_mismatch_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["text"] = "Build the synthetic parser sketch."
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_TEXT_MISMATCH"]


def test_commitment_extra_word_mismatch_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["text"] = "Build the synthetic parser sketch today"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_TEXT_MISMATCH"]


def test_commitment_kind_only_mismatch_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["kind"] = "write"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_TEXT_MISMATCH"]


def test_commitment_dimension_only_mismatch_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["dimension"] = "love"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_TEXT_MISMATCH"]


def test_commitment_unknown_id_suppresses_mismatch() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["commitment_id"] = "cm-builder-absent"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_NOT_COMMITTED"]


def test_commitment_cross_profile_id_fires() -> None:
    briefing, context = _fresh()
    action = _section(briefing, "actions")["actions"][0]
    action["commitment_id"] = "cm-disconnect-walk"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ACTION_NOT_COMMITTED"]


def test_commitment_unavailable_skips_per_action_checks() -> None:
    briefing, context = _fresh()
    context = context.model_copy(update={"commitments_available": False})
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_COMMITMENTS_UNAVAILABLE"]
    assert result.violations[0].location == "briefing"


ADVICE_ENTRIES = [
    "should",
    "must",
    "diet",
    "diets",
    "calorie",
    "calories",
    "medication",
    "medications",
    "medicine",
    "medicines",
    "dose",
    "doses",
    "dosage",
    "dosages",
    "symptom",
    "symptoms",
    "diagnosis",
    "diagnoses",
    "treatment",
    "treatments",
    "therapy",
    "therapies",
    "intensity",
    "shouldn't",
    "mustn't",
    "push harder",
    "rest more",
]


@pytest.mark.parametrize("entry", ADVICE_ENTRIES, ids=ADVICE_ENTRIES)
def test_advice_pinned_entry_fires(entry: str) -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += f" Notes on {entry} timing here"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ADVICE"], entry
    assert entry not in result.violations[0].message


def test_advice_rest_alone_passes() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Rest with quiet music"
    assert evaluate_briefing(briefing, context).passed is True


def test_advice_mustard_and_shoulder_pass() -> None:
    for text in ("Mustard on the synthetic shelf", "Shoulder the synthetic pack"):
        briefing, context = _fresh()
        claim = _section(briefing, "working")["claims"][0]
        claim["text"] = text
        assert evaluate_briefing(briefing, context).passed is True, text


def test_advice_spacing_and_case_variants_fire() -> None:
    for text in ("Plan to Push  Harder today", "Plan to REST MORE today"):
        briefing, context = _fresh()
        claim = _section(briefing, "working")["claims"][0]
        claim["text"] = text
        result = evaluate_briefing(briefing, context)
        assert _codes(result) == ["L1_ADVICE"], text


def test_advice_curly_apostrophe_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Notes on shouldn’t timing here"
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_ADVICE"]


def test_label_push_pr_feed_cancel_forms_pass() -> None:
    passing = [
        ("Merged 2 PRs in last", "period.last.prs", 2.0),
        ("2 pull requests in last", "period.last.prs", 2.0),
        ("Pushed 3 times in last", "period.last.pushes", 3.0),
        ("Feeds held 9", "feed.item.count", 9.0),
        ("Canceled 2 deep blocks in last", "period.last.cancelled.iki-deep", 2.0),
    ]
    for text, metric_id, value in passing:
        briefing, context = _label_fresh(text, metric_id, value)
        assert evaluate_briefing(briefing, context).passed is True, text


def test_label_feedback_and_pushback_fail() -> None:
    briefing, context = _label_fresh("Feedback reached 9", "feed.item.count", 9.0)
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISSING"]
    briefing, context = _label_fresh("Pushback reached 3", "github.push.count", 3.0)
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISSING"]


def test_label_prior_without_pr_fails_with_both_codes() -> None:
    briefing, context = _label_fresh("Prior reached 2 in prior", "github.pr.count", 2.0)
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == [
        "L1B_METRIC_LABEL_MISSING",
        "L1B_PERIOD_WORD_MISSING",
    ]


def test_label_empty_and_dotted_ids_are_unknown() -> None:
    from framework.briefing.labels import metric_label_binding

    for metric_id in (
        "screen_hours.Work/",
        "tag_hours.iki-",
        "screen_hours. ",
        "period.last.tag_hours.iki-",
        "feed.item.count.",
    ):
        assert metric_label_binding(metric_id) is None, metric_id


def test_label_dotted_category_is_known() -> None:
    from framework.briefing.labels import metric_label_binding

    binding = metric_label_binding("screen_hours.Work/Node.js")
    assert binding is not None
    assert "Node.js" in binding.labels
    binding = metric_label_binding("period.last.screen_hours.Work/Node.js")
    assert binding is not None
    assert binding.period == "last"
    assert "Node.js" in binding.labels


def test_period_word_whole_word_only() -> None:
    for text in (
        "Priority pushes reached 3 today",
        "Pushes reached 3 lastly today",
        "Earliest push logs reached 3 today",
    ):
        briefing, context = _label_fresh(text, "github.push.count", 3.0)
        assert evaluate_briefing(briefing, context).passed is True, text


def test_period_word_prior_capitalised_fires() -> None:
    briefing, context = _label_fresh(
        "Prior to the review, pushes reached 3", "github.push.count", 3.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_PERIOD_WORD_MISSING"]


def test_period_word_last_push_window_total_fires() -> None:
    briefing, context = _label_fresh(
        "Pushes reached 3 in the last push", "github.push.count", 3.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_PERIOD_WORD_MISSING"]


def test_period_word_since_last_exemption() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][0]
    claim["text"] = "Programming is down 10 since the last briefing"
    assert evaluate_briefing(briefing, case.context).passed is True


def test_direction_non_words_pass() -> None:
    for word in ("download", "upstream", "lowercase", "morning"):
        briefing, context = _label_fresh(
            f"Pushes reached 3 in last {word}", "period.last.pushes", 3.0
        )
        assert evaluate_briefing(briefing, context).passed is True, word


def test_direction_hyphen_forms_are_free_but_spaced_is_not() -> None:
    for text in (
        "Pushes follow-up reached 3 in last",
        "Pushes wind-down reached 3 in last",
    ):
        briefing, context = _label_fresh(text, "period.last.pushes", 3.0)
        assert evaluate_briefing(briefing, context).passed is True, text
    briefing, context = _label_fresh(
        "Pushes wind down reached 3 in last", "period.last.pushes", 3.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_zero_change_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushes rose from 3 in earlier to 3 in last"
    claim["metric_refs"] = [
        {"metric_id": "period.earlier.pushes", "value": 3.0},
        {"metric_id": "period.last.pushes", "value": 3.0},
    ]
    values = dict(context.metrics.values)
    values["period.earlier.pushes"] = 3.0
    values["period.last.pushes"] = 3.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_both_lists_fire() -> None:
    briefing, context = _label_fresh(
        "Pushes more or less reached 3 in last", "period.last.pushes", 3.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_shuffled_ref_order_sorts_before_compare() -> None:
    def _shuffled(text: str) -> list[str]:
        briefing, context = _fresh()
        claim = _section(briefing, "working")["claims"][0]
        claim["text"] = text
        claim["metric_refs"] = [
            {"metric_id": "period.last.pushes", "value": 1.0},
            {"metric_id": "period.earlier.pushes", "value": 3.0},
            {"metric_id": "period.prior.pushes", "value": 2.0},
        ]
        values = dict(context.metrics.values)
        values["period.last.pushes"] = 1.0
        values["period.earlier.pushes"] = 3.0
        values["period.prior.pushes"] = 2.0
        context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
        return _codes(evaluate_briefing(briefing, context))

    assert (
        _shuffled("Pushes fell from 3 in earlier to 2 in prior and to 1 in last") == []
    )
    assert _shuffled(
        "Pushes rose from 3 in earlier to 2 in prior and to 1 in last"
    ) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_since_last_sign_checked() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][2]
    assert claim["text"] == "Pushes rose by 1 since the parent briefing"
    assert evaluate_briefing(briefing, case.context).passed is True
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][2]
    claim["text"] = "Pushes fell by 1 since the parent briefing"
    result = evaluate_briefing(briefing, case.context)
    assert _codes(result) == ["L1B_DIRECTION_MISMATCH"]


def test_too_many_metrics_variants_fire() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushes reached 3 in last and again 3 in last"
    claim["metric_refs"] = [
        {"metric_id": "period.last.pushes", "value": 3.0},
        {"metric_id": "period.last.pushes", "value": 3.0},
    ]
    values = dict(context.metrics.values)
    values["period.last.pushes"] = 3.0
    dup = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, dup)) == ["L1B_TOO_MANY_METRICS"]

    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushes reached 3 in last with 3 pushes overall"
    claim["metric_refs"] = [
        {"metric_id": "period.last.pushes", "value": 3.0},
        {"metric_id": "github.push.count", "value": 3.0},
    ]
    mixed = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, mixed)) == ["L1B_TOO_MANY_METRICS"]

    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushes 3 in earlier and prior and last and overall"
    claim["metric_refs"] = [
        {"metric_id": "period.earlier.pushes", "value": 3.0},
        {"metric_id": "period.prior.pushes", "value": 3.0},
        {"metric_id": "period.last.pushes", "value": 3.0},
        {"metric_id": "github.push.count", "value": 3.0},
    ]
    values = dict(context.metrics.values)
    values["period.earlier.pushes"] = 3.0
    values["period.prior.pushes"] = 3.0
    values["period.last.pushes"] = 3.0
    four = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, four)) == ["L1B_TOO_MANY_METRICS"]


def test_binding_raw_refs_exempt_from_binding() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] += " Resting average is 62 beats"
    claim["metric_refs"] = [{"metric_id": "raw.health.resting_hr", "value": 62.0}]
    values = dict(context.metrics.values)
    values["raw.health.resting_hr"] = 62.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, context)) == ["L1_RAW_VALUE"]


def test_binding_unknown_period_name_fires() -> None:
    briefing, context = _label_fresh(
        "Pushes reached 3 in someday", "period.someday.pushes", 3.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_UNKNOWN"]


def test_binding_cancelled_metric_needs_cancel_word() -> None:
    briefing, context = _label_fresh(
        "Deep blocks reached 2 in last", "period.last.cancelled.iki-deep", 2.0
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISSING"]


def _two_ref_fresh(
    text: str, first: tuple[str, float], second: tuple[str, float]
) -> tuple[dict[str, Any], Any]:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    claim["metric_refs"] = [
        {"metric_id": first[0], "value": first[1]},
        {"metric_id": second[0], "value": second[1]},
    ]
    values = dict(context.metrics.values)
    values[first[0]] = first[1]
    values[second[0]] = second[1]
    return briefing, context.model_copy(
        update={"metrics": MetricSnapshot(values=values)}
    )


@pytest.mark.parametrize(
    ("metric_id", "labels", "period", "family", "requires_cancel"),
    [
        (
            "screen_hours.Work/Programming",
            frozenset({"Work/Programming", "Programming"}),
            None,
            "screen_hours.Work/Programming",
            False,
        ),
        (
            "tag_hours.iki-deep",
            frozenset({"iki-deep", "deep"}),
            None,
            "tag_hours.iki-deep",
            False,
        ),
        (
            "github.push.count",
            frozenset({"push", "pushes", "pushed", "pushing"}),
            None,
            "github.push.count",
            False,
        ),
        (
            "github.pr.count",
            frozenset({"pr", "prs", "pull request", "pull requests"}),
            None,
            "github.pr.count",
            False,
        ),
        (
            "calendar.busy_hours",
            frozenset({"busy"}),
            None,
            "calendar.busy_hours",
            False,
        ),
        (
            "feed.item.count",
            frozenset({"feed", "feeds"}),
            None,
            "feed.item.count",
            False,
        ),
        (
            "feed.item.count.hn",
            frozenset({"feed", "feeds"}),
            None,
            "feed.item.count.hn",
            False,
        ),
        (
            "period.last.screen_hours.Work/Programming",
            frozenset({"Work/Programming", "Programming"}),
            "last",
            "screen_hours.Work/Programming",
            False,
        ),
        (
            "period.prior.pushes",
            frozenset({"push", "pushes", "pushed", "pushing"}),
            "prior",
            "pushes",
            False,
        ),
        (
            "period.last.prs",
            frozenset({"pr", "prs", "pull request", "pull requests"}),
            "last",
            "prs",
            False,
        ),
        (
            "period.earlier.tag_hours.iki-deep",
            frozenset({"iki-deep", "deep"}),
            "earlier",
            "tag_hours.iki-deep",
            False,
        ),
        (
            "period.last.cancelled.iki-deep",
            frozenset({"iki-deep", "deep"}),
            "last",
            "cancelled.iki-deep",
            True,
        ),
    ],
)
def test_label_pinned_families_exact(
    metric_id: str,
    labels: frozenset[str],
    period: str | None,
    family: str,
    requires_cancel: bool,
) -> None:
    from framework.briefing.labels import metric_label_binding

    binding = metric_label_binding(metric_id)
    assert binding is not None, metric_id
    assert binding.labels == labels, metric_id
    assert binding.period == period, metric_id
    assert binding.family == family, metric_id
    assert binding.requires_cancel is requires_cancel, metric_id


@pytest.mark.parametrize(
    "metric_id",
    [
        "period.last.github.push.count",
        "period.last.github.pr.count",
        "period.last.calendar.busy_hours",
        "period.last.feed.item.count",
        "period.last.feed.item.count.hn",
        "pushes",
        "prs",
        "cancelled.iki-deep",
        "period.pushes",
        "period.last.",
        "period.someday.pushes",
        "feed.item.count. ",
        "feed.item.count.",
    ],
)
def test_label_unlisted_forms_are_unknown(metric_id: str) -> None:
    from framework.briefing.labels import metric_label_binding

    assert metric_label_binding(metric_id) is None, metric_id
    briefing, context = _label_fresh("Logged 3 synthetic units", metric_id, 3.0)
    assert _codes(evaluate_briefing(briefing, context)) == [
        "L1B_METRIC_LABEL_UNKNOWN"
    ], metric_id


def test_binding_two_refs_wrong_label_fires() -> None:
    briefing, context = _two_ref_fresh(
        "Feed fell from 3 in prior to 1 in last",
        ("period.prior.pushes", 3.0),
        ("period.last.pushes", 1.0),
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_METRIC_LABEL_MISSING"]


def test_period_word_required_on_since_last_period_refs() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][2]
    claim["text"] = "Pushes rose by 1 since the parent briefing"
    claim["metric_refs"] = [{"metric_id": "period.last.pushes", "value": 1.0}]
    values = dict(case.context.metrics.values)
    values["period.last.pushes"] = 5.0
    parent_values = dict(case.context.parent_metrics.values)  # type: ignore[union-attr]
    parent_values["period.last.pushes"] = 4.0
    context = case.context.model_copy(
        update={
            "metrics": MetricSnapshot(values=values),
            "parent_metrics": MetricSnapshot(values=parent_values),
        }
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_PERIOD_WORD_MISSING"]

    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][2]
    claim["text"] = "Pushes rose by 1 and 2 in last since the parent briefing"
    claim["metric_refs"] = [
        {"metric_id": "period.prior.pushes", "value": 1.0},
        {"metric_id": "period.last.pushes", "value": 2.0},
    ]
    values = dict(case.context.metrics.values)
    values["period.prior.pushes"] = 6.0
    values["period.last.pushes"] = 7.0
    parent_values = dict(case.context.parent_metrics.values)  # type: ignore[union-attr]
    parent_values["period.prior.pushes"] = 5.0
    parent_values["period.last.pushes"] = 5.0
    context = case.context.model_copy(
        update={
            "metrics": MetricSnapshot(values=values),
            "parent_metrics": MetricSnapshot(values=parent_values),
        }
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_PERIOD_WORD_MISSING"]


def test_too_many_window_and_period_same_family() -> None:
    briefing, context = _two_ref_fresh(
        "Programming reached 90 in last with 90 overall",
        ("screen_hours.Work/Programming", 90.0),
        ("period.last.screen_hours.Work/Programming", 90.0),
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_TOO_MANY_METRICS"]


def test_too_many_different_families_all_period() -> None:
    briefing, context = _two_ref_fresh(
        "Pushes reached 3 in prior and PRs reached 2 in last",
        ("period.prior.pushes", 3.0),
        ("period.last.prs", 2.0),
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_TOO_MANY_METRICS"]


def test_direction_both_lists_fire_when_one_side_agrees() -> None:
    briefing, context = _two_ref_fresh(
        "Pushes rose then fell from 1 in prior to 3 in last",
        ("period.prior.pushes", 1.0),
        ("period.last.pushes", 3.0),
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][2]
    claim["text"] = "Pushes rose then fell by 1 since the parent briefing"
    assert _codes(evaluate_briefing(briefing, case.context)) == [
        "L1B_DIRECTION_MISMATCH"
    ]


def test_direction_zero_delta_with_word_fires() -> None:
    case = base_case_with_parent("builder")
    briefing = copy.deepcopy(case.briefing)
    claim = _section(briefing, "since_last")["claims"][1]
    claim["text"] = "Walk total fell since the parent briefing"
    assert _codes(evaluate_briefing(briefing, case.context)) == [
        "L1B_DIRECTION_MISMATCH"
    ]


def test_direction_fell_with_no_change_fires() -> None:
    briefing, context = _two_ref_fresh(
        "Pushes fell from 3 in earlier to 3 in last",
        ("period.earlier.pushes", 3.0),
        ("period.last.pushes", 3.0),
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_direction_rose_with_mixed_changes_fires() -> None:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = "Pushes rose from 1 in earlier to 3 in prior and to 2 in last"
    claim["metric_refs"] = [
        {"metric_id": "period.earlier.pushes", "value": 1.0},
        {"metric_id": "period.prior.pushes", "value": 3.0},
        {"metric_id": "period.last.pushes", "value": 2.0},
    ]
    values = dict(context.metrics.values)
    values["period.earlier.pushes"] = 1.0
    values["period.prior.pushes"] = 3.0
    values["period.last.pushes"] = 2.0
    context = context.model_copy(update={"metrics": MetricSnapshot(values=values)})
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


_UP_LIST = (
    "up",
    "rose",
    "rise",
    "rises",
    "rising",
    "risen",
    "increase",
    "increased",
    "increases",
    "increasing",
    "more",
    "higher",
    "grew",
    "grow",
    "grows",
    "growing",
    "grown",
)
_DOWN_LIST = (
    "down",
    "fell",
    "fall",
    "falls",
    "falling",
    "fallen",
    "decrease",
    "decreased",
    "decreases",
    "decreasing",
    "less",
    "fewer",
    "lower",
    "dropped",
    "drop",
    "drops",
    "dropping",
)


@pytest.mark.parametrize("word", _UP_LIST + _DOWN_LIST)
def test_direction_every_listed_word(word: str) -> None:
    rising = word in _UP_LIST

    def _run(prior_value: float, last_value: float) -> list[str]:
        briefing, context = _two_ref_fresh(
            f"Pushes {word} from 1 in prior to 3 in last",
            ("period.prior.pushes", prior_value),
            ("period.last.pushes", last_value),
        )
        return _codes(evaluate_briefing(briefing, context))

    assert _run(1.0, 3.0) == ([] if rising else ["L1B_DIRECTION_MISMATCH"]), word
    assert _run(3.0, 1.0) == (["L1B_DIRECTION_MISMATCH"] if rising else []), word


def test_direction_underscore_word_is_free() -> None:
    briefing, context = _label_fresh(
        "Up_stream pushes reached 3 in last", "period.last.pushes", 3.0
    )
    assert evaluate_briefing(briefing, context).passed is True


def _followup_fresh(
    text: str, refs: list[tuple[str, float]]
) -> tuple[dict[str, Any], Any]:
    briefing, context = _fresh()
    claim = _section(briefing, "working")["claims"][0]
    claim["text"] = text
    claim["metric_refs"] = [
        {"metric_id": metric_id, "value": value} for metric_id, value in refs
    ]
    values = dict(context.metrics.values)
    for metric_id, value in refs:
        values[metric_id] = value
    return briefing, context.model_copy(
        update={"metrics": MetricSnapshot(values=values)}
    )


def test_direction_label_words_are_free() -> None:
    briefing, context = _followup_fresh(
        "Follow Up reached 2 in last",
        [("period.last.screen_hours.Work/Follow Up", 2.0)],
    )
    assert evaluate_briefing(briefing, context).passed is True
    briefing, context = _followup_fresh(
        "Follow Up fell from 3 in prior to 2 in last",
        [
            ("period.prior.screen_hours.Work/Follow Up", 3.0),
            ("period.last.screen_hours.Work/Follow Up", 2.0),
        ],
    )
    assert evaluate_briefing(briefing, context).passed is True
    briefing, context = _followup_fresh(
        "Follow Up rose from 3 in prior to 2 in last",
        [
            ("period.prior.screen_hours.Work/Follow Up", 3.0),
            ("period.last.screen_hours.Work/Follow Up", 2.0),
        ],
    )
    assert _codes(evaluate_briefing(briefing, context)) == ["L1B_DIRECTION_MISMATCH"]


def test_commitment_unavailable_skips_unknown_ids() -> None:
    briefing, context = _fresh()
    context = context.model_copy(
        update={"commitments_available": False, "commitments": ()}
    )
    result = evaluate_briefing(briefing, context)
    assert _codes(result) == ["L1_COMMITMENTS_UNAVAILABLE"]
    assert result.violations[0].location == "briefing"


def test_text_check_codes_verdicts() -> None:
    assert text_check_codes("Note " + "ghp_" + "a" * 20) == ("L1_SECRET",)
    assert text_check_codes("Contact synthetic@example.invalid for notes") == (
        "L1_PII",
    )
    assert text_check_codes("You should log the synthetic result") == ("L1_ADVICE",)
    assert text_check_codes("Notes mention quetzal-garden here") == ()
    assert text_check_codes(
        "Notes mention quetzal-garden here",
        private_terms=("quetzal-garden",),
    ) == ("L1_PRIVATE_TERM",)
    assert text_check_codes("Seen Invented Calendar Title Zqx today") == ()
    assert text_check_codes(
        "Seen Invented Calendar Title Zqx today",
        forbidden_raw_literals=("Invented Calendar Title Zqx",),
    ) == ("L1_RAW_VALUE",)
    assert text_check_codes("Plan work on ikigai-loop docs") == ()
    assert text_check_codes("Build the synthetic parser sketch") == ()


def _window(
    start: str,
    end: str,
    *,
    slot: str,
    busy: list[tuple[str, str]],
    free: list[tuple[str, str]],
) -> tuple[str, ...]:
    return action_window_codes(
        datetime.fromisoformat(start),
        datetime.fromisoformat(end),
        slot=datetime.fromisoformat(slot),
        busy_intervals=tuple(
            TimeInterval(start=datetime.fromisoformat(s), end=datetime.fromisoformat(e))
            for s, e in busy
        ),
        free_intervals=tuple(
            TimeInterval(start=datetime.fromisoformat(s), end=datetime.fromisoformat(e))
            for s, e in free
        ),
    )


def _iso_dt(day: int, hour: int, minute: int) -> str:
    return f"2026-10-{day:02d}T{hour:02d}:{minute:02d}:00+01:00"


def test_action_window_codes_verdicts() -> None:
    slot = _iso_dt(31, 13, 0)
    busy = [(_iso_dt(31, 15, 0), _iso_dt(31, 16, 0))]
    free = [(_iso_dt(31, 11, 0), _iso_dt(31, 23, 30))]
    assert (
        _window(
            _iso_dt(31, 14, 0), _iso_dt(31, 14, 45), slot=slot, busy=busy, free=free
        )
        == ()
    )
    assert (
        _window(_iso_dt(31, 16, 0), _iso_dt(31, 17, 0), slot=slot, busy=busy, free=free)
        == ()
    )
    assert _window(
        _iso_dt(31, 12, 0), _iso_dt(31, 12, 30), slot=slot, busy=busy, free=free
    ) == ("L1_ACTION_BEFORE_SLOT",)
    narrow_free = [(_iso_dt(31, 11, 0), _iso_dt(31, 14, 0))]
    assert _window(
        _iso_dt(31, 15, 30),
        _iso_dt(31, 16, 30),
        slot=slot,
        busy=busy,
        free=narrow_free,
    ) == ("L1_ACTION_IN_BUSY_INTERVAL",)
    assert _window(
        _iso_dt(31, 14, 30), _iso_dt(31, 15, 0), slot=slot, busy=busy, free=narrow_free
    ) == ("L1_ACTION_NOT_FREE",)
    touching_free = [
        (_iso_dt(31, 13, 0), _iso_dt(31, 15, 0)),
        (_iso_dt(31, 15, 0), _iso_dt(31, 18, 0)),
    ]
    assert (
        _window(
            _iso_dt(31, 14, 0),
            _iso_dt(31, 16, 0),
            slot=slot,
            busy=[],
            free=touching_free,
        )
        == ()
    )
    assert _window(
        _iso_dt(31, 12, 0), _iso_dt(31, 15, 30), slot=slot, busy=busy, free=free
    ) == ("L1_ACTION_BEFORE_SLOT", "L1_ACTION_IN_BUSY_INTERVAL")
