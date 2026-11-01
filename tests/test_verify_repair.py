"""Ticket 17a: the single generic repair loop and its verify wrapper."""

from __future__ import annotations

import re
from pathlib import Path

from framework.verify import verify_claims
from framework.verify.repair import (
    Attempt,
    FailedValidation,
    RepairResult,
    repair_loop,
    verify_and_repair,
)


class _Stub:
    def __init__(self, passed: bool, text: str = "") -> None:
        self.passed = passed
        self._text = text

    def feedback(self) -> str:
        return self._text


def _good_input(draft: dict[str, object]) -> dict[str, object]:
    return draft


def test_repair_loop_passes_first_try() -> None:
    seen: list[object] = []

    def generate(feedback: str | None) -> dict[str, object]:
        seen.append(feedback)
        return {
            "claims": [
                {"id": "c1", "text": "The queue looks steady", "fact_ids": ["t1"]}
            ],
            "facts": {"t1": "Note filed"},
            "metrics": {},
        }

    result = verify_and_repair(generate, _good_input)
    assert isinstance(result, RepairResult)
    assert result.report.passed is True
    assert len(result.attempts) == 1
    assert isinstance(result.attempts[0], Attempt)
    assert seen == [None]


def test_repair_loop_retries_with_feedback_then_passes() -> None:
    feedbacks: list[str | None] = []
    drafts = [
        {
            "claims": [{"id": "c1", "text": "Scored 42 points in the trial"}],
            "facts": {},
            "metrics": {},
        },
        {
            "claims": [
                {"id": "c1", "text": "The queue looks steady", "fact_ids": ["t1"]}
            ],
            "facts": {"t1": "Note filed"},
            "metrics": {},
        },
    ]

    def generate(feedback: str | None) -> dict[str, object]:
        feedbacks.append(feedback)
        return drafts[len(feedbacks) - 1]

    result = verify_and_repair(generate, _good_input, max_retries=1)
    assert result.report.passed is True
    assert len(result.attempts) == 2
    assert feedbacks[0] is None
    assert "L1B_CLAIM_WITHOUT_EVIDENCE" in (feedbacks[1] or "")
    assert "L1B_NUMBER_WITHOUT_METRIC_REF" in (feedbacks[1] or "")
    assert result.draft == drafts[1]
    assert result.report is result.attempts[-1].report


def test_repair_loop_stops_after_max_retries() -> None:
    calls = 0

    def generate(feedback: str | None) -> str:
        nonlocal calls
        calls += 1
        return "never parseable"

    def validate(draft: object) -> _Stub:
        raise ValueError("boom")

    result = repair_loop(generate, validate, max_retries=2)
    assert calls == 3
    assert len(result.attempts) == 3
    assert result.report.passed is False


def test_parse_failure_is_a_failed_attempt_with_fixed_feedback() -> None:
    def generate(feedback: str | None) -> str:
        return "bad draft"

    def validate(draft: object) -> _Stub:
        raise RuntimeError("private detail that must not leak")

    result = repair_loop(generate, validate, max_retries=0)
    assert len(result.attempts) == 1
    report = result.attempts[0].report
    assert isinstance(report, FailedValidation)
    assert report.passed is False
    assert report.feedback() == "draft could not be parsed"
    assert "private detail" not in report.feedback()
    assert result.draft == "bad draft"


def test_generate_exceptions_propagate() -> None:
    def generate(feedback: str | None) -> object:
        raise KeyError("generator owns this failure")

    try:
        repair_loop(generate, lambda draft: _Stub(True))
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected KeyError")


def test_verify_and_repair_threads_build_input() -> None:
    seen_inputs: list[dict[str, object]] = []

    def build_input(draft: int) -> dict[str, object]:
        payload = {
            "claims": [
                {
                    "id": "c1",
                    "text": f"Deploys reached {draft} in November",
                    "metric_refs": [{"metric_id": "deploys.nov", "value": draft}],
                }
            ],
            "facts": {},
            "metrics": {"deploys.nov": 12},
            "labels": {"deploys.nov": ["deploys", "november"]},
        }
        seen_inputs.append(payload)
        return payload

    drafts = iter([9, 12])

    def generate(feedback: str | None) -> int:
        return next(drafts)

    result = verify_and_repair(generate, build_input, max_retries=1)
    assert result.report.passed is True
    assert result.draft == 12
    assert verify_claims(seen_inputs[-1]).passed is True


def test_single_repair_loop_in_repo() -> None:
    root = Path(__file__).resolve().parents[1] / "framework"
    hits = [
        str(p)
        for p in sorted(root.rglob("*.py"))
        if re.search(r"^def repair_loop\b", p.read_text(), re.MULTILINE)
    ]
    assert hits == [str(root / "verify" / "repair.py")]


def test_repair_has_no_briefing_or_meta_import() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "framework" / "verify" / "repair.py"
    ).read_text()
    assert "framework.briefing" not in text
    assert "framework/briefing" not in text
    assert "Meta" not in text
    assert "inspect_ai" not in text
    assert "LOCAL_LLM" not in text


def test_verify_and_repair_without_max_retries_makes_at_most_two_attempts() -> None:
    calls = 0

    def generate(feedback: str | None) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "claims": [{"id": "c1", "text": "Scored 42 points in the trial"}],
            "facts": {},
            "metrics": {},
        }

    result = verify_and_repair(generate, _good_input)
    assert calls == 2
    assert len(result.attempts) == 2
    assert result.report.passed is False
