"""Ticket 16b: R1b case-file tests (D11 families a-e).

Runs against the committed fixture in every session, and against the real
``evals/r1b_cases.json`` only when that file exists. Real-file failure
output names case ids and rule names only, never case text.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from evals import r1b
from evals.r1b import FIXTURE_CASES_SHA256, R1bCase, load_cases

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json"
REAL_PATH = REPO_ROOT / "evals" / "r1b_cases.json"

BANNED_WORDS = ("coach", "wellness", "wellbeing", "mental", "recovery")


def _sources() -> list[tuple[str, Path]]:
    paths = [("fixture", FIXTURE_PATH)]
    if REAL_PATH.exists():
        paths.append(("real", REAL_PATH))
    return paths


def _raw_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _mutate_case(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    mutated = json.loads(json.dumps(base))
    mutated.update(overrides)
    return mutated


def _write_tmp_cases(tmp_path: Path, raw: list[dict[str, Any]]) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def _fail_message(excinfo: pytest.ExceptionInfo[Any]) -> str:
    return str(excinfo.value)


# (a) Shape ---------------------------------------------------------------


def test_fixture_loads_four_cases_in_order() -> None:
    cases = load_cases(FIXTURE_PATH)
    assert [case.id for case in cases] == ["r1b-f01", "r1b-f02", "r1b-f03", "r1b-f04"]
    assert [case.trap for case in cases] == [
        None,
        None,
        "orphan-number",
        "flat-direction",
    ]
    assert cases[0].parent_snapshot is None
    assert cases[1].parent_snapshot is not None


def test_shape_holds_on_every_source() -> None:
    for _name, path in _sources():
        cases = load_cases(path)
        assert len(cases) >= 1
        for case in cases:
            assert isinstance(case, R1bCase)


def test_duplicate_ids_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    doubled = raw + [json.loads(json.dumps(raw[0]))]
    path = _write_tmp_cases(tmp_path, doubled)
    with pytest.raises(ValueError, match="duplicate") as excinfo:
        load_cases(path)
    message = _fail_message(excinfo)
    assert "r1b-f01" in message


def test_sensitive_fact_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = json.loads(json.dumps(raw[1]))
    mutated["facts"][0]["tier"] = "sensitive"
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="sensitive") as excinfo:
        load_cases(path)
    assert "r1b-f02" in _fail_message(excinfo)


def test_wrong_profile_commitment_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = json.loads(json.dumps(raw[0]))
    mutated["commitments"][0]["profile_id"] = "disconnect"
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="profile") as excinfo:
        load_cases(path)
    assert "r1b-f01" in _fail_message(excinfo)


def test_non_quarter_hour_slot_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = _mutate_case(
        raw[0],
        slot="2026-11-03T15:37:00+01:00",
        hour={
            "start": "2026-11-03T15:37:00+01:00",
            "end": "2026-11-03T16:37:00+01:00",
        },
    )
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="quarter") as excinfo:
        load_cases(path)
    assert "r1b-f01" in _fail_message(excinfo)


def test_slot_outside_window_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = _mutate_case(
        raw[0],
        slot="2026-11-25T15:30:00+01:00",
        hour={
            "start": "2026-11-25T15:30:00+01:00",
            "end": "2026-11-25T16:30:00+01:00",
        },
    )
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="window") as excinfo:
        load_cases(path)
    assert "r1b-f01" in _fail_message(excinfo)


def test_wrong_offset_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = _mutate_case(
        raw[0],
        slot="2026-11-03T15:30:00+00:00",
        hour={
            "start": "2026-11-03T15:30:00+00:00",
            "end": "2026-11-03T16:30:00+00:00",
        },
    )
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="offset") as excinfo:
        load_cases(path)
    assert "r1b-f01" in _fail_message(excinfo)


def test_wrong_hour_rejected(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = _mutate_case(
        raw[0],
        hour={
            "start": "2026-11-03T15:30:00+01:00",
            "end": "2026-11-03T16:00:00+01:00",
        },
    )
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError, match="hour") as excinfo:
        load_cases(path)
    assert "r1b-f01" in _fail_message(excinfo)


def test_banned_words_absent_from_every_source() -> None:
    for _name, path in _sources():
        text = path.read_text(encoding="utf-8").casefold()
        for word in BANNED_WORDS:
            assert word not in text


def test_failure_output_names_ids_not_text(tmp_path: Path) -> None:
    raw = _raw_cases(FIXTURE_PATH)
    mutated = json.loads(json.dumps(raw[0]))
    mutated["commitments"][0]["profile_id"] = "disconnect"
    statement = mutated["facts"][0]["statement"]
    assert statement
    path = _write_tmp_cases(tmp_path, [mutated])
    with pytest.raises(ValueError) as excinfo:
        load_cases(path)
    message = _fail_message(excinfo)
    assert "r1b-f01" in message
    assert statement not in message


# (b) Number agreement ------------------------------------------------------


def test_fact_numbers_backed_outside_exempt_classes() -> None:
    from framework.briefing.gate import ref_backs_token
    from framework.briefing.numbers import extract_number_tokens

    for _name, path in _sources():
        for case in load_cases(path):
            if case.trap in ("orphan-number", "injection"):
                continue
            for fact in case.facts:
                for token in extract_number_tokens(fact.statement, {fact.id}):
                    assert any(
                        ref_backs_token(value, token.places, abs(token.value))
                        for value in case.metrics.values()
                    ), f"{case.id} number-agreement"


def test_orphan_case_holds_an_unbacked_number() -> None:
    from framework.briefing.gate import ref_backs_token
    from framework.briefing.numbers import extract_number_tokens

    cases = load_cases(FIXTURE_PATH)
    orphans = [case for case in cases if case.trap == "orphan-number"]
    assert orphans
    for case in orphans:
        assert any(
            not any(
                ref_backs_token(value, token.places, abs(token.value))
                for value in case.metrics.values()
            )
            for fact in case.facts
            for token in extract_number_tokens(fact.statement, {fact.id})
        ), f"{case.id} orphan-number"


# (c) Admissibility ---------------------------------------------------------


def build_minimal_draft(case: R1bCase) -> dict[str, Any]:
    """The pinned D11c recipe: one claim from the case's own data."""
    from evals.r1b import case_parent_briefing
    from framework.proposal.prompt import (
        compute_deltas,
        display_value,
        offered_metrics,
    )

    offered = offered_metrics(dict(case.metrics))
    ordered = sorted(offered, key=r1b.metric_sort_key)
    first_id = ordered[0]
    binding = r1b.metric_binding_for(first_id)
    assert binding is not None
    label = r1b.shortest_label(binding)
    value = display_value(offered[first_id])
    words: list[str] = [label.capitalize(), "was", value]
    if "hours" in first_id:
        words.append("hours" if offered[first_id] != 1 else "hour")
    if binding.period is not None:
        words.extend(["in", "the", binding.period, "period"])
    else:
        words.extend(["across", "the", "window"])
    if "cancelled." in first_id:
        words.append("cancelled")
    overall = [
        {"text": " ".join(words), "fact_ids": [], "metric_refs": [first_id]},
    ]
    payload: dict[str, Any] = {
        "commitment_id": case.commitments[0].id,
        "overall_state": overall,
        "working": [],
        "not_working": [],
    }
    parent, parent_values = case_parent_briefing(case)
    if parent is not None and parent_values is not None:
        deltas = compute_deltas(offered, parent_values)
        assert deltas
        delta = deltas[0]
        delta_binding = r1b.metric_binding_for(delta.metric_id)
        assert delta_binding is not None
        delta_label = r1b.shortest_label(delta_binding)
        sentence = [delta_label.capitalize(), "changed", "by", delta.display]
        if delta_binding.period is not None:
            sentence.extend(["in", "the", delta_binding.period, "period"])
        if "hours" in delta.metric_id:
            sentence.append("hours" if delta.value != 1 else "hour")
        if "cancelled." in delta.metric_id:
            sentence.append("cancelled")
        payload["since_last"] = [
            {
                "text": " ".join(sentence),
                "fact_ids": [],
                "metric_refs": [delta.metric_id],
            },
        ]
    return payload


