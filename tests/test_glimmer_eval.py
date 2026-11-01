"""Ticket 9: Inspect task construction; the replay scorer agrees with the core."""

from typing import Any

from inspect_ai.scorer import CORRECT, INCORRECT

from evals import glimmer_facts
from evals.glimmer_cases import (
    AS_OF,
    KNOWN_GOOD,
    MUTANTS,
    SUBJECT_ID,
    RecordingLLM,
    base_case,
)
from evals.glimmer_facts import score_case
from framework.glimmer.facts import extract_facts


def test_task_holds_all_30_cases() -> None:
    task = glimmer_facts.glimmer_facts()
    assert len(task.dataset) == len(KNOWN_GOOD) + len(MUTANTS) == 30
    ids = [sample.id for sample in task.dataset]
    assert ids == [c.name for c in (*KNOWN_GOOD, *MUTANTS)]


def test_scorer_agrees_with_extract_facts() -> None:
    task = glimmer_facts.glimmer_facts()
    by_id = {s.id: s for s in task.dataset}
    sample = by_id["G1-base"]
    assert sample.metadata is not None
    scored = score_case(sample.metadata)
    assert sample.target == scored.answer
    assert scored.value == CORRECT


def test_scorer_rejects_tampered_expectation() -> None:
    task = glimmer_facts.glimmer_facts()
    by_id = {s.id: s for s in task.dataset}
    raw = by_id["F3-unbacked-number"].metadata
    assert raw is not None
    metadata: dict[str, Any] = dict(raw)
    metadata["expected_kept"] = 1
    assert score_case(metadata).value == INCORRECT


def test_scorer_matches_direct_replay() -> None:
    case = base_case()
    llm = RecordingLLM(personal=case.personal_texts, feed=case.feed_texts)
    direct = extract_facts(AS_OF, SUBJECT_ID, list(case.events), llm)
    task = glimmer_facts.glimmer_facts()
    sample = next(s for s in task.dataset if s.id == "G1-base")
    assert sample.metadata is not None
    scored = score_case(sample.metadata)
    assert scored.value == CORRECT
    assert scored.answer is not None
    assert f"kept={len(direct.facts)}" in scored.answer
