"""Ticket 9: Glimmer fact-layer Inspect task (meta-eval harness, not a model eval).

This module wears Inspect's log format so runs are comparable with
``evals/hello.py`` logs, but determinism comes from ``extract_facts``, not
the model: the scorer ignores the mock completion beyond requiring the run
completed, replays the recorded per-pass texts through ``extract_facts``,
and compares kept/noop/dropped/snapshot to the target. The binding CI
claim stays on the pytest meta-eval (``tests/test_glimmer_mutants.py``),
not on this mock run. Offline, no network, no real model.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

_REPOS_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOS_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOS_ROOT))

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, scorer
from inspect_ai.solver import TaskState, generate

from evals.glimmer_cases import (
    AS_OF,
    KNOWN_GOOD,
    MUTANTS,
    SUBJECT_ID,
    WINDOW_START,
    Case,
    RecordingLLM,
    ScriptEntry,
)
from framework.glimmer.facts import extract_facts
from framework.schemas.events import Event
from framework.store import EventStore

PASS = "PASS"
INPUT = "Extract objective facts from the attached personal event data."


def _case_to_metadata(case: Case) -> dict[str, Any]:
    return {
        "name": case.name,
        "as_of": AS_OF.isoformat(),
        "subject_id": SUBJECT_ID,
        "events": [e.model_dump(mode="json") for e in case.events],
        "personal_texts": [s.to_dict() for s in case.personal_texts],
        "feed_texts": [s.to_dict() for s in case.feed_texts],
        "via_store": case.via_store,
        "expected_kept": case.expected_kept,
        "expected_noop": case.expected_noop,
        "expected_dropped": list(case.expected_dropped),
        "expected_statements": list(case.expected_statements),
        "expected_snapshot": dict(case.expected_snapshot),
    }


def _events_from_metadata(metadata: dict[str, Any]) -> list[Event]:
    events = [Event.model_validate(raw) for raw in metadata["events"]]
    if not metadata.get("via_store"):
        return events
    with tempfile.TemporaryDirectory() as tmp:
        store = EventStore(db_path=Path(tmp) / "eval.db")
        try:
            store.append_events(events)
            return store.events_between(
                metadata["subject_id"],
                WINDOW_START,
                AS_OF,
            )
        finally:
            store.close()


def target_text(case: Case) -> str:
    """One-line expected summary (``PASS`` never applies: facts vary)."""
    noop = case.expected_noop or "-"
    dropped = ",".join(case.expected_dropped) or "-"
    return f"kept={case.expected_kept} noop={noop} dropped={dropped}"


def score_case(metadata: dict[str, Any]) -> Score:
    """Pure scorer logic: replay the recorded texts, compare to the target."""
    from datetime import datetime

    as_of = datetime.fromisoformat(metadata["as_of"])
    events = _events_from_metadata(metadata)
    llm = RecordingLLM(
        personal=tuple(
            ScriptEntry.from_dict(raw) for raw in metadata["personal_texts"]
        ),
        feed=tuple(ScriptEntry.from_dict(raw) for raw in metadata["feed_texts"]),
    )
    result = extract_facts(as_of, metadata["subject_id"], events, llm)
    noop = result.noop_reason or "-"
    dropped = ",".join(d.code for d in result.dropped) or "-"
    answer = f"kept={len(result.facts)} noop={noop} dropped={dropped}"
    statements = [f.statement for f in result.facts]
    ok = (
        len(result.facts) == metadata["expected_kept"]
        and (result.noop_reason or "-") == (metadata["expected_noop"] or "-")
        and [d.code for d in result.dropped] == metadata["expected_dropped"]
        and statements == metadata["expected_statements"]
        and result.snapshot.values == metadata["expected_snapshot"]
    )
    return Score(
        value=CORRECT if ok else INCORRECT,
        answer=answer,
        explanation=("; ".join(statements) if statements else "no facts"),
    )


@scorer(metrics=[])
def replay_scorer() -> Scorer:
    """Deterministic scorer: the mock completion is ignored beyond the run."""

    async def score(state: TaskState, target: Target) -> Score:
        scored = score_case(state.metadata)
        expected = [] if target.text == PASS else [target.text]
        ok = (scored.value == CORRECT) and (
            not expected or scored.answer == target.text
        )
        return Score(value=CORRECT if ok else INCORRECT, answer=scored.answer)

    return score


def _samples(cases: tuple[Case, ...]) -> list[Sample]:
    return [
        Sample(
            id=case.name,
            input=INPUT,
            target=target_text(case),
            metadata=_case_to_metadata(case),
        )
        for case in cases
    ]


@task
def glimmer_facts() -> Task:
    """Fact-layer replay task over every Glimmer case."""
    return Task(
        dataset=_samples((*KNOWN_GOOD, *MUTANTS)),
        solver=[generate()],
        scorer=replay_scorer(),
    )
