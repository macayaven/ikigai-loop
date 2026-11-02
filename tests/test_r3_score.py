"""Ticket 15b: R3 scorer tests (D30-D32, D34).

Pure hand-written rows: no model, no clock, no filesystem. Each test
covers one registered rule, one verdict status, the literal reading, or
one Deviation 6 clause.
"""

from __future__ import annotations

from typing import Any

from evals.r3_score import (
    base_spread,
    profile_rate,
    render_r3,
    score_rows,
    stability_summary,
    wilson,
)


def _pair(
    pair_id: str,
    kind: str,
    profile: str,
    expect_pick: str | None = None,
    expect_avoid: str | None = None,
) -> dict[str, Any]:
    return {
        "id": pair_id,
        "kind": kind,
        "profile": profile,
        "expect_pick": expect_pick,
        "expect_avoid": expect_avoid,
    }


def _doc(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {"pairs": pairs}


def _row(
    pair: dict[str, Any],
    arm: str,
    repeat: int,
    pick: str | None,
    execution: int = 1,
    drawn: bool = True,
    result_kind: str = "proposal",
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    if pick is None and drawn:
        result_kind = "fallback"
    return {
        "pair_id": pair["id"],
        "kind": pair["kind"],
        "profile": pair["profile"],
        "expect_pick": pair["expect_pick"],
        "expect_avoid": pair["expect_avoid"],
        "arm": arm,
        "repeat": repeat,
        "execution": execution,
        "drawn": drawn,
        "pick": pick,
        "result_kind": result_kind,
        "unavailable_reason": unavailable_reason,
    }


def _unavailable(
    pair: dict[str, Any], arm: str, repeat: int, execution: int
) -> dict[str, Any]:
    return _row(
        pair,
        arm,
        repeat,
        None,
        execution=execution,
        drawn=False,
        result_kind="fallback",
        unavailable_reason="timeout",
    )


def _arm_rows(
    pair: dict[str, Any], arm: str, picks: list[str | None]
) -> list[dict[str, Any]]:
    return [_row(pair, arm, repeat + 1, pick) for repeat, pick in enumerate(picks)]


def _info() -> dict[str, Any]:
    return {
        "gate_commit": "a" * 40,
        "gate_hash": "b" * 64,
        "prompt_sha256": "c" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commits": ["a" * 40],
        "model": "muse-wonder-1.0",
        "effort": "high",
        "transports": ["muse"],
        "muse_versions": ["muse 1.4.14"],
        "rules_values": [False],
        "calls": 12,
        "local_starts": 0,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "wall_start": "2026-11-03T10:00:00+00:00",
        "wall_end": "2026-11-03T10:05:00+00:00",
    }


def test_invariance_subset_pass_and_non_subset_fail() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].passed is True
    assert score.pairs["I1"].perturbed.most == frozenset({"c1"})
    rows = _arm_rows(pair, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c2", "c2", "c1"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].passed is False


def test_invariance_tied_most_picked_sets() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = _arm_rows(pair, "base", ["c1", "c2", "c3"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].base.most == frozenset({"c1", "c2", "c3"})
    assert score.pairs["I1"].passed is True
    rows = _arm_rows(pair, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c2", "c3"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].passed is False


def test_arm_of_pure_fallbacks_fails_and_counts() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pair, "perturbed", [None, None, None])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].passed is False
    assert score.invariance_no_pick_pairs == 1
    assert score.pairs["I1"].perturbed.real == 0


def test_each_uninformative_arm() -> None:
    pick_pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pick_pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pick_pair, "perturbed", ["c1", "c1", "c1"])
    scored = score_rows(rows, _doc([pick_pair])).rerun.pairs["D1"]
    assert scored.informative is False
    assert scored.uninformative_reason == "base-picks-expect-3-of-3"

    avoid_pair = _pair("D5", "directional", "builder", expect_avoid="c1")
    rows = _arm_rows(avoid_pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(avoid_pair, "perturbed", ["c2", "c2", "c2"])
    scored = score_rows(rows, _doc([avoid_pair])).rerun.pairs["D5"]
    assert scored.informative is False
    assert scored.uninformative_reason == "base-never-picks-avoid"

    thin_pair = _pair("D2", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(thin_pair, "base", ["c1", None, None])
    rows += _arm_rows(thin_pair, "perturbed", ["c1", "c1", "c1"])
    scored = score_rows(rows, _doc([thin_pair])).rerun.pairs["D2"]
    assert scored.informative is False
    assert scored.uninformative_reason == "base-fewer-than-2-real-picks"


def test_boundary_counts() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    assert score_rows(rows, _doc([pair])).rerun.pairs["D1"].passed is False
    rows = _arm_rows(pair, "base", ["c1", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    assert score_rows(rows, _doc([pair])).rerun.pairs["D1"].passed is True

    avoid = _pair("D5", "directional", "builder", expect_avoid="c1")
    rows = _arm_rows(avoid, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(avoid, "perturbed", ["c2", "c2", "c1"])
    assert score_rows(rows, _doc([avoid])).rerun.pairs["D5"].passed is True
    rows = _arm_rows(avoid, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(avoid, "perturbed", ["c2", "c1", "c1"])
    assert score_rows(rows, _doc([avoid])).rerun.pairs["D5"].passed is False
    rows = _arm_rows(avoid, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(avoid, "perturbed", ["c2", "c2", "c2"])
    assert score_rows(rows, _doc([avoid])).rerun.pairs["D5"].passed is True
    rows = _arm_rows(avoid, "base", ["c1", "c1", "c2"])
    rows += _arm_rows(avoid, "perturbed", ["c2", None, None])
    assert score_rows(rows, _doc([avoid])).rerun.pairs["D5"].passed is False


def test_exhausted_unavailable_scores_as_no_pick() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    for repeat in (1, 2, 3):
        for execution in (1, 2, 3):
            rows.append(_unavailable(pair, "perturbed", repeat, execution))
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I1"].passed is False
    assert score.exhausted_slots == 3
    assert score.unavailable_by_reason == {"timeout": 9}
    assert score.missing_slots == 0


def test_missing_repeat_is_incomplete() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])[:2]
    score = score_rows(rows, _doc([pair])).rerun
    assert score.missing_slots == 1
    assert score.pairs["D1"].passed is False
    assert score.verdict_directional == "incomplete"
    assert score.verdict_combined == "incomplete"


def test_per_profile_denominators() -> None:
    builder_dir = _pair("D1", "directional", "builder", expect_pick="c1")
    disc_inv = _pair("I2", "invariance", "disconnect")
    rows = _arm_rows(builder_dir, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(builder_dir, "perturbed", ["c1", "c1", "c2"])
    rows += _arm_rows(disc_inv, "base", ["d1", "d1", "d1"])
    rows += _arm_rows(disc_inv, "perturbed", ["d1", "d1", "d1"])
    score = score_rows(rows, _doc([builder_dir, disc_inv])).rerun
    assert profile_rate(score, "builder") == (1, 1)
    assert profile_rate(score, "disconnect") == (1, 1)


def test_prediction_verdicts_in_all_statuses() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.verdict_directional == "held"
    assert score.verdict_invariance == "not held"
    assert score.verdict_combined == "not held"

    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c2", "c2", "c1"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.verdict_directional == "not held"

    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.verdict_directional == "not evaluable"
    assert score.verdict_combined == "not evaluable"

    inv_pairs = [_pair(f"I{i}", "invariance", "builder") for i in range(1, 11)]
    rows = []
    for inv in inv_pairs:
        rows += _arm_rows(inv, "base", ["c1", "c1", "c1"])
        rows += _arm_rows(inv, "perturbed", ["c1", "c1", "c1"])
    score = score_rows(rows, _doc(inv_pairs)).rerun
    assert score.verdict_invariance == "held"


def test_literal_reading_differing_and_agreeing() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows.append(_unavailable(pair, "perturbed", 1, 1))
    rows.append(_row(pair, "perturbed", 1, "c1", execution=2))
    rows.append(_row(pair, "perturbed", 2, "c1"))
    rows.append(_row(pair, "perturbed", 3, "c2"))
    full = score_rows(rows, _doc([pair]))
    assert full.literal_applies is True
    assert full.literal is not None
    assert full.rerun.pairs["D1"].passed is True
    assert full.literal.pairs["D1"].passed is False

    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    full = score_rows(rows, _doc([pair]))
    assert full.literal_applies is False
    assert full.literal is None


def test_first_drawn_execution_stands_and_multi_drawn_counted() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows.append(_row(pair, "perturbed", 1, "c1", execution=1))
    rows.append(_row(pair, "perturbed", 1, "c2", execution=2))
    rows += [_row(pair, "perturbed", 2, "c1"), _row(pair, "perturbed", 3, "c2")]
    full = score_rows(rows, _doc([pair]))
    assert full.rerun.pairs["D1"].passed is True
    assert full.rerun.multi_drawn_slots == 1
    text = render_r3(full, _info())
    assert "more than one drawn execution: 1" in text


def test_uninformative_pair_never_renders_fail() -> None:
    pair = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    rows = _arm_rows(pair, "base", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(pair, "perturbed", ["d-screens", "d-screens", "d-screens"])
    full = score_rows(rows, _doc([pair]))
    assert full.rerun.pairs["D6"].informative is False
    text = render_r3(full, _info())
    assert "D6" in text
    assert "uninformative (base-picks-expect-3-of-3)" in text
    assert "fail" not in text.split("D6")[1].split("\n")[0]


def test_base_spread_ignores_no_pick_for_modal_share() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c1", None, None])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    score = score_rows(rows, _doc([pair])).rerun
    spread = base_spread(score)
    assert spread["builder"] == {"c1": 1}
    text = render_r3(score_rows(rows, _doc([pair])), _info())
    assert "modal share 1/1 of real picks" in text
    assert "no picks 2" in text


def test_deviation_6_clauses_in_render() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])
    full = score_rows(rows, _doc([pair]))
    text = render_r3(full, _info())
    assert "c2, c2, c1" in text
    assert "repeat stability" in text
    assert "1/1" in text
    assert "informative 1/1 of 1 directional pairs" in text
    assert "these fixed pairs only" in text
    assert "new, not registered; decides nothing" in text
    assert "at least 70% of informative directional pairs" in text
    assert "at least 8 of 10 invariance" in text


def test_report_shape_result_first_tables_and_lists() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])
    full = score_rows(rows, _doc([pair]))
    text = render_r3(full, _info())
    assert text.startswith("# R3 steering\n\n## Result")
    assert "my reading of the registered fallback and noop rule" in text
    assert "update F" not in text
    assert "| pair | base 1-3 | perturbed 1-3 |" in text
    assert "- gate commit" in text
    assert "- builder:" in text
    assert "I call Ticket 11's propose" in text
    assert "I pass an empty policy block" in text


def test_zero_informative_renders_not_evaluable() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])
    text = render_r3(score_rows(rows, _doc([pair])), _info())
    assert "not evaluable" in text
    assert "passes over informative" not in text


def test_wilson_by_hand() -> None:
    low, high = wilson(7, 10)
    assert abs(low - 0.3968) < 0.001
    assert abs(high - 0.8922) < 0.001


def test_stability_and_spread_definitions() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    score = score_rows(rows, _doc([pair])).rerun
    stability = stability_summary(score)
    assert stability["overall"] == (1, 2)
    assert stability["excluded"] == 0
    spread = base_spread(score)
    assert spread["builder"] == {"c2": 3}
    assert max(spread["builder"].values()) / 30 == 0.1


def test_expect_avoid_more_than_one_of_three_fails_even_when_fewer_than_base() -> None:
    pair = _pair("D5", "directional", "builder", expect_avoid="c1")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
    scored = score_rows(rows, _doc([pair])).rerun.pairs["D5"]
    assert scored.informative is True
    assert scored.passed is False


def test_expect_avoid_equal_to_base_fails() -> None:
    pair = _pair("D5", "directional", "builder", expect_avoid="c1")
    rows = _arm_rows(pair, "base", ["c1", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c2", "c2", "c1"])
    scored = score_rows(rows, _doc([pair])).rerun.pairs["D5"]
    assert scored.informative is True
    assert scored.passed is False


def _directional_doc(
    passing: int, total: int = 10
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = [
        _pair(f"D{i + 1}", "directional", "builder", expect_pick="c1")
        for i in range(total)
    ]
    rows: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        rows += _arm_rows(pair, "base", ["c2", "c2", "c2"])
        if index < passing:
            rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c2"])
        else:
            rows += _arm_rows(pair, "perturbed", ["c1", "c2", "c2"])
    return pairs, rows


def _invariance_doc(
    passing: int, total: int = 10
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pairs = [_pair(f"I{i + 1}", "invariance", "builder") for i in range(total)]
    rows: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs):
        rows += _arm_rows(pair, "base", ["c1", "c1", "c1"])
        if index < passing:
            rows += _arm_rows(pair, "perturbed", ["c1", "c1", "c1"])
        else:
            rows += _arm_rows(pair, "perturbed", ["c2", "c2", "c2"])
    return pairs, rows


def test_directional_threshold_seven_of_ten_held_six_not() -> None:
    pairs, rows = _directional_doc(7)
    score = score_rows(rows, _doc(pairs)).rerun
    assert score.directional_passes == 7
    assert score.directional_informative == 10
    assert score.verdict_directional == "held"
    pairs, rows = _directional_doc(6)
    score = score_rows(rows, _doc(pairs)).rerun
    assert score.directional_passes == 6
    assert score.verdict_directional == "not held"


def test_invariance_threshold_eight_of_ten_held_seven_not() -> None:
    pairs, rows = _invariance_doc(8)
    score = score_rows(rows, _doc(pairs)).rerun
    assert score.invariance_passes == 8
    assert score.invariance_total == 10
    assert score.verdict_invariance == "held"
    pairs, rows = _invariance_doc(7)
    score = score_rows(rows, _doc(pairs)).rerun
    assert score.invariance_passes == 7
    assert score.verdict_invariance == "not held"


def test_missing_repeat_only_in_invariance() -> None:
    directional = _pair("D1", "directional", "builder", expect_pick="c1")
    invariance = _pair("I2", "invariance", "disconnect")
    rows = _arm_rows(directional, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(directional, "perturbed", ["c1", "c1", "c2"])
    rows += _arm_rows(invariance, "base", ["d1", "d1", "d1"])
    rows += _arm_rows(invariance, "perturbed", ["d1", "d1", "d1"])[:2]
    score = score_rows(rows, _doc([directional, invariance])).rerun
    assert score.pairs["I2"].missing == 1
    assert score.verdict_directional == "held"
    assert score.verdict_invariance == "incomplete"
    assert score.verdict_combined == "incomplete"


def test_two_unavailable_is_missing_three_is_exhausted() -> None:
    pair = _pair("I9", "invariance", "builder")
    rows = _arm_rows(pair, "base", ["c1", "c1", "c1"])
    rows += [_row(pair, "perturbed", 2, "c1"), _row(pair, "perturbed", 3, "c1")]
    rows.append(_unavailable(pair, "perturbed", 1, 1))
    rows.append(_unavailable(pair, "perturbed", 1, 2))
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I9"].missing == 1
    assert score.missing_slots == 1
    assert score.exhausted_slots == 0
    assert score.verdict_invariance == "incomplete"
    rows.append(_unavailable(pair, "perturbed", 1, 3))
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["I9"].missing == 0
    assert score.missing_slots == 0
    assert score.exhausted_slots == 1
    assert score.pairs["I9"].perturbed.picks == (None, "c1", "c1")
    assert score.unavailable_by_reason == {"timeout": 3}


def test_single_real_pick_excluded_from_stability() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="c1")
    rows = _arm_rows(pair, "base", ["c2", "c2", "c2"])
    rows += _arm_rows(pair, "perturbed", ["c1", None, None])
    score = score_rows(rows, _doc([pair])).rerun
    assert score.pairs["D1"].perturbed.real == 1
    assert score.pairs["D1"].perturbed.stable is False
    stability = stability_summary(score)
    assert stability["overall"] == (1, 1)
    assert stability["excluded"] == 1


def test_d6_i1_block_counts() -> None:
    d6 = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    i1 = _pair("I1", "invariance", "builder")
    rows = _arm_rows(d6, "base", ["d-screens", "d-screens", "d-family"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-read", "b-read"])
    full = score_rows(rows, _doc([d6, i1]))
    assert full.rerun.pairs["D6"].passed is False
    assert full.rerun.pairs["I1"].passed is False
    text = render_r3(full, _info())
    assert "d-screens base 2/3, perturbed 1/3" in text
    assert "perturbed picks matching a base most-picked commitment: 1/3" in text


def _contrast_four() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    d6 = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    i1 = _pair("I1", "invariance", "builder")
    d1 = _pair("D1", "directional", "builder", expect_pick="b-ship")
    i2 = _pair("I2", "invariance", "disconnect")
    return d6, i1, d1, i2


def test_both_contrast_tables_print_in_order_with_exact_heading() -> None:
    d6, i1, d1, i2 = _contrast_four()
    rows = _arm_rows(d6, "base", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(d1, "base", ["b-read", "b-ship", "b-read"])
    rows += _arm_rows(d1, "perturbed", ["b-ship", "b-ship", "b-ship"])
    rows += _arm_rows(i2, "base", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(i2, "perturbed", ["d-screens", "d-screens", "d-screens"])
    text = render_r3(score_rows(rows, _doc([d6, i1, d1, i2])), _info())
    first = "Registered contrast D6/I1"
    second = "Also registered: D1 and I2 (shown after I saw the results)"
    assert first in text
    assert second in text
    first_idx = text.index(first)
    second_idx = text.index(second)
    d6_idx = text.index("| D6 |", first_idx)
    i1_idx = text.index("| I1 |", first_idx)
    d1_idx = text.index("| D1 |", second_idx)
    i2_idx = text.index("| I2 |", second_idx)
    assert first_idx < d6_idx < i1_idx < second_idx < d1_idx < i2_idx


def test_d1_count_reads_expect_pick_and_i2_counts_perturbed_match() -> None:
    d6 = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    i1 = _pair("I1", "invariance", "builder")
    d1 = _pair("D1", "directional", "builder", expect_pick="zz-top")
    i2 = _pair("I2", "invariance", "disconnect")
    rows = _arm_rows(d6, "base", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(d1, "base", ["zz-top", "other", "other"])
    rows += _arm_rows(d1, "perturbed", ["zz-top", "zz-top", "other"])
    rows += _arm_rows(i2, "base", ["m1", "m1", "m2"])
    rows += _arm_rows(i2, "perturbed", ["m1", "m2", "m2"])
    text = render_r3(score_rows(rows, _doc([d6, i1, d1, i2])), _info())
    d1_line = next(
        line for line in text.splitlines() if line.startswith("| D1 |") and "/3" in line
    )
    assert "zz-top base 1/3, perturbed 2/3" in d1_line
    i2_line = next(
        line for line in text.splitlines() if line.startswith("| I2 |") and "/3" in line
    )
    assert "perturbed picks matching a base most-picked commitment: 1/3" in i2_line
    assert "2/3" not in i2_line


def test_uninformative_sentence_prints_for_d6_and_absent_when_informative() -> None:
    d6 = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    i1 = _pair("I1", "invariance", "builder")
    d1 = _pair("D1", "directional", "builder", expect_pick="b-ship")
    i2 = _pair("I2", "invariance", "disconnect")
    rows = _arm_rows(d6, "base", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(d1, "base", ["b-read", "b-ship", "b-read"])
    rows += _arm_rows(d1, "perturbed", ["b-ship", "b-ship", "b-ship"])
    rows += _arm_rows(i2, "base", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(i2, "perturbed", ["d-screens", "d-screens", "d-screens"])
    text = render_r3(score_rows(rows, _doc([d6, i1, d1, i2])), _info())
    sentence = "I found D6 uninformative:"
    assert sentence in text
    assert "3 of 3" in text.split(sentence, 1)[1].splitlines()[0]
    assert "can't show a move" in text.split(sentence, 1)[1].splitlines()[0]
    assert text.index("| I1 |") < text.index(sentence)
    assert text.index(sentence) < text.index("Also registered: D1 and I2")

    rows = _arm_rows(d6, "base", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(d1, "base", ["b-read", "b-ship", "b-read"])
    rows += _arm_rows(d1, "perturbed", ["b-ship", "b-ship", "b-ship"])
    rows += _arm_rows(i2, "base", ["d-screens", "d-screens", "d-family"])
    rows += _arm_rows(i2, "perturbed", ["d-screens", "d-screens", "d-family"])
    text = render_r3(score_rows(rows, _doc([d6, i1, d1, i2])), _info())
    assert "I found D6 uninformative" not in text
    assert "I found D1 uninformative" not in text
    assert "I found I1 uninformative" not in text
    assert "I found I2 uninformative" not in text


def test_uninformative_sentence_stands_outside_the_table() -> None:
    d6 = _pair("D6", "directional", "disconnect", expect_pick="d-screens")
    i1 = _pair("I1", "invariance", "builder")
    d1 = _pair("D1", "directional", "builder", expect_pick="b-ship")
    i2 = _pair("I2", "invariance", "disconnect")
    rows = _arm_rows(d6, "base", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-screens", "d-screens"])
    rows += _arm_rows(i1, "base", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(i1, "perturbed", ["b-ship", "b-ship", "b-read"])
    rows += _arm_rows(d1, "base", ["b-ship", "b-ship", "b-ship"])
    rows += _arm_rows(d1, "perturbed", ["b-ship", "b-ship", "b-ship"])
    rows += _arm_rows(i2, "base", ["d-screens", "d-screens", "d-family"])
    rows += _arm_rows(i2, "perturbed", ["d-screens", "d-screens", "d-family"])
    text = render_r3(score_rows(rows, _doc([d6, i1, d1, i2])), _info())
    lines = text.splitlines()
    first_heading = (
        "## Registered contrast D6/I1 (same perturbation, both goals; "
        "PREREG defines no out-of-6 score)"
    )
    second_heading = "## Also registered: D1 and I2 (shown after I saw the results)"
    for heading in (first_heading, second_heading):
        at = lines.index(heading)
        assert lines[at + 1] == ""
        assert lines[at + 2].startswith("|")
    for pair_id in ("D6", "D1"):
        at = next(
            index
            for index, line in enumerate(lines)
            if line.startswith(f"I found {pair_id} uninformative")
        )
        assert lines[at - 1] == ""
        assert lines[at - 2].startswith("|")


def _timed_row(
    pair: dict[str, Any], arm: str, repeat: int, codes: list[list[str]]
) -> dict[str, Any]:
    row = _row(pair, arm, repeat, "c1")
    row["attempts"] = [{"codes": [list(code) for code in codes]}]
    return row


def test_method_lists_pre_13b_run_without_stalled_call_retry() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = [
        _timed_row(pair, "base", 1, []),
        _timed_row(pair, "base", 2, []),
        _timed_row(pair, "base", 3, []),
        _timed_row(pair, "perturbed", 1, []),
        _timed_row(pair, "perturbed", 2, []),
        _timed_row(pair, "perturbed", 3, []),
    ]
    info = _info()
    info["gate_hash"] = "42b57031c11b" + "0" * 52
    info["three_layer_rows"] = 0
    info["two_layer_rows"] = 6
    info["timeout_retries"] = 0
    text = render_r3(score_rows(rows, _doc([pair])), info)
    assert "42b57031c11b" in text
    assert "predates Ticket 13b" in text
    assert "without the stalled-call retry" in text
    assert "none of its 6 calls timed out" in text


def _stack_info(
    three: int, two: int, timeout_total: int, gate_prefix: str = "ab1234567890"
) -> dict[str, Any]:
    info = _info()
    info["gate_hash"] = gate_prefix + "0" * (64 - len(gate_prefix))
    info["three_layer_rows"] = three
    info["two_layer_rows"] = two
    info["timeout_retries"] = timeout_total
    return info


def test_client_stack_two_layer_rows_name_two_layer_stack() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = [
        _timed_row(pair, "base", 1, []),
        _timed_row(pair, "base", 2, []),
        _timed_row(pair, "base", 3, []),
        _timed_row(pair, "perturbed", 1, []),
        _timed_row(pair, "perturbed", 2, []),
        _timed_row(pair, "perturbed", 3, []),
    ]
    assert all("timeout_retries" not in row for row in rows)
    text = render_r3(score_rows(rows, _doc([pair])), _stack_info(0, 6, 0))
    assert "LocalRetryClient around MuseExecClient" in text
    assert "TimeoutRetryClient" not in text
    assert "predates Ticket 13b" in text


def test_client_stack_three_layer_rows_name_three_layer_stack() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = [_timed_row(pair, "base", 1, [])]
    for row in rows:
        row["timeout_retries"] = 2
    rows += [_timed_row(pair, "base", 2, []), _timed_row(pair, "base", 3, [])]
    for row in rows[1:]:
        row["timeout_retries"] = 0
    rows += [_timed_row(pair, "perturbed", 1, [])]
    for row in rows[3:]:
        row["timeout_retries"] = 0
    rows += [_timed_row(pair, "perturbed", 2, []), _timed_row(pair, "perturbed", 3, [])]
    for row in rows[4:]:
        row["timeout_retries"] = 0
    text = render_r3(
        score_rows(rows, _doc([pair])), _stack_info(6, 0, 2, gate_prefix="cd1234567890")
    )
    assert "TimeoutRetryClient around LocalRetryClient around MuseExecClient" in text
    assert "with 2 timeout retries" in text
    assert "predates Ticket 13b" not in text
    assert "without a deadline, like the local one" in text


def test_client_stack_mixed_rows_name_both_with_counts() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = [
        _timed_row(pair, "base", 1, []),
        _timed_row(pair, "base", 2, []),
        _timed_row(pair, "base", 3, []),
        _timed_row(pair, "perturbed", 1, []),
        _timed_row(pair, "perturbed", 2, []),
        _timed_row(pair, "perturbed", 3, []),
    ]
    rows[0]["timeout_retries"] = 1
    rows[1]["timeout_retries"] = 0
    text = render_r3(score_rows(rows, _doc([pair])), _stack_info(2, 4, 1))
    assert (
        "TimeoutRetryClient around LocalRetryClient around MuseExecClient "
        "for 2 rows and LocalRetryClient around MuseExecClient for 4 rows" in text
    )
    assert "with 1 timeout retries" in text


def test_method_timeout_count_comes_from_rows() -> None:
    pair = _pair("I1", "invariance", "builder")
    rows = [
        _timed_row(pair, "base", 1, [["MODEL_UNAVAILABLE", "timeout"]]),
        _timed_row(pair, "base", 2, []),
        _timed_row(pair, "base", 3, []),
        _timed_row(pair, "perturbed", 1, []),
        _timed_row(pair, "perturbed", 2, []),
        _timed_row(pair, "perturbed", 3, []),
    ]
    text = render_r3(score_rows(rows, _doc([pair])), _info())
    assert "1 of its 6 calls timed out" in text


def _history_full_row(
    pair_id: str,
    arm: str,
    repeat: int,
    pick: str | None,
    *,
    gate_hash: str,
    prompt_sha: str,
    pairs_sha: str,
    recorded_at: str,
) -> dict[str, Any]:
    return {
        "pair_id": pair_id,
        "arm": arm,
        "repeat": repeat,
        "execution": 1,
        "drawn": True,
        "pick": pick,
        "result_kind": "proposal" if pick is not None else "fallback",
        "unavailable_reason": None,
        "model": "m",
        "effort": "high",
        "gate_commit": "e" * 40,
        "gate_hash": gate_hash,
        "prompt_sha256": prompt_sha,
        "pairs_sha256": pairs_sha,
        "tree_commit": "f" * 40,
        "transport": "muse",
        "muse_version": "muse 1.4.14",
        "harness_rules_file": False,
        "attempts": [{"codes": [], "prompt_tokens": 1, "completion_tokens": 1}],
        "local_retries": [],
        "recorded_at": recorded_at,
    }


def _history_file_rows(
    base_picks: list[str | None],
    pert_picks: list[str | None],
    *,
    gate_hash: str,
    prompt_sha: str,
    recorded_at: str,
) -> list[dict[str, Any]]:
    from evals.r3 import load_pairs as _load_pairs

    _doc_real, pairs_sha = _load_pairs()
    rows: list[dict[str, Any]] = []
    for repeat, pick in enumerate(base_picks, start=1):
        rows.append(
            _history_full_row(
                "D1",
                "base",
                repeat,
                pick,
                gate_hash=gate_hash,
                prompt_sha=prompt_sha,
                pairs_sha=pairs_sha,
                recorded_at=recorded_at,
            )
        )
    for repeat, pick in enumerate(pert_picks, start=1):
        rows.append(
            _history_full_row(
                "D1",
                "perturbed",
                repeat,
                pick,
                gate_hash=gate_hash,
                prompt_sha=prompt_sha,
                pairs_sha=pairs_sha,
                recorded_at=recorded_at,
            )
        )
    return rows


def _write_history_file(path: Any, rows: list[dict[str, Any]]) -> None:
    import json as _json

    path.write_text(
        "".join(_json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_summary_single_run_is_byte_identical(tmp_path: Any, capsys: Any) -> None:
    from evals import r3 as _r3
    from evals.r3 import _summary_info as _r3_info
    from evals.r3 import load_rows_file as _load_rows
    from evals.r3_score import render_r3 as _render
    from evals.r3_score import score_rows as _score

    rows = _history_file_rows(
        ["b-read", "b-read", "b-read"],
        ["b-ship", "b-ship", "b-ship"],
        gate_hash="a" * 64,
        prompt_sha="c" * 64,
        recorded_at="2026-11-01T10:00:00+00:00",
    )
    _write_history_file(tmp_path / "one.jsonl", rows)
    assert _r3.main(["--summary", "--results-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    loaded = _load_rows(tmp_path / "one.jsonl")
    assert out == _render(_score(loaded), _r3_info(loaded))
    assert "First run" not in out
    assert "Earlier run" not in out


def test_summary_two_runs_newer_full_older_first_with_own_numbers(
    tmp_path: Any, capsys: Any
) -> None:
    from evals import r3 as _r3

    old = _history_file_rows(
        ["b-read", "b-read", "b-read"],
        ["b-read", "b-read", "b-read"],
        gate_hash="a" * 64,
        prompt_sha="c" * 64,
        recorded_at="2026-11-01T10:00:00+00:00",
    )
    new = _history_file_rows(
        ["b-read", "b-read", "b-ship"],
        ["b-ship", "b-ship", "b-ship"],
        gate_hash="b" * 64,
        prompt_sha="d" * 64,
        recorded_at="2026-11-02T10:00:00+00:00",
    )
    _write_history_file(tmp_path / "old.jsonl", old)
    _write_history_file(tmp_path / "new.jsonl", new)
    assert _r3.main(["--summary", "--results-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert out.count("# R3 steering") == 1
    assert "First run, gate aaaaaaaaaaaa, prompt cccccccccccc" in out
    assert "Earlier run" not in out
    assert "The headline above is the newest run" in out
    headline_table = out.split("## All six picks per pair")[1].split("## First run")[0]
    assert "b-read, b-read, b-ship" in headline_table
    first_section = out.split("## First run")[1]
    assert "b-read, b-read, b-read | b-read, b-read, b-read" in first_section
    assert "b-read, b-read, b-ship" not in first_section


def test_summary_three_runs_labels_middle_earlier(tmp_path: Any, capsys: Any) -> None:
    from evals import r3 as _r3

    _write_history_file(
        tmp_path / "a.jsonl",
        _history_file_rows(
            ["b-read", "b-read", "b-read"],
            ["b-read", "b-read", "b-read"],
            gate_hash="a" * 64,
            prompt_sha="c" * 64,
            recorded_at="2026-11-01T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "b.jsonl",
        _history_file_rows(
            ["b-ship", "b-ship", "b-ship"],
            ["b-ship", "b-ship", "b-ship"],
            gate_hash="b" * 64,
            prompt_sha="d" * 64,
            recorded_at="2026-11-02T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "c.jsonl",
        _history_file_rows(
            ["b-read", "b-ship", "b-read"],
            ["b-ship", "b-read", "b-ship"],
            gate_hash="e" * 64,
            prompt_sha="f" * 64,
            recorded_at="2026-11-03T10:00:00+00:00",
        ),
    )
    assert _r3.main(["--summary", "--results-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "First run, gate aaaaaaaaaaaa, prompt cccccccccccc" in out
    assert "Earlier run, gate bbbbbbbbbbbb, prompt dddddddddddd" in out
    assert out.index("## First run") < out.index("## Earlier run")
    middle_section = out.split("## Earlier run")[1]
    assert "b-ship, b-ship, b-ship | b-ship, b-ship, b-ship" in middle_section


def test_summary_identity_renders_one_file_alone(tmp_path: Any, capsys: Any) -> None:
    from evals import r3 as _r3
    from evals.r3 import _summary_info as _r3_info
    from evals.r3 import load_rows_file as _load_rows
    from evals.r3_score import render_r3 as _render
    from evals.r3_score import score_rows as _score

    _write_history_file(
        tmp_path / "old.jsonl",
        _history_file_rows(
            ["b-read", "b-read", "b-read"],
            ["b-read", "b-read", "b-read"],
            gate_hash="a" * 64,
            prompt_sha="c" * 64,
            recorded_at="2026-11-01T10:00:00+00:00",
        ),
    )
    _write_history_file(
        tmp_path / "new.jsonl",
        _history_file_rows(
            ["b-read", "b-read", "b-ship"],
            ["b-ship", "b-ship", "b-ship"],
            gate_hash="b" * 64,
            prompt_sha="d" * 64,
            recorded_at="2026-11-02T10:00:00+00:00",
        ),
    )
    assert (
        _r3.main(["--summary", "--results-dir", str(tmp_path), "--identity", "a" * 12])
        == 0
    )
    out = capsys.readouterr().out
    assert "First run" not in out
    assert "Earlier run" not in out
    loaded = _load_rows(tmp_path / "old.jsonl")
    assert out == _render(_score(loaded), _r3_info(loaded))


def test_missing_contrast_pairs_render_without_raising() -> None:
    d6, i1, d1, i2 = _contrast_four()
    rows = _arm_rows(d6, "base", ["d-screens", "d-family", "d-family"])
    rows += _arm_rows(d6, "perturbed", ["d-screens", "d-family", "d-family"])
    text = render_r3(score_rows(rows, _doc([d6, i1])), _info())
    assert "Also registered: D1 and I2" not in text
    assert "missing repeat slots:" in text

    rows = _arm_rows(d1, "base", ["b-read", "b-ship", "b-read"])
    rows += _arm_rows(d1, "perturbed", ["b-ship", "b-ship", "b-ship"])
    text = render_r3(score_rows(rows, _doc([d1, i2])), _info())
    assert "Registered contrast D6/I1" not in text
    assert "Also registered: D1 and I2 (shown after I saw the results)" in text
    assert "missing repeat slots:" in text


def test_closure_heading_and_line_with_field() -> None:
    from evals.r3_score import closure_line, closure_suffix, history_heading

    info = {
        "gate_commit": "a" * 40,
        "gate_hash": "a" * 64,
        "prompt_sha256": "b" * 64,
        "closure_sha256": "c" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commit": "d" * 40,
        "tree_commits": ["d" * 40],
        "model": "m",
        "effort": "high",
    }
    assert history_heading(info, first=True) == (
        "First run, gate " + "a" * 12 + ", prompt " + "b" * 12 + ", closure " + "c" * 12
    )
    assert history_heading(info, first=False) == (
        "Earlier run, gate "
        + "a" * 12
        + ", prompt "
        + "b" * 12
        + ", closure "
        + "c" * 12
    )
    assert closure_suffix(info) == ", closure " + "c" * 12
    assert closure_line(info) == "- closure " + "c" * 12


def test_closure_heading_and_line_without_field() -> None:
    from evals.r3_score import closure_line, history_heading

    info = {
        "gate_commit": "a" * 40,
        "gate_hash": "a" * 64,
        "prompt_sha256": "b" * 64,
        "pairs_sha256": "d" * 64,
        "tree_commit": "d" * 40,
        "tree_commits": ["d" * 40],
        "model": "m",
        "effort": "high",
    }
    assert history_heading(info, first=True) == (
        "First run, gate "
        + "a" * 12
        + ", prompt "
        + "b" * 12
        + ", closure not recorded; tree "
        + "d" * 12
    )
    assert closure_line(info) == "- closure not recorded; tree " + "d" * 12


def test_rendered_identity_carries_closure_line() -> None:
    pair = _pair("D1", "directional", "builder", expect_pick="b-ship")
    rows = _arm_rows(pair, "base", ["b-read", "b-read", "b-read"])
    rows += _arm_rows(pair, "perturbed", ["b-ship", "b-ship", "b-ship"])
    text = render_r3(score_rows(rows, _doc([pair])), _info())
    assert "- closure not recorded; tree " + "a" * 12 in text
    info = dict(_info())
    info["closure_sha256"] = "c" * 64
    text = render_r3(score_rows(rows, _doc([pair])), info)
    assert "- closure " + "c" * 12 in text
    assert "closure not recorded" not in text
