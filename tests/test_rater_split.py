"""Slice A, AT-A1: the atomic split is fixed rules, never fitted to ratings."""

from framework.briefing.schemas import MetricRef
from framework.rater.split import split_atomic


def _ref(metric_id: str = "period.last.pushes", value: float = 2.0) -> MetricRef:
    return MetricRef(metric_id=metric_id, value=value)


def test_decimal_point_is_not_a_boundary() -> None:
    outcome = split_atomic("Screen time was 3.95 hours in the last period.")
    assert [atom.text for atom in outcome.atomics] == [
        "Screen time was 3.95 hours in the last period."
    ]


def test_two_sentence_statement_splits_in_two() -> None:
    outcome = split_atomic(
        "Pushes were 2 in the prior period. Pushes rose to 3 in the last period."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 2 in the prior period.",
        "Pushes rose to 3 in the last period.",
    ]


def test_semicolon_splits() -> None:
    outcome = split_atomic(
        "Pushes were 2 in the prior period; pushes were 3 in the last period."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 2 in the prior period.",
        "pushes were 3 in the last period.",
    ]


def test_so_clause_without_digit_is_cut() -> None:
    outcome = split_atomic(
        "Chat was 3.95 hours in the last period, so this hour goes to rest."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Chat was 3.95 hours in the last period."
    ]
    assert outcome.so_clauses_cut == 1
    assert outcome.so_clauses_kept_with_digit == 0


def test_so_clause_with_digit_stays_whole() -> None:
    outcome = split_atomic(
        "Chat was 3 hours in the last period, so this hour goes to 2 blocks."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Chat was 3 hours in the last period, so this hour goes to 2 blocks."
    ]
    assert outcome.so_clauses_cut == 0
    assert outcome.so_clauses_kept_with_digit == 1


def test_three_period_series_stays_one_and_is_not_compound() -> None:
    outcome = split_atomic("Pushes were 2 in earlier, 2 in prior and 2 in last.")
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 2 in earlier, 2 in prior and 2 in last."
    ]
    assert outcome.possibly_compound == 0


def test_and_with_two_numbers_stays_whole_and_counts() -> None:
    outcome = split_atomic("Pushes were 5 and pulls were 6 in the last window.")
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 5 and pulls were 6 in the last window."
    ]
    assert outcome.possibly_compound == 1


def test_and_with_one_number_stays_whole_and_counts() -> None:
    outcome = split_atomic("Pushes were 5 and steady in the last window.")
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 5 and steady in the last window."
    ]
    assert outcome.possibly_compound == 1


def test_and_with_no_number_fact_only_stays_whole_and_counts() -> None:
    outcome = split_atomic("Paper lists hold tasks and picnic lists hold dates.")
    assert [atom.text for atom in outcome.atomics] == [
        "Paper lists hold tasks and picnic lists hold dates."
    ]
    assert outcome.possibly_compound == 1


def test_so_cut_head_with_and_counts_compound() -> None:
    outcome = split_atomic(
        "Pushes were 2 and steady in the last window, so this hour goes to rest."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 2 and steady in the last window."
    ]
    assert outcome.so_clauses_cut == 1
    assert outcome.possibly_compound == 1


def test_so_cut_head_with_series_stays_not_compound() -> None:
    outcome = split_atomic(
        "Pushes were 2 in earlier, 2 in prior and 2 in last, so this hour goes to rest."
    )
    assert [atom.text for atom in outcome.atomics] == [
        "Pushes were 2 in earlier, 2 in prior and 2 in last."
    ]
    assert outcome.so_clauses_cut == 1
    assert outcome.possibly_compound == 0


def test_every_atomic_keeps_its_statement_evidence() -> None:
    refs = (_ref(),)
    outcome = split_atomic(
        "Pushes were 2 in the prior period. Pushes rose to 3 in the last period.",
        fact_ids=["f1"],
        metric_refs=refs,
        section_type="working",
    )
    assert len(outcome.atomics) == 2
    for index, atom in enumerate(outcome.atomics):
        assert atom.fact_ids == ("f1",)
        assert atom.metric_refs == refs
        assert atom.section_type == "working"
        assert atom.atomic_index == index
