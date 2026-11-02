"""Ticket 16b: summary tests over the committed fixtures (D10, D19)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from evals.r1b import load_cases
from evals.r1b_summary import CATEGORY_TABLE, mcnemar_exact, render_summary

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CASES = REPO_ROOT / "tests" / "fixtures" / "r1b_cases_fixture.json"
FIXTURE_ROWS = REPO_ROOT / "tests" / "fixtures" / "r1b_results_fixture.jsonl"
EXPECTED_MD = REPO_ROOT / "tests" / "fixtures" / "r1b_expected.md"


def _rows() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in FIXTURE_ROWS.read_text(encoding="utf-8").splitlines()
    ]


def _cases() -> list[Any]:
    return list(load_cases(FIXTURE_CASES))


def _render(rows: list[dict[str, Any]] | None = None) -> str:
    return render_summary(_rows() if rows is None else rows, _cases())


def test_fixture_rendering_byte_equals_expected() -> None:
    assert _render() == EXPECTED_MD.read_text(encoding="utf-8")


def test_fixed_preamble_present() -> None:
    text = _render()
    assert text.startswith("# R1b — models on the gate\n")
    assert "framework/proposal/prompt.py" in text
    assert "evals/r1b_prompts.py" in text
    assert (
        "[docs/plans/016b-models-on-the-gate.md](plans/016b-models-on-the-gate.md)"
        in text
    )
    assert "Claude Code" in text
    assert "the driver" not in text
    assert "15,900" in text
    assert "temperature 0" in text
    assert "32768" in text
    assert "muse-wonder-full-1.0" in text
    assert "Contributor mode" in text
    assert "private-term check is not exercised" in text
    assert "A gate pass does not show a sentence is true" in text
    assert "a gate failure does not show a sentence is false" in text
    assert "generalises past them not at all" in text


def test_zero_denominator_wording() -> None:
    text = _render()
    assert "ratio undefined" in text
    assert "not evaluable" in text


def test_mechanical_verdicts_and_overall_line() -> None:
    text = _render()
    assert "the plain prompt fails at least 3 times as often" in text
    lines = text.splitlines()
    verdicts = [line for line in lines if line.startswith("verdict:")]
    assert any("muse-wonder-1.0 (high): did not hold" in line for line in verdicts)
    assert any("muse-spark-1.3 (low): not evaluable" in line for line in verdicts)
    overall = [line for line in lines if line.startswith("overall:")]
    assert len(overall) == 1
    assert "did not hold" in overall[0]


def test_paired_exclusions_and_retry_unavailable_counted() -> None:
    text = _render()
    assert "excluded" in text
    assert "retry came back unavailable" in text
    assert "stayed failed" in text


def test_mcnemar_known_pairs() -> None:
    assert mcnemar_exact(1, 1) == 1.0
    assert mcnemar_exact(2, 0) == 0.5
    assert mcnemar_exact(0, 0) == 1.0


def test_no_discordant_pairs_line() -> None:
    passing = {
        "schema": 1,
        "case_id": "r1b-f01",
        "trap": None,
        "arm": "product",
        "model": "m",
        "model_reported": "m",
        "effort": "high",
        "attempt": 1,
        "execution": 1,
        "raw_text": "{}",
        "parsed_ok": True,
        "blocked": False,
        "codes": [],
        "latency_ms": 5,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "reasoning_tokens": None,
        "finish_reason": "stop",
        "prompt_hash": "x",
        "cases_sha256": "y",
        "gate_commit": "0" * 40,
        "gate_hash": "c" * 64,
        "transport": "muse",
        "muse_version": None,
        "harness_rules_file": False,
        "recorded_at": "2026-11-02T09:00:00+01:00",
    }
    rows = [
        dict(passing),
        dict(passing, arm="plain"),
    ]
    text = render_summary(rows, _cases())
    assert "no discordant pairs" in text


def _not_draft_row(arm: str = "product") -> dict[str, Any]:
    return {
        "schema": 1,
        "case_id": "r1b-f01",
        "trap": None,
        "arm": arm,
        "model": "m",
        "model_reported": "m",
        "effort": "high",
        "attempt": 1,
        "execution": 1,
        "raw_text": "{}",
        "parsed_ok": True,
        "blocked": False,
        "codes": [["L1_ACTION_NOT_FREE", "sections[overall_state]"]],
        "latency_ms": 5,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "reasoning_tokens": None,
        "finish_reason": "stop",
        "prompt_hash": "x",
        "cases_sha256": "y",
        "gate_commit": "0" * 40,
        "gate_hash": "c" * 64,
        "transport": "muse",
        "muse_version": None,
        "harness_rules_file": False,
        "recorded_at": "2026-11-02T09:00:00+01:00",
    }


def test_not_a_draft_outcome_is_neither_pass_nor_failure() -> None:
    text = render_summary(
        [_not_draft_row("product"), _not_draft_row("plain")], _cases()
    )
    assert "first-draft passes: 0" in text
    assert "first-draft gate failures: 0" in text
    assert text.count("not-a-draft-outcome first drafts: 1") == 2


def test_cached_tokens_median_printed() -> None:
    first = _not_draft_row("product")
    first["codes"] = []
    first["cached_tokens"] = 4
    second = _not_draft_row("product")
    second["codes"] = []
    second["case_id"] = "r1b-f02"
    second["cached_tokens"] = 6
    text = render_summary([first, second], _cases())
    assert "first-attempt cached tokens median: 5" in text


def test_missing_cached_tokens_prints_not_reported() -> None:
    assert "first-attempt cached tokens median: not reported" in _render()


def test_overview_table_opens_each_gate_identity() -> None:
    text = _render()
    assert "| model | effort | arm | counted |" in text
    gate_heading = next(
        line for line in text.splitlines() if line.startswith("## Live rows")
    )
    first_table = text.splitlines().index(gate_heading)
    first_header = next(
        index
        for index, line in enumerate(text.splitlines())
        if index > first_table and line.startswith("| model |")
    )
    assert first_header == first_table + 2
    assert "| muse-wonder-1.0 | high | product |" in text
    assert "latency median s" in text


def test_detail_sections_follow_matrix_order() -> None:
    text = _render()
    headings = [line for line in text.splitlines() if line.startswith("### ")]
    assert headings.index("### muse-wonder-1.0 (high)") < headings.index(
        "### muse-spark-1.3 (low)"
    )


def test_unknown_rows_sort_after_the_matrix() -> None:
    rows = _rows()
    extra = dict(rows[0])
    extra["model"] = "zzz-custom"
    extra["effort"] = "high"
    text = render_summary([*rows, extra], _cases())
    headings = [line for line in text.splitlines() if line.startswith("### ")]
    assert headings[-1] == "### zzz-custom (high)"


def test_trap_split_prints_every_present_class_with_zeros() -> None:
    text = _render()
    for trap in ("clean", "flat-direction", "orphan-number"):
        line = next(
            line
            for line in text.splitlines()
            if line.startswith(f"- {trap}:") and "counted" in line
        )
        assert " of " in line


def test_unavailable_counts_every_execution() -> None:
    first = _not_draft_row("product")
    first["parsed_ok"] = False
    first["codes"] = [["MODEL_UNAVAILABLE", "timeout"]]
    first["raw_text"] = ""
    first["execution"] = 1
    second = _not_draft_row("product")
    second["codes"] = []
    second["execution"] = 2
    text = render_summary([first, second], _cases())
    assert "cases counted: 1" in text
    assert "unavailable first attempts: 1" in text


def test_ended_passing_and_unparseable_recovered_lines() -> None:
    text = _render()
    assert "ended passing within one retry:" in text
    ended = next(
        line
        for line in text.splitlines()
        if line.startswith("ended passing within one retry:")
    )
    assert " of " in ended
    assert "unparseable first drafts recovered by retry:" in text


def test_overall_line_states_its_rule() -> None:
    text = _render()
    overall = next(line for line in text.splitlines() if line.startswith("overall:"))
    assert "did not hold if any row did not hold" in overall
    assert "held if every row held" in overall
    assert "otherwise not evaluable" in overall


def test_wording_split_says_above() -> None:
    text = _render()
    assert "the wording split above" in text
    assert "the wording split below" not in text


def test_local_row_prints_not_applicable() -> None:
    row = _not_draft_row("product")
    row["codes"] = []
    row["transport"] = "local"
    row["effort"] = "none"
    row["model"] = "muse-glimmer-30b"
    text = render_summary([row, dict(row, arm="plain")], _cases())
    assert "muse versions seen: not applicable" in text
    assert "rules-file values seen: not applicable" in text


def test_gate_code_table_covers_every_gate_code_once() -> None:
    source = (REPO_ROOT / "framework" / "briefing" / "gate.py").read_text(
        encoding="utf-8"
    )
    names = set(re.findall(r'"(L\d[A-Z0-9_]*)"', source)) - {"L0", "L1"}
    table: list[str] = [code for _category, codes in CATEGORY_TABLE for code in codes]
    assert sorted(names) == sorted(table)
    assert len(table) == len(set(table))


def test_third_arm_prints_without_moving_verdicts() -> None:
    base = _render()
    extra = dict(_rows()[0])
    extra["arm"] = "zzz-custom"
    extra["codes"] = [["L1_ADVICE", "sections[overall_state].claims[c-x]"]]
    with_extra = render_summary([*_rows(), extra], _cases())

    def _verdict_lines(text: str) -> list[str]:
        return [
            line
            for line in text.splitlines()
            if line.startswith(("verdict:", "overall:", "paired:"))
        ]

    assert _verdict_lines(base) == _verdict_lines(with_extra)
    assert "arm: zzz-custom" in with_extra


def test_identities_never_mixed() -> None:
    other = dict(_rows()[0])
    other["gate_hash"] = "d" * 64
    other["gate_commit"] = "1" * 40
    text = render_summary([_rows()[0], other], _cases())
    assert text.count("gate cccccccccc") >= 1
    assert "gate dddddddddd" in text


def _paired_row(arm: str, case_id: str, failed: bool) -> dict[str, Any]:
    codes: list[list[str]] = (
        [["L1_ADVICE", "sections[overall_state].claims[c-x]"]] if failed else []
    )
    return {
        "schema": 1,
        "case_id": case_id,
        "trap": None,
        "arm": arm,
        "model": "m",
        "model_reported": "m",
        "effort": "high",
        "attempt": 1,
        "execution": 1,
        "raw_text": "{}",
        "parsed_ok": True,
        "blocked": False,
        "codes": codes,
        "latency_ms": 5,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "reasoning_tokens": None,
        "finish_reason": "stop",
        "prompt_hash": "x",
        "cases_sha256": "y",
        "gate_commit": "0" * 40,
        "gate_hash": "c" * 64,
        "transport": "muse",
        "muse_version": None,
        "harness_rules_file": False,
        "recorded_at": "2026-11-02T09:00:00+01:00",
    }


def _coded_row(arm: str, case_id: str, codes: list[list[str]]) -> dict[str, Any]:
    row = _paired_row(arm, case_id, False)
    row["codes"] = codes
    return row


def test_tiny_p_prints_less_than() -> None:
    ids = [f"tiny-{index:02d}" for index in range(20)]
    rows: list[dict[str, Any]] = []
    for case_id in ids:
        rows.append(_paired_row("product", case_id, False))
        rows.append(_paired_row("plain", case_id, True))
    text = render_summary(rows, _cases())
    line = next(
        line
        for line in text.splitlines()
        if line.startswith("paired McNemar exact two-sided p:")
    )
    assert line == "paired McNemar exact two-sided p: p < 0.0001"


def test_headline_latency_has_one_decimal() -> None:
    import re

    text = _render()
    data = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and not line.startswith("| model |")
    ]
    assert data, "expected headline data rows"
    for line in data:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        assert re.fullmatch(r"\d+\.\d", cells[-2]), line
        assert re.fullmatch(r"\d+\.\d", cells[-1]), line


def test_beyond_wording_split_counts() -> None:
    wording = [["L1B_PERIOD_WORD_MISSING", "sections[overall_state].claims[c-x]"]]
    beyond = [["L1_ADVICE", "sections[overall_state].claims[c-x]"]]
    mixed = [
        ["L1B_PERIOD_WORD_MISSING", "sections[overall_state].claims[c-x]"],
        ["L1B_DIRECTION_MISMATCH", "sections[overall_state].claims[c-y]"],
    ]
    rows = [
        _coded_row("product", "w-01", wording),
        _coded_row("product", "w-02", beyond),
        _coded_row("product", "w-03", mixed),
        _coded_row("plain", "w-01", wording),
        _coded_row("plain", "w-02", wording),
        _coded_row("plain", "w-03", wording),
    ]
    text = render_summary(rows, _cases())
    assert "fail beyond wording" in text
    headline = next(
        line for line in text.splitlines() if line.startswith("| m | high | product |")
    )
    assert "| 3 | 2 |" in headline
    assert (
        "first-draft gate failures beyond wording or form: "
        "2 (wording or form alone: 1)" in text
    )
    paired_line = next(
        line
        for line in text.splitlines()
        if line.startswith("paired beyond wording or form")
    )
    assert "not registered" in paired_line
    assert "no verdict" in paired_line
    assert "product 2" in paired_line
    assert "plain 0" in paired_line


def _paired_verdict_line(
    ids: list[str], product_bad: set[int], plain_bad: set[int]
) -> str:
    rows: list[dict[str, Any]] = []
    for index, case_id in enumerate(ids):
        rows.append(_paired_row("product", case_id, index in product_bad))
        rows.append(_paired_row("plain", case_id, index in plain_bad))
    text = render_summary(rows, _cases())
    verdicts = [line for line in text.splitlines() if line.startswith("verdict:")]
    assert len(verdicts) == 1
    return verdicts[0]


def test_threefold_verdict_boundary() -> None:
    # Synthetic case ids: the fixture only holds four cases, and the wider
    # boundaries need up to six paired cases.
    ids3 = ["syn-01", "syn-02", "syn-03"]
    ids6 = ["syn-01", "syn-02", "syn-03", "syn-04", "syn-05", "syn-06"]
    assert _paired_verdict_line(ids3, {0}, {0, 1, 2}) == (
        "verdict: m (high): held (product failures 1, plain failures 3)"
    )
    assert _paired_verdict_line(ids3[:2], {0}, {0, 1}) == (
        "verdict: m (high): did not hold (product failures 1, plain failures 2)"
    )
    assert _paired_verdict_line(ids6[:5], {0, 1}, {0, 1, 2, 3, 4}) == (
        "verdict: m (high): did not hold (product failures 2, plain failures 5)"
    )
    assert _paired_verdict_line(ids6, {0, 1}, {0, 1, 2, 3, 4, 5}) == (
        "verdict: m (high): held (product failures 2, plain failures 6)"
    )
    assert _paired_verdict_line(ids6[:4], set(), {0, 1, 2, 3}) == (
        "verdict: m (high): not evaluable "
        "(product failures 0, plain failures 4; ratio undefined)"
    )


def test_staleness_over_live_rows_when_they_exist() -> None:
    live = sorted((REPO_ROOT / "evals" / "results" / "r1b").glob("*.jsonl"))
    doc = REPO_ROOT / "docs" / "r1b.md"
    if not live or not doc.exists():
        pytest.skip("no live rows yet")
    rows: list[dict[str, Any]] = []
    for path in live:
        for line in path.read_text(encoding="utf-8").splitlines():
            rows.append(json.loads(line))
    from evals.r1b import load_cases as _load

    cases_path = REPO_ROOT / "evals" / "r1b_cases.json"
    assert render_summary(rows, list(_load(cases_path))) == doc.read_text(
        encoding="utf-8"
    )
