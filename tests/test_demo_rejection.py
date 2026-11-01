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


def test_demo_output_replays_rejection_then_pass(
    capsys: pytest.CaptureFixture[str],
) -> None:
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


def test_demo_script_runs_offline_with_exit_zero() -> None:
    proc = subprocess.run(
        [sys.executable, "evals/demo_rejection.py"],
        check=False,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0
    assert "L1B_METRIC_VALUE_MISMATCH" in proc.stdout


def test_demo_fails_when_gate_passes_everything(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        demo,
        "evaluate_briefing",
        lambda briefing, context: types.SimpleNamespace(violations=(), passed=True),
    )
    assert main() == 1


def test_demo_fails_when_gate_rejects_everything(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
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