def test_every_case_admits_its_minimal_draft() -> None:
    from framework.briefing.gate import evaluate_briefing
    from framework.proposal.assembly import assemble_briefing
    from framework.proposal.prompt import compute_deltas, offered_metrics
    from framework.proposal.schemas import ProposalDraft, parse_draft

    for _name, path in _sources():
        for case in load_cases(path):
            context = r1b.build_case_context(case)
            hour = r1b.build_case_hour(case)
            offered = offered_metrics(dict(case.metrics))
            parent_values = (
                dict(context.parent_metrics.values)
                if context.parent_metrics is not None
                else None
            )
            deltas = (
                compute_deltas(offered, parent_values)
                if parent_values is not None
                else ()
            )
            draft = parse_draft(
                json.dumps(build_minimal_draft(case)),
                has_facts=True,
                has_metrics=True,
                has_parent=context.parent_briefing is not None,
            )
            assert isinstance(draft, ProposalDraft), f"{case.id} admissibility"
            briefing = assemble_briefing(
                draft,
                profile_id=case.profile,
                subject_id=r1b.SUBJECT_ID,
                slot=case.slot,  # type: ignore[arg-type]
                parent=context.parent_briefing,
                commitments_by_id={c.id: c for c in case.commitments},
                snapshot=dict(case.metrics),
                parent_snapshot=parent_values,
                deltas={d.metric_id: d.value for d in deltas},
                hour=hour,
            )
            result = evaluate_briefing(briefing, context)
            assert result.passed, f"{case.id} admissibility: " + "; ".join(
                v.code for v in result.violations
            )


