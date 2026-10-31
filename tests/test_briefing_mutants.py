"""Ticket 8: meta-eval over ``evals/briefing_cases`` (16 mutants, 12 known-good)."""

import pytest

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.gate import evaluate_briefing


def test_case_counts() -> None:
    assert len(MUTANTS) == 20
    assert len(KNOWN_GOOD) == 12


@pytest.mark.parametrize("case", MUTANTS, ids=[c.name for c in MUTANTS])
def test_mutant_fails_with_exactly_its_expected_code(case: Case) -> None:
    result = evaluate_briefing(case.briefing, case.context)
    assert result.passed is False
    assert [v.code for v in result.violations] == list(case.expected)


@pytest.mark.parametrize("case", KNOWN_GOOD, ids=[c.name for c in KNOWN_GOOD])
def test_known_good_passes_with_no_violations(case: Case) -> None:
    result = evaluate_briefing(case.briefing, case.context)
    assert result.violations == ()
    assert result.passed is True
