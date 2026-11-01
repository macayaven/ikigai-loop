"""Ticket 11: proposal-gate Inspect task (meta-eval harness, not a model eval).

The scorer ignores the mock completion beyond requiring the run completed,
replays each case's scripted outcomes through ``propose`` with the scripted
client, and compares kind, attempts, and first-attempt codes to the target.
The binding CI claim stays on the pytest meta-eval
(``tests/test_proposal_core.py``), not on this mock run. Offline, no
network, no real model.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState, generate

from evals.proposal_cases import (
    CASES,
    Case,
    first_codes,
    result_commitment,
    run_case,
    run_hour_case,
    run_refusal_case,
)

INPUT = "Propose one commitment per goal for the next free hour."


def target_text(case: Case) -> str:
    """One-line expected summary for one case."""
    if case.expected_kind == "raise":
        return "refused"
    if case.expected_kind == "hour":
        assert case.expected_hour is not None
        return f"{case.expected_hour[0]} {case.expected_hour[1]}"
    codes = ",".join(case.expected_codes) or "-"
    commitment = case.expected_commitment or "-"
    return (
        f"kind={case.expected_kind} attempts={case.expected_attempts} "
        f"codes={codes} commitment={commitment}"
    )


def score_case(metadata: dict[str, Any]) -> Score:
    """Pure scorer logic: replay the case, compare outcome to the target."""
    from evals.proposal_cases import Case as _Case

    case = _Case.from_dict(metadata["case"])
    if case.expected_kind == "raise":
        exc = run_refusal_case(case)
        ok = exc is not None
        return Score(
            value=CORRECT if ok else INCORRECT,
            answer="refused" if ok else "not refused",
        )
    if case.expected_kind == "hour":
        hour = run_hour_case(case)
        expected = metadata["case"].get("expected_hour")
        if hour is None or expected is None:
            ok = hour is None and expected is None
            answer = "none" if hour is None else "hour"
        else:
            ok = (
                hour.start.isoformat() == expected[0]
                and hour.end.isoformat() == expected[1]
            )
            answer = f"{hour.start.isoformat()} {hour.end.isoformat()}"
        return Score(value=CORRECT if ok else INCORRECT, answer=answer)
    result = run_case(case)
    codes = ",".join(first_codes(result)) or "-"
    commitment = result_commitment(result) or "-"
    answer = (
        f"kind={result.kind} attempts={len(result.attempts)} "
        f"codes={codes} commitment={commitment}"
    )
    ok = (
        result.kind == case.expected_kind
        and len(result.attempts) == case.expected_attempts
        and first_codes(result) == case.expected_codes
        and result_commitment(result) == case.expected_commitment
    )
    return Score(value=CORRECT if ok else INCORRECT, answer=answer)


@scorer(metrics=[])
def replay_scorer() -> Scorer:
    """Deterministic scorer: the mock completion is ignored beyond the run."""

    async def score(state: TaskState, target: Target) -> Score:
        scored = score_case(state.metadata)
        expected = target.text
        ok = (scored.value == CORRECT) and (scored.answer == expected)
        return Score(value=CORRECT if ok else INCORRECT, answer=scored.answer)

    return score


def _samples(cases: tuple[Case, ...]) -> list[Sample]:
    return [
        Sample(
            id=case.name,
            input=INPUT,
            target=target_text(case),
            metadata={"case": case.to_dict()},
        )
        for case in cases
    ]


@task
def proposal_gate() -> Task:
    """Proposal replay task over every proposal case."""
    return Task(
        dataset=_samples(CASES),
        solver=[generate()],
        scorer=replay_scorer(),
    )