def test_fixture_proves_the_period_word_fix() -> None:
    cases = {case.id: case for case in load_cases(FIXTURE_PATH)}
    parented = [case for case in cases.values() if case.parent_snapshot is not None]
    assert parented
    assert any(
        "period." in metric_id for case in parented for metric_id in case.metrics
    )


def test_fixture_proves_the_cancelled_fix() -> None:
    cases = load_cases(FIXTURE_PATH)
    assert any(
        "cancelled." in metric_id for case in cases for metric_id in case.metrics
    )


# (d) Prompt hygiene --------------------------------------------------------


def test_prompt_hygiene_on_every_case_and_arm() -> None:
    from evals.r1b import build_case_context
    from evals.r1b_prompts import build_plain_prompt, build_plain_response_schema
    from framework.briefing.gate import (
        action_window_codes,
        scan_outbound_text,
        slot_window_codes,
    )
    from framework.proposal.hour import allowed_windows
    from framework.proposal.prompt import build_prompt, offered_metrics

    for _name, path in _sources():
        for case in load_cases(path):
            context = build_case_context(case)
            hour = r1b.build_case_hour(case)
            deltas = r1b.offered_deltas_for(case)
            product = build_prompt(
                profile_id=case.profile,
                profile_name=case.profile.capitalize(),
                facts=list(case.facts),
                metrics=dict(case.metrics),
                deltas=deltas,
                commitments=list(case.commitments),
                hour=hour,
                policy="",
            )
            plain = build_plain_prompt(
                profile_name=case.profile.capitalize(),
                hour=hour,
                facts=list(case.facts),
                metrics=dict(case.metrics),
                deltas=deltas,
                commitments=list(case.commitments),
            )
            void: tuple[str, ...] = ()
            assert (
                scan_outbound_text(
                    product,
                    private_terms=void,
                    private_terms_available=True,
                    forbidden_raw_literals=void,
                )
                == ()
            ), f"{case.id} hygiene"
            assert (
                scan_outbound_text(
                    plain,
                    private_terms=void,
                    private_terms_available=True,
                    forbidden_raw_literals=void,
                )
                == ()
            ), f"{case.id} hygiene"
            assert set(case.metrics) == set(offered_metrics(dict(case.metrics))), (
                f"{case.id} offered"
            )
            assert slot_window_codes(case.slot, context.limits) == (), (  # type: ignore[arg-type]
                f"{case.id} slot-window"
            )
            assert (
                action_window_codes(
                    hour.start,
                    hour.end,
                    slot=case.slot,  # type: ignore[arg-type]
                    busy_intervals=(),
                    free_intervals=allowed_windows(case.slot, context.limits),  # type: ignore[arg-type]
                )
                == ()
            ), f"{case.id} action-window"
            if case.parent_snapshot is not None:
                assert deltas, f"{case.id} parent-delta"
            _schema = build_plain_response_schema(has_parent=bool(deltas))
            assert _schema["type"] == "object"


# (e) Freeze ------------------------------------------------------------------


def test_fixture_hash_pinned() -> None:
    digest = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert digest == FIXTURE_CASES_SHA256


def test_real_file_hash_pinned_when_present() -> None:
    if not REAL_PATH.exists():
        pytest.skip("real case file not in the tree during implementation")
    digest = hashlib.sha256(REAL_PATH.read_bytes()).hexdigest()
    assert digest == r1b.EXPECTED_CASES_SHA256


def test_result_rows_require_the_case_file(tmp_path: Path) -> None:
    results = tmp_path / "r1b"
    results.mkdir()
    (results / "row.jsonl").write_text("{}\n", encoding="utf-8")
    missing = tmp_path / "missing-cases.json"
    assert not missing.exists()
    with pytest.raises(AssertionError, match="case-file-missing"):
        r1b.require_cases_file_for_results(missing, results)
    r1b.require_cases_file_for_results(FIXTURE_PATH, tmp_path / "empty")
