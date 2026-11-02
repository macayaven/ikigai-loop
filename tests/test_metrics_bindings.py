"""Slice B, AT-B7: PREREG bindings (BD8).

Deviation 5 (counts, never a ratio), the forecast drift check, and the
five clock-rule citations resolved to real test names. Deviations 4, 8
and 9 point at the Slice A/B tests that prove them, by name.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from framework.learner.simulate import recover_table
from framework.metrics.report import FORECAST, forecast_from_prereg

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_forecast_matches_prereg_table() -> None:
    text = (REPO_ROOT / "docs" / "PREREG.md").read_text(encoding="utf-8")
    assert forecast_from_prereg(text) == FORECAST
    assert FORECAST == {"15:30": (8, 10), "20:30": (5, 10), "22:30": (0, 10)}


def test_forecast_drift_is_caught_on_a_mutated_copy() -> None:
    text = (REPO_ROOT / "docs" / "PREREG.md").read_text(encoding="utf-8")
    mutated = text.replace(
        "| 15:30 | 8 of 10 | 2 of 10 |", "| 15:30 | 9 of 10 | 1 of 10 |"
    )
    assert mutated != text
    assert forecast_from_prereg(mutated) != FORECAST


def test_recover_table_defaults_untouched() -> None:
    params = inspect.signature(recover_table).parameters
    assert params["true_ps"].default == (0.5, 0.6, 0.7, 0.8, 0.9)
    assert params["n_cards"].default == (5, 13, 30, 100)


def test_clock_citations_resolve_to_real_tests() -> None:
    cited = {
        "tests/test_glimmer_clock.py": (
            "test_snapshot_totals_stop_at_the_floor",
            "test_half_hour_cut_invents_no_change",
            "test_floor_madrid_fall_back",
            "test_overlapping_blocks_union",
            "test_cancellation_is_per_calendar",
            "test_block_crossing_window_start_counts_clipped",
            "test_moved_block_is_not_cancelled",
        ),
        "tests/test_glimmer_metrics.py": (
            "test_zoned_as_of_gives_three_absolute_24h_periods",
        ),
    }
    for rel, names in cited.items():
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for name in names:
            assert f"def {name}" in body, f"{rel}::{name}"


def test_deviation_4_rater_tests_exist() -> None:
    split = (REPO_ROOT / "tests" / "test_rater_split.py").read_text(encoding="utf-8")
    for name in (
        "test_decimal_point_is_not_a_boundary",
        "test_two_sentence_statement_splits_in_two",
        "test_three_period_series_stays_one_and_is_not_compound",
        "test_every_atomic_keeps_its_statement_evidence",
    ):
        assert f"def {name}" in split, name
    score = (REPO_ROOT / "tests" / "test_rater_score.py").read_text(encoding="utf-8")
    for name in (
        "test_score_rates_over_every_atomic_claim",
        "test_unlabelled_claims_need_no_key",
    ):
        assert f"def {name}" in score, name


def test_deviation_8_r7_tests_exist() -> None:
    body = (REPO_ROOT / "tests" / "test_metrics_report.py").read_text(encoding="utf-8")
    for name in (
        "test_r7_window_past_cut_is_right_censored",
        "test_r7_no_screen_unobserved_device_is_unknown",
        "test_r7_no_screen_completed_names_observed_devices",
        "test_r7_github_push_completed_and_this_repo_never_counts",
    ):
        assert f"def {name}" in body, name


def test_deviation_9_r8_tests_exist() -> None:
    body = (REPO_ROOT / "tests" / "test_metrics_report.py").read_text(encoding="utf-8")
    for name in (
        "test_r8_scores_primary_brier_and_clipping_note",
        "test_r8_recovery_grid_labels_and_assumption",
        "test_r8_forecast_actual_neither_untapped",
    ):
        assert f"def {name}" in body, name


def test_public_text_uses_plain_words() -> None:
    contributions = (REPO_ROOT / "CONTRIBUTIONS.md").read_text(encoding="utf-8")
    session = (REPO_ROOT / "docs" / "sessions" / "016-metrics-and-labels.md").read_text(
        encoding="utf-8"
    )
    assert "the dated Deviations entries 13 to 16" in contributions
    assert "the identities that must hold between the counts" in contributions
    assert "the dated Deviations entries 13 to 16" in session
    for body in (contributions, session):
        assert "A12 Deviations entry" not in body
        assert "A12 entry" not in body
        assert "BD4 identities" not in body
