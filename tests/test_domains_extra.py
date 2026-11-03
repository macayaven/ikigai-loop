"""Ticket 26: extra tests for the R1-R7 rulings (development windows only)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "tests" / "fixtures" / "domains" / "mini"


def _copy_mini(tmp_path: Path) -> Path:
    for name in ("pack.json", "day.csv", "hour.csv"):
        shutil.copy(MINI / name, tmp_path / name)
    return tmp_path


def _refix_sha(pack_dir: Path) -> None:
    data = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    for key in ("day", "hour"):
        raw = (pack_dir / data["sources"][key]["path"]).read_bytes()
        data["sources"][key]["sha256"] = hashlib.sha256(raw).hexdigest()
    (pack_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")


def _load_pack_case(path: Path) -> Any:
    from framework.domains.schema import load_pack

    return load_pack(path)


def test_r1_datetime_dates_grouped_by_day(tmp_path: Path) -> None:
    from framework.domains.csv_adapter import build_reference, window_starts

    pack_dir = _copy_mini(tmp_path)
    for name in ("day.csv", "hour.csv"):
        lines = (pack_dir / name).read_text(encoding="utf-8").splitlines()
        head, rows = lines[0], lines[1:]
        fixed = [head]
        for row in rows:
            cells = row.split(",")
            cells[1] = cells[1] + "T00:00:00"
            fixed.append(",".join(cells))
        (pack_dir / name).write_text("\n".join(fixed) + "\n", encoding="utf-8")
    _refix_sha(pack_dir)
    pack = _load_pack_case(pack_dir / "pack.json")
    assert window_starts(pack, pack_dir) == ["2030-01-07", "2030-01-14"]
    ref = build_reference(pack, pack_dir, "2030-01-07")
    assert ref.metrics["total_rentals.2030-01-07"] == 110
    assert ref.metrics["week_total_rentals"] == 630
    assert ref.metrics["busy_days"] == 2


def test_r1_bad_date_names_source(tmp_path: Path) -> None:
    from framework.domains.csv_adapter import WindowError, build_reference

    pack_dir = _copy_mini(tmp_path)
    lines = (pack_dir / "day.csv").read_text(encoding="utf-8").splitlines()
    head, rows = lines[0], lines[1:]
    cells = rows[0].split(",")
    cells[1] = "not-a-date"
    rows[0] = ",".join(cells)
    (pack_dir / "day.csv").write_text("\n".join([head, *rows]) + "\n", encoding="utf-8")
    _refix_sha(pack_dir)
    pack = _load_pack_case(pack_dir / "pack.json")
    with __import__("pytest").raises(WindowError) as excinfo:
        build_reference(pack, pack_dir, "2030-01-07")
    assert "day" in str(excinfo.value)


def _pack_with_rows_per_date(tmp_path: Path, count: int) -> tuple[Any, Path]:
    from framework.domains.schema import load_pack

    pack_dir = _copy_mini(tmp_path)
    data = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    data["identities"].append(
        {"kind": "rows_per_date", "source": "hour", "count": count}
    )
    (pack_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    return load_pack(pack_dir / "pack.json"), pack_dir


def test_r2_rows_per_date_holds(tmp_path: Path) -> None:
    from framework.domains.csv_adapter import build_reference

    pack, pack_dir = _pack_with_rows_per_date(tmp_path, 2)
    ref = build_reference(pack, pack_dir, "2030-01-07")
    assert [item.kind for item in ref.identities] == [
        "columns_sum",
        "daily_matches",
        "rows_per_date",
    ]
    assert all(item.held for item in ref.identities)


def test_r2_rows_per_date_failure_names_kind_and_date(tmp_path: Path) -> None:
    import pytest

    from framework.domains.csv_adapter import IdentityError, build_reference

    pack, pack_dir = _pack_with_rows_per_date(tmp_path, 3)
    with pytest.raises(IdentityError) as excinfo:
        build_reference(pack, pack_dir, "2030-01-07")
    assert "rows_per_date" in str(excinfo.value)
    assert "2030-01-07" in str(excinfo.value)


def _mini_expected(tmp_path: Path) -> Path:
    from evals.domains_oracle import compute

    result = compute(
        str(MINI / "day.csv"),
        str(MINI / "hour.csv"),
        ["2030-01-07", "2030-01-14"],
        100,
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    out = tmp_path / "mini_expected.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return out


def _freeze_mini(tmp_path: Path, seed: int = 7) -> Path:
    from evals.domains import main

    expected = _mini_expected(tmp_path)
    out = tmp_path / "mini_cases.json"
    code = main(
        [
            "freeze",
            "--pack",
            str(MINI / "pack.json"),
            "--expected",
            str(expected),
            "--seed",
            str(seed),
            "--windows",
            "2030-01-07,2030-01-14",
            "--planted-per-kind",
            "2",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    return out


def test_r3_freeze_mini_two_weeks_two_per_kind(tmp_path: Path) -> None:
    cases_path = _freeze_mini(tmp_path)
    payload = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = payload["cases"]
    controls = [c for c in cases if c["expect"] == "pass"]
    planted = [c for c in cases if c["expect"] == "fail"]
    assert len(controls) == 2
    assert len(planted) == 12
    for case in planted:
        assert case.get("twin")


def test_r3_score_mini_summary_counts(tmp_path: Path) -> None:
    from evals.domains import main

    cases_path = _freeze_mini(tmp_path)
    out = tmp_path / "mini_score.json"
    code = main(
        [
            "score",
            "--pack",
            str(MINI / "pack.json"),
            "--cases",
            str(cases_path),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["controls_total"] == 2
    assert summary["planted_total"] == 12
    counts = [summary["controls_accepted"], summary["planted_caught"]]
    counts.extend(summary["per_kind_caught"].values())
    counts.append(summary["twins_accepted"])
    for item in counts:
        assert re.fullmatch(r"\d+/\d+", item), item


class _FakeClient:
    transport = "fake"
    transport_version = None
    harness_rules_file = None

    def __init__(self, queue: list[Any]) -> None:
        self.queue = list(queue)
        self.requests: list[Any] = []

    def complete(self, request: Any) -> Any:
        self.requests.append(request)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _wonder_response(text: str, latency_ms: int = 1200) -> Any:
    from framework.proposal.core import WonderResponse

    return WonderResponse(
        text=text,
        model_reported="fake-model",
        latency_ms=latency_ms,
        finish_reason="stop",
        prompt_tokens=None,
        completion_tokens=None,
        reasoning_tokens=None,
    )


def _mini_week_proposal(window: str, busy: int, commitment: str) -> str:
    return json.dumps(
        {
            "commitment_id": commitment,
            "claims": [
                {
                    "id": "c1",
                    "text": f"Busy days numbered {busy} in the week of {window}.",
                    "metric_refs": [{"metric_id": "busy_days", "value": busy}],
                    "fact_ids": [],
                }
            ],
        }
    )


def test_r4_wonder_limit_and_resume(tmp_path: Path) -> None:
    queue: list[Any] = [
        _wonder_response(_mini_week_proposal("2030-01-07", 2, "review-capacity")),
        _wonder_response(_mini_week_proposal("2030-01-14", 0, "continue-monitoring")),
    ]
    out = tmp_path / "wonder.jsonl"
    from evals.domains import main

    cases_path = _freeze_mini(tmp_path / "prep")
    base = [
        "wonder",
        "--pack",
        str(MINI / "pack.json"),
        "--cases",
        str(cases_path),
        "--out",
        str(out),
    ]
    assert main([*base, "--limit", "1"], client_factory=lambda: _FakeClient(queue)) == 0
    first = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(first) == 1
    assert json.loads(first[0])["window_start"] == "2030-01-07"
    assert main([*base, "--limit", "1"], client_factory=lambda: _FakeClient(queue)) == 0
    second = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(second) == 2
    assert json.loads(second[1])["window_start"] == "2030-01-14"
    assert main([*base], client_factory=lambda: _FakeClient(queue)) == 0
    third = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(third) == 2


def _summary_attempt(
    commitment_id: str | None,
    passed: bool,
    codes: list[dict[str, str]],
    latency_ms: int,
) -> dict[str, Any]:
    return {
        "number": 1,
        "latency_ms": latency_ms,
        "model_reported": "fake",
        "prompt_sha256": "a" * 64,
        "raw_text": "{}",
        "passed": passed,
        "codes": codes,
        "commitment_id": commitment_id,
        "commitment_matches_expected": True,
        "check_complete": True,
    }


def test_r5_summary_tables(tmp_path: Path) -> None:
    from evals.domains import main

    score_path = tmp_path / "score.json"
    score_path.write_text(
        json.dumps(
            {
                "pack_id": "bikes",
                "git_commit": None,
                "case_sha256": "0" * 64,
                "summary": {
                    "controls_total": 2,
                    "controls_accepted": "2/2",
                    "planted_total": 4,
                    "planted_caught": "3/4",
                    "per_kind_caught": {"wrong_value": "1/2", "wrong_unit": "2/2"},
                    "twins_total": 4,
                    "twins_accepted": "4/4",
                    "misses": [],
                },
                "results": [],
            }
        ),
        encoding="utf-8",
    )
    expected_path = tmp_path / "expected.json"
    expected_path.write_text(
        json.dumps(
            {
                "2030-01-07": {"expected_commitment": "review-capacity"},
                "2030-01-14": {"expected_commitment": "continue-monitoring"},
                "2030-01-21": {"expected_commitment": "continue-monitoring"},
                "2030-01-28": {"expected_commitment": "review-capacity"},
            }
        ),
        encoding="utf-8",
    )
    wonder_path = tmp_path / "wonder.jsonl"
    wonder_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "pack_id": "bikes",
                        "window_start": "2030-01-07",
                        "model": "fake",
                        "effort": "low",
                        "expected_commitment": "review-capacity",
                        "attempts": [
                            {
                                "number": 1,
                                "latency_ms": 1200,
                                "model_reported": "fake",
                                "prompt_sha256": "a" * 64,
                                "raw_text": "{}",
                                "passed": True,
                                "codes": [],
                                "commitment_id": "review-capacity",
                                "commitment_matches_expected": True,
                                "check_complete": True,
                            }
                        ],
                        "first_pass_accepted": True,
                        "repaired": False,
                        "final_passed": True,
                        "transport_error": None,
                        "latency_ms_total": 1200,
                        "git_commit": None,
                        "case_sha256": "0" * 64,
                    }
                ),
                json.dumps(
                    {
                        "pack_id": "bikes",
                        "window_start": "2030-01-14",
                        "model": "fake",
                        "effort": "low",
                        "expected_commitment": "continue-monitoring",
                        "attempts": [
                            _summary_attempt(
                                "continue-monitoring",
                                False,
                                [
                                    {
                                        "code": "L1B_METRIC_VALUE_MISMATCH",
                                        "claim_id": "c1",
                                    }
                                ],
                                1500,
                            ),
                            _summary_attempt("review-capacity", True, [], 2500),
                        ],
                        "first_pass_accepted": False,
                        "repaired": True,
                        "final_passed": True,
                        "transport_error": None,
                        "latency_ms_total": 4000,
                    }
                ),
                json.dumps(
                    {
                        "pack_id": "bikes",
                        "window_start": "2030-01-21",
                        "model": "fake",
                        "effort": "low",
                        "expected_commitment": "continue-monitoring",
                        "attempts": [
                            _summary_attempt(
                                "continue-monitoring",
                                False,
                                [
                                    {
                                        "code": "L1B_METRIC_LABEL_MISSING",
                                        "claim_id": "c1",
                                    }
                                ],
                                800,
                            )
                        ],
                        "first_pass_accepted": False,
                        "repaired": False,
                        "final_passed": False,
                        "transport_error": None,
                        "latency_ms_total": 800,
                    }
                ),
                json.dumps(
                    {
                        "pack_id": "bikes",
                        "window_start": "2030-01-28",
                        "model": "fake",
                        "effort": "low",
                        "expected_commitment": "review-capacity",
                        "attempts": [],
                        "first_pass_accepted": False,
                        "repaired": False,
                        "final_passed": False,
                        "transport_error": "MetaUnavailableError: timeout",
                        "latency_ms_total": 500,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(
            [
                "summary",
                "--score",
                str(score_path),
                "--wonder",
                str(wonder_path),
                "--expected",
                str(expected_path),
            ]
        )
    assert code == 0
    text = buf.getvalue()
    assert "2/2" in text
    assert "3/4" in text
    assert "1/2" in text
    assert re.search(r"\d+\.\d+s", text)
    assert "| first-pass acceptance | 1/4 |" in text
    assert "| repaired | 1/4 |" in text
    assert "| residual failures | 1/4 |" in text
    assert "| transport errors | 1/4 |" in text
    assert "| first-attempt commitment matches oracle | 3/4 |" in text
    assert "| final-attempt commitment matches oracle | 2/4 |" in text
    assert "| median first-attempt latency | 1.2s |" in text
    assert "| median total latency | 1.0s |" in text
    assert "| maximum total latency | 4.0s |" in text
    assert "| L1B_METRIC_LABEL_MISSING | 1 |" in text
    assert "| L1B_METRIC_VALUE_MISMATCH | 1 |" in text


def test_r6_provenance_in_run_and_result_files(tmp_path: Path, capsys: Any) -> None:
    import re as _re

    from framework.domains.__main__ import main as domains_main

    out_file = tmp_path / "run.json"
    proposal = _mini_week_proposal("2030-01-07", 2, "review-capacity")

    def factory() -> _FakeClient:
        return _FakeClient([_wonder_response(proposal)])

    code = domains_main(
        [
            "propose",
            "--pack",
            str(MINI / "pack.json"),
            "--window",
            "2030-01-07",
            "--model",
            "fake-model",
            "--effort",
            "low",
            "--out",
            str(out_file),
        ],
        client_factory=factory,
    )
    capsys.readouterr()
    assert code == 0
    run_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert run_data["pack_id"] == "bikes"
    assert run_data["window_start"] == "2030-01-07"
    assert run_data["model"] == "fake-model"
    assert run_data["effort"] == "low"
    assert run_data["attempts"][0]["model_reported"] == "fake-model"
    assert "git_commit" in run_data
    assert run_data["git_commit"] is None or _re.fullmatch(
        r"[0-9a-f]{40}", run_data["git_commit"]
    )

    from evals.domains import main as eval_main

    cases_path = _freeze_mini(tmp_path / "prov")
    score_out = tmp_path / "score.json"
    assert (
        eval_main(
            [
                "score",
                "--pack",
                str(MINI / "pack.json"),
                "--cases",
                str(cases_path),
                "--out",
                str(score_out),
            ]
        )
        == 0
    )
    score_data = json.loads(score_out.read_text(encoding="utf-8"))
    digest = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    assert score_data["case_sha256"] == digest
    assert "git_commit" in score_data

    wonder_out = tmp_path / "wonder.jsonl"
    queue: list[Any] = [
        _wonder_response(_mini_week_proposal("2030-01-07", 2, "review-capacity")),
        _wonder_response(_mini_week_proposal("2030-01-14", 0, "continue-monitoring")),
    ]
    assert (
        eval_main(
            [
                "wonder",
                "--pack",
                str(MINI / "pack.json"),
                "--cases",
                str(cases_path),
                "--out",
                str(wonder_out),
            ],
            client_factory=lambda: _FakeClient(queue),
        )
        == 0
    )
    lines = wonder_out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        entry = json.loads(line)
        assert entry["pack_id"] == "bikes"
        assert entry["case_sha256"] == digest
        assert "git_commit" in entry
        assert "window_start" in entry


def test_r7_prompt_has_ids_no_threshold_number_no_readme() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import build_prompt
    from framework.domains.schema import load_pack

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    prompt = build_prompt(pack, ref)
    for metric_id in ref.metrics:
        assert metric_id in prompt
    for line in prompt.splitlines():
        lowered = line.lower()
        if "above" in lowered and re.search(r"\d", line):
            assert "number of dates whose" in line, line
        if "threshold" in lowered:
            assert not re.search(r"\d", line), line
    readme_lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    for line in readme_lines:
        stripped = line.strip()
        if len(stripped) >= 30:
            assert stripped not in prompt


def test_f1_collects_commitment_rule_and_checker_findings() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import validate_proposal
    from framework.domains.schema import load_pack

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    draft = json.dumps(
        {
            "commitment_id": "continue-monitoring",
            "claims": [
                {
                    "id": "c1",
                    "text": "Busy days numbered 3 in the week of 2030-01-07.",
                    "metric_refs": [{"metric_id": "busy_days", "value": 3}],
                    "fact_ids": [],
                }
            ],
        }
    )
    result = validate_proposal(pack, ref, draft)
    assert not result.passed
    assert result.codes == (
        ("DOMAIN_COMMITMENT_RULE", "c1"),
        ("L1B_METRIC_VALUE_MISMATCH", "c1"),
    )
    lines = result.feedback().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("DOMAIN_COMMITMENT_RULE c1:")
    assert lines[1].startswith("L1B_METRIC_VALUE_MISMATCH c1:")


def test_f1_unknown_commitment_still_runs_checker() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import validate_proposal
    from framework.domains.schema import load_pack

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    draft = json.dumps(
        {
            "commitment_id": "bogus-commitment",
            "claims": [
                {
                    "id": "c1",
                    "text": "Busy days numbered 3 in the week of 2030-01-07.",
                    "metric_refs": [{"metric_id": "busy_days", "value": 3}],
                    "fact_ids": [],
                }
            ],
        }
    )
    result = validate_proposal(pack, ref, draft)
    assert not result.passed
    assert result.codes == (
        ("DOMAIN_UNKNOWN_COMMITMENT", "c1"),
        ("L1B_METRIC_VALUE_MISMATCH", "c1"),
    )


def test_f2_transport_error_keeps_finished_attempts() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import run_window
    from framework.domains.schema import load_pack
    from framework.proposal.core import MetaUnavailableError

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    bad = _wonder_response(_mini_week_proposal("2030-01-07", 3, "review-capacity"))
    client = _FakeClient([bad, MetaUnavailableError("timeout")])
    run = run_window(pack, ref, client, model="fake", effort="low")
    assert len(run.attempts) == 1
    assert ("L1B_METRIC_VALUE_MISMATCH", "c1") in run.attempts[0].codes
    assert run.transport_error is not None
    assert "timeout" in run.transport_error
    assert "MetaUnavailableError" in run.transport_error
    assert run.first_pass_accepted is False
    assert run.repaired is False
    assert run.final_passed is False
    assert run.latency_ms_total == 1200


def test_f3_attempt_records_response_fields() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import run_window
    from framework.domains.schema import load_pack
    from framework.proposal.core import WonderResponse

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    response = WonderResponse(
        text=_mini_week_proposal("2030-01-07", 2, "review-capacity"),
        model_reported="fake-model",
        latency_ms=1200,
        finish_reason="stop",
        prompt_tokens=11,
        completion_tokens=22,
        reasoning_tokens=33,
    )
    run = run_window(pack, ref, _FakeClient([response]), model="fake", effort="low")
    attempt = run.attempts[0].to_json()
    assert attempt["finish_reason"] == "stop"
    assert attempt["prompt_tokens"] == 11
    assert attempt["completion_tokens"] == 22
    assert attempt["reasoning_tokens"] == 33
    data = json.loads(json.dumps(run.to_json()))
    assert set(data) == {
        "pack_id",
        "window_start",
        "model",
        "effort",
        "expected_commitment",
        "attempts",
        "first_pass_accepted",
        "repaired",
        "final_passed",
        "transport_error",
        "latency_ms_total",
    }


def test_f4_no_pack_specific_words_in_runner() -> None:
    import ast as _ast

    runner = ROOT / "framework" / "domains" / "runner.py"
    tree = _ast.parse(runner.read_text(encoding="utf-8"))
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            for word in ("busy", "rental", "bike", "threshold_number"):
                assert word not in lowered, (word, node.value)


def test_f4_commitment_decision_window_and_metric_lines() -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import build_prompt
    from framework.domains.schema import load_pack

    pack = load_pack(MINI / "pack.json")
    ref = build_reference(pack, MINI, "2030-01-07")
    prompt = build_prompt(pack, ref)
    assert pack.goal.text in prompt
    assert (
        "- review-capacity: Review bike capacity for the coming week. "
        "Choose it when busy_days is at least 1." in prompt.splitlines()
    )
    assert (
        "- continue-monitoring: Keep monitoring; no capacity change this week. "
        "Choose it when busy_days is exactly 0." in prompt.splitlines()
    )
    assert " on busy_days" not in prompt
    assert "Decision: choose exactly one commitment." in prompt.splitlines()
    assert (
        "Window: week of 2030-01-07, the 7 dates from 2030-01-07 to 2030-01-13."
        in prompt.splitlines()
    )
    assert "Metrics, computed from the pinned source files:" in prompt.splitlines()
    assert "every value below is already checked" not in prompt
    assert "sum of total_rentals over the window's dates" in prompt
    assert "number of dates whose total_rentals is above 100" in prompt
    for metric_id, value in ref.metrics.items():
        assert metric_id in prompt
        assert str(value) in prompt
    for fact_id in pack.facts:
        assert fact_id in prompt


def test_f4_max_metric_definition_in_words(tmp_path: Path) -> None:
    from framework.domains.csv_adapter import build_reference
    from framework.domains.runner import build_prompt
    from framework.domains.schema import load_pack

    pack_dir = _copy_mini(tmp_path)
    data = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    data["window_metrics"].append(
        {
            "id": "peak_rentals",
            "op": "max",
            "of": "total_rentals",
            "labels": ["total", "rentals"],
            "unit": "count",
        }
    )
    (pack_dir / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    pack = load_pack(pack_dir / "pack.json")
    ref = build_reference(pack, pack_dir, "2030-01-07")
    prompt = build_prompt(pack, ref)
    assert "largest daily total_rentals" in prompt


def test_f5_freeze_has_no_duplicate_claims(tmp_path: Path) -> None:
    from collections import Counter as _Counter

    from evals.domains import main

    out = tmp_path / "bikes_fresh.json"
    code = main(
        [
            "freeze",
            "--pack",
            str(ROOT / "examples" / "domains" / "bikes" / "pack.json"),
            "--expected",
            str(ROOT / "examples" / "domains" / "bikes" / "expected.json"),
            "--seed",
            "20261104",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert len(cases) == 80
    keys = set()
    for case in cases:
        claim = case["claim"]
        keys.add(
            (
                claim["text"],
                tuple(
                    (item["metric_id"], item["value"]) for item in claim["metric_refs"]
                ),
                tuple(claim.get("fact_ids", [])),
            )
        )
    assert len(keys) == 80
    planted = [case for case in cases if case["expect"] == "fail"]
    assert _Counter(case["kind"] for case in planted) == {
        "wrong_value": 10,
        "wrong_label": 10,
        "wrong_period": 10,
        "wrong_unit": 10,
        "wrong_source": 10,
        "wrong_direction": 10,
    }
    controls = [case for case in cases if case["expect"] == "pass"]
    assert len(controls) == 20
    digest = hashlib.sha256(
        json.dumps(controls, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert digest == "34999ace854f3ae77d12ab18c9c34ceab595725615e73a3ca89faaa49d5f53c6"


def test_f6_score_codes_by_kind(tmp_path: Path) -> None:
    from evals.domains import main

    cases_path = _freeze_mini(tmp_path)
    out = tmp_path / "mini_score.json"
    assert (
        main(
            [
                "score",
                "--pack",
                str(MINI / "pack.json"),
                "--cases",
                str(cases_path),
                "--out",
                str(out),
            ]
        )
        == 0
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    codes_by_kind = payload["summary"]["codes_by_kind"]
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    kinds = {case["kind"] for case in cases}
    assert set(codes_by_kind) == kinds
    for kind, counts in codes_by_kind.items():
        total = sum(1 for case in cases if case["kind"] == kind)
        assert isinstance(counts, dict)
        for code, count in counts.items():
            assert isinstance(code, str)
            assert isinstance(count, int)
            assert 1 <= count <= total
    assert codes_by_kind["wrong_value"] == {"L1B_METRIC_VALUE_MISMATCH": 2}
    assert codes_by_kind["daily_total"] == {}
    assert codes_by_kind["daily_casual"] == {}


def test_f8_show_prints_identity_lines(capsys: Any) -> None:
    from framework.domains.__main__ import main as domains_main

    code = domains_main(
        ["show", "--pack", str(MINI / "pack.json"), "--window", "2030-01-07"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "identity columns_sum: held on 7 of 7 dates" in out
    assert "identity daily_matches: held on 7 of 7 dates" in out
    assert "identities: 2 of 2 hold" in out
    assert out.index("identity columns_sum") < out.index("identities: 2 of 2 hold")
