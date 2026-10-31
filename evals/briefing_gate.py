"""Ticket 8: briefing-gate Inspect tasks (meta-eval harness, not a model eval).

This module wears Inspect's log format so gate runs are comparable with
``evals/hello.py`` logs, but determinism comes from the gate, not the model:
the scorer ignores the mock completion beyond requiring the run completed,
reconstructs the ``GateContext`` from sample metadata, and calls
``evaluate_briefing``. The binding CI claim stays on the pytest meta-eval
(``tests/test_briefing_mutants.py``), not on this mock run.

Layer tasks include every case; a case whose defect lives in another layer
is expected to pass that layer's task (target ``PASS``), which tests layer
isolation as well as detection.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState, generate

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.context import GateContext
from framework.briefing.gate import evaluate_briefing

PASS = "PASS"
ALL_LAYERS = ("L0", "L1", "L1b")
INPUT = "Gate the attached briefing with the deterministic briefing gate."


def layer_of(code: str) -> str:
    """Map a stable violation code to its layer."""
    if code.startswith("L1B"):
        return "L1b"
    if code.startswith("L1"):
        return "L1"
    return "L0"


def target_text(codes: tuple[str, ...], layers: tuple[str, ...]) -> str:
    """Comma-joined expected codes filtered to ``layers`` (``PASS`` if none)."""
    filtered = [code for code in codes if layer_of(code) in layers]
    return PASS if not filtered else ",".join(filtered)


def score_briefing(
    briefing: dict[str, Any],
    context_json: dict[str, Any],
    layers: tuple[str, ...],
    target: str,
) -> Score:
    """Pure scorer logic: gate the briefing, compare filtered codes to target."""
    context = GateContext.model_validate(context_json)
    result = evaluate_briefing(briefing, context)
    actual = [v.code for v in result.violations if layer_of(v.code) in layers]
    answer = PASS if not actual else ",".join(actual)
    expected = [] if target == PASS else target.split(",")
    ok = actual == expected
    explanation = (
        "no violations"
        if not result.violations
        else "; ".join(f"{v.code} @ {v.location}" for v in result.violations)
    )
    return Score(
        value=CORRECT if ok else INCORRECT,
        answer=answer,
        explanation=explanation,
    )


@scorer(metrics=[])
def gate_scorer(layers: list[str]) -> Scorer:
    """Deterministic scorer factory: filter the gate's codes to ``layers``."""

    async def score(state: TaskState, target: Target) -> Score:
        metadata = state.metadata
        return score_briefing(
            metadata["briefing"],
            metadata["context"],
            tuple(layers),
            target.text,
        )

    return score


def _samples(cases: tuple[Case, ...], layers: tuple[str, ...]) -> list[Sample]:
    return [
        Sample(
            id=case.name,
            input=INPUT,
            target=target_text(case.expected, layers),
            metadata={
                "briefing": case.briefing,
                "context": case.context.model_dump(mode="json"),
                "layers": list(layers),
            },
        )
        for case in cases
    ]


def _all_cases() -> tuple[Case, ...]:
    return (*MUTANTS, *KNOWN_GOOD)


@task
def briefing_l0() -> Task:
    """L0 structure task over every briefing-gate case."""
    return Task(
        dataset=_samples(_all_cases(), ("L0",)),
        solver=[generate()],
        scorer=gate_scorer(["L0"]),
    )


@task
def briefing_l1() -> Task:
    """L1 rules task over every briefing-gate case."""
    return Task(
        dataset=_samples(_all_cases(), ("L1",)),
        solver=[generate()],
        scorer=gate_scorer(["L1"]),
    )


@task
def briefing_l1b() -> Task:
    """L1b reconciliation task over every briefing-gate case."""
    return Task(
        dataset=_samples(_all_cases(), ("L1b",)),
        solver=[generate()],
        scorer=gate_scorer(["L1b"]),
    )


@task
def briefing_gate() -> Task:
    """All-layers gate task over every briefing-gate case."""
    return Task(
        dataset=_samples(_all_cases(), ALL_LAYERS),
        solver=[generate()],
        scorer=gate_scorer(["L0", "L1", "L1b"]),
    )
