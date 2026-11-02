"""Offline demo replay: M12 rejection through the deterministic gate."""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest

import evals.demo_rejection as demo
from evals.briefing_cases import MUTANTS
from evals.demo_rejection import main

REPO_ROOT = Path(__file__).resolve().parents[1]


def _m12() -> tuple[str, str, float, float]:
    case = next(c for c in MUTANTS if c.name == "M12-metric-mismatch")
    working = next(s for s in case.briefing["sections"] if s["type"] == "working")
    claim = next(c for c in working["claims"] if c["id"] == "claim-w1")
    ref = claim["metric_refs"][0]
    source = case.context.metrics.values[ref["metric_id"]]
    return claim["text"], ref["metric_id"], float(ref["value"]), source


def _fmt(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _without_kept_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IKIGAI_R1B_DEMO_FILE", str(tmp_path / "missing-rejection.json"))


def test_demo_output_replays_rejection_then_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _without_kept_file(monkeypatch, tmp_path)
    sentence, metric_id, draft_value, source = _m12()
    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("Synthetic")
    assert sentence in lines[1] and lines[1].startswith("DRAFT: ")
    draft_line = f"DRAFT: {sentence}"
    case = next(c for c in MUTANTS if c.name == "M12-metric-mismatch")
    rejected_line = f"REJECTED {case.expected[0]} at sections[working].claims[claim-w1]"
    source_line = f"SOURCE: {metric_id} is {_fmt(source)}"
    fixed_line = f"FIXED: {sentence.replace(_fmt(draft_value), _fmt(source), 1)}"
    assert draft_line in lines
    assert rejected_line in lines
    assert source_line in lines
    assert fixed_line in lines
    assert lines[-1] == "PASSED"
    assert (
        lines.index(lines[0])
        < lines.index(draft_line)
        < lines.index(rejected_line)
        < lines.index(source_line)
        < lines.index(fixed_line)
        < lines.index("PASSED")
    )
    assert _fmt(source) in lines[lines.index(fixed_line)]
    assert _fmt(draft_value) not in lines[lines.index(fixed_line)]


def test_demo_script_runs_offline_with_exit_zero(tmp_path: Path) -> None:
    import os as _os

    env = dict(_os.environ)
    env["IKIGAI_R1B_DEMO_FILE"] = str(tmp_path / "missing-rejection.json")
    proc = subprocess.run(
        [sys.executable, "evals/demo_rejection.py"],
        check=False,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert proc.returncode == 0
    assert "L1B_METRIC_VALUE_MISMATCH" in proc.stdout


def test_demo_fails_when_gate_passes_everything(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _without_kept_file(monkeypatch, tmp_path)
    monkeypatch.setattr(
        demo,
        "evaluate_briefing",
        lambda briefing, context: types.SimpleNamespace(violations=(), passed=True),
    )
    assert main() == 1


def _kept_draft(
    tmp_path: Path,
    *,
    arm: str = "product",
    retry_passed: bool = True,
    location: str = "sections[overall_state].claims[c-overall_state-1]",
) -> Path:
    import json as _json

    draft = {
        "commitment_id": "cm-f01-build",
        "overall_state": [
            {
                "text": "Busy was 2.6 hours across the window",
                "fact_ids": [],
                "metric_refs": ["calendar.busy_hours"],
            }
        ],
        "working": [],
        "not_working": [],
    }
    retry = {
        "commitment_id": "cm-f01-build",
        "overall_state": [
            {
                "text": "Busy was 2.5 hours across the window",
                "fact_ids": [],
                "metric_refs": ["calendar.busy_hours"],
            }
        ],
        "working": [],
        "not_working": [],
    }
    kept = {
        "synthetic": True,
        "label": "synthetic data only",
        "model": "muse-wonder-1.0",
        "effort": "high",
        "arm": arm,
        "case_id": "r1b-f01",
        "trap": None,
        "gate_commit": "0" * 40,
        "gate_hash": "c" * 64,
        "draft_text": _json.dumps(draft),
        "codes": [
            [
                "L1B_NUMBER_WITHOUT_METRIC_REF",
                location,
            ]
        ],
        "retry_text": _json.dumps(retry) if retry_passed else None,
        "retry_passed": retry_passed,
    }
    path = tmp_path / "demo_real_rejection.json"
    path.write_text(_json.dumps(kept, indent=2) + "\n", encoding="utf-8")
    return path


def test_demo_prefers_kept_draft_verbatim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import json as _json

    monkeypatch.setenv("IKIGAI_R1B_DEMO_FILE", str(_kept_draft(tmp_path)))
    assert main() == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[0].startswith("Synthetic")
    assert "muse-wonder-1.0" in lines[1] and "product" in lines[1]
    assert "high" in lines[1]
    kept = _json.loads((tmp_path / "demo_real_rejection.json").read_text())
    assert f"DRAFT: {kept['draft_text']}" in lines
    assert "SENTENCE: Busy was 2.6 hours across the window" in lines
    assert (
        "REJECTED L1B_NUMBER_WITHOUT_METRIC_REF "
        "at sections[overall_state].claims[c-overall_state-1]" in lines
    )
    assert f"RETRY: {kept['retry_text']}" in lines
    assert lines[-1] == "PASSED"


def test_demo_labels_plain_arm_pick(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("IKIGAI_R1B_DEMO_FILE", str(_kept_draft(tmp_path, arm="plain")))
    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert "plain" in lines[1]


def test_demo_without_passing_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "IKIGAI_R1B_DEMO_FILE", str(_kept_draft(tmp_path, retry_passed=False))
    )
    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "NO PASSING RETRY"


def test_demo_prints_no_sentence_when_location_does_not_resolve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "IKIGAI_R1B_DEMO_FILE",
        str(
            _kept_draft(
                tmp_path,
                location="sections[overall_state].claims[c-overall_state-9]",
            )
        ),
    )
    assert main() == 0
    lines = capsys.readouterr().out.splitlines()
    assert not [line for line in lines if line.startswith("SENTENCE: ")]
    assert (
        "REJECTED L1B_NUMBER_WITHOUT_METRIC_REF "
        "at sections[overall_state].claims[c-overall_state-9]" in lines
    )


def test_demo_fails_when_gate_rejects_everything(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _without_kept_file(monkeypatch, tmp_path)
    case = next(c for c in MUTANTS if c.name == "M12-metric-mismatch")
    monkeypatch.setattr(
        demo,
        "evaluate_briefing",
        lambda briefing, context: types.SimpleNamespace(
            violations=(
                types.SimpleNamespace(
                    code=case.expected[0],
                    location="sections[working].claims[claim-w1]",
                ),
            ),
            passed=False,
        ),
    )
    assert main() == 1
    capsys.readouterr()
