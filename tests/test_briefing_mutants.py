"""Ticket 10b: meta-eval over ``evals/briefing_cases`` (118 mutants, 57 known-good)."""

import pytest

from evals.briefing_cases import KNOWN_GOOD, MUTANTS, Case
from framework.briefing.gate import evaluate_briefing


def test_case_counts() -> None:
    # 38 base mutants + 34 round-1 redteam (M39-M72) + 46 round-2 (M73-M118).
    assert len(MUTANTS) == 38 + 34 + 46 == 118
    # 20 base known-good + 28 round-1 redteam (G21-G48) + 9 round-2 (G49-G57).
    assert len(KNOWN_GOOD) == 20 + 28 + 9 == 57


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
