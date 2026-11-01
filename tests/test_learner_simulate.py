"""Ticket 15a: known-preference simulation against the frozen grid."""

import math
import random
from fractions import Fraction

import pytest

from framework.learner.beta import credible_interval
from framework.learner.schemas import RecoverCell
from framework.learner.simulate import recover, recover_table

# Frozen exact grid, computed by enumeration outside this repo on
# 2026-11-01. Each cell is (true_p, n_cards) to
# (correct_side, mean_absolute_error, coverage, mean_interval_width).
FROZEN_GRID: dict[tuple[float, int], tuple[float | None, float, float, float]] = {
    (0.5, 5): (None, 0.133929, 0.937500, 0.627244),
    (0.6, 5): (0.682560, 0.127808, 0.989760, 0.620604),
    (0.7, 5): (0.836920, 0.120255, 0.969220, 0.600559),
    (0.8, 5): (0.942080, 0.123163, 0.942080, 0.566739),
    (0.9, 5): (0.991440, 0.114286, 0.918540, 0.518524),
    (0.5, 13): (None, 0.097754, 0.977539, 0.466939),
    (0.6, 13): (0.771156, 0.092461, 0.955290, 0.459225),
    (0.7, 13): (0.937625, 0.091485, 0.972088, 0.435385),
    (0.8, 13): (0.992996, 0.078483, 0.969965, 0.393082),
    (0.9, 13): (0.999901, 0.070279, 0.965839, 0.327538),
    (0.5, 30): (None, 0.067718, 0.957226, 0.333603),
    (0.6, 30): (0.824631, 0.067180, 0.961577, 0.327388),
    (0.7, 30): (0.983063, 0.063645, 0.929793, 0.308004),
    (0.8, 30): (0.999769, 0.056556, 0.963861, 0.272738),
    (0.9, 30): (1.000000, 0.044272, 0.974173, 0.214475),
    (0.5, 100): (None, 0.039014, 0.943112, 0.191775),
    (0.6, 100): (0.972901, 0.038369, 0.948118, 0.187990),
    (0.7, 100): (0.999978, 0.036030, 0.949558, 0.176150),
    (0.8, 100): (1.000000, 0.031622, 0.940520, 0.154416),
    (0.9, 100): (1.000000, 0.024034, 0.936398, 0.117443),
}

TRUE_PS = (0.5, 0.6, 0.7, 0.8, 0.9)
N_CARDS = (5, 13, 30, 100)

# One cache for the module so repeated cells cost nothing twice.
_CELL_CACHE: dict[tuple[float, int, int, int], RecoverCell] = {}


def _cached(true_p: float, n_cards: int, n_sims: int, seed: int) -> RecoverCell:
    key = (true_p, n_cards, n_sims, seed)
    cell = _CELL_CACHE.get(key)
    if cell is None:
        cell = recover(true_p, n_cards, n_sims, seed)
        _CELL_CACHE[key] = cell
    return cell


def _enumerate_cell(true_p: float, n_cards: int) -> dict[str, float | None]:
    """Exact cell values by counting over k takes out of n_cards."""
    p = Fraction(str(true_p))
    stats: dict[str, float] = {"mae": 0.0, "cov": 0.0, "width": 0.0, "side": 0.0}
    second: dict[str, float] = {"mae": 0.0, "cov": 0.0, "width": 0.0, "side": 0.0}
    for k in range(n_cards + 1):
        weight = float(
            Fraction(math.comb(n_cards, k)) * p**k * (1 - p) ** (n_cards - k)
        )
        a, b = 1 + k, 1 + n_cards - k
        mean = a / (a + b)
        lo, hi = credible_interval(a, b)
        mae = abs(mean - true_p)
        cov = 1.0 if lo <= true_p <= hi else 0.0
        width = hi - lo
        if true_p > 0.5:
            side = 1.0 if mean > 0.5 else 0.0
        elif true_p < 0.5:
            side = 1.0 if mean < 0.5 else 0.0
        else:
            side = 0.0
        for name, value in (
            ("mae", mae),
            ("cov", cov),
            ("width", width),
            ("side", side),
        ):
            stats[name] += weight * value
            second[name] += weight * value * value
    out: dict[str, float | None] = {
        "correct_side": None if true_p == 0.5 else stats["side"],
        "mean_absolute_error": stats["mae"],
        "coverage": stats["cov"],
        "mean_interval_width": stats["width"],
    }
    out["var_side"] = second["side"] - stats["side"] ** 2
    out["var_mae"] = second["mae"] - stats["mae"] ** 2
    out["var_cov"] = second["cov"] - stats["cov"] ** 2
    out["var_width"] = second["width"] - stats["width"] ** 2
    return out


def test_exact_grid_matches_frozen_literals() -> None:
    for (true_p, n_cards), frozen in FROZEN_GRID.items():
        exact = _enumerate_cell(true_p, n_cards)
        want_side, want_mae, want_cov, want_width = frozen
        got_side = exact["correct_side"]
        got_mae = exact["mean_absolute_error"]
        got_cov = exact["coverage"]
        got_width = exact["mean_interval_width"]
        assert isinstance(got_mae, float)
        assert isinstance(got_cov, float)
        assert isinstance(got_width, float)
        assert got_side == want_side or (
            want_side is not None
            and got_side is not None
            and abs(got_side - want_side) < 1e-4
        ), (true_p, n_cards)
        assert abs(got_mae - want_mae) < 1e-4
        assert abs(got_cov - want_cov) < 1e-4
        assert abs(got_width - want_width) < 1e-4


def test_frozen_coverage_floor() -> None:
    for (true_p, n_cards), frozen in FROZEN_GRID.items():
        assert 0.91 <= frozen[2] <= 1.0, (true_p, n_cards)


def test_prior_average_coverage_near_nominal() -> None:
    for n_cards in (5, 13):
        rng = random.Random(f"prioravg:{n_cards}")
        hits = 0
        draws = 5000
        for _ in range(draws):
            true_p = rng.uniform(0, 1)
            cell = recover(true_p, n_cards, 1, 7)
            a_hits = cell.coverage == 1.0
            hits += 1 if a_hits else 0
        assert abs(hits / draws - 0.95) < 0.0125, n_cards


def test_simulated_close_to_exact_within_4_se() -> None:
    for n_cards in (5, 13, 30):
        for true_p in TRUE_PS:
            cell = _cached(true_p, n_cards, 500, 1)
            exact = _enumerate_cell(true_p, n_cards)
            n_sims = 500
            for name, var_name in (
                ("mean_absolute_error", "var_mae"),
                ("coverage", "var_cov"),
                ("mean_interval_width", "var_width"),
            ):
                var = exact[var_name]
                got = getattr(cell, name)
                want = exact[name]
                assert isinstance(var, float)
                assert isinstance(got, float) and isinstance(want, float)
                se = math.sqrt(var / n_sims)
                assert abs(got - want) <= 4 * se + 1e-12, (true_p, n_cards, name)
            if true_p != 0.5:
                var = exact["var_side"]
                assert isinstance(var, float)
                se = math.sqrt(var / n_sims)
                got = cell.correct_side
                want = exact["correct_side"]
                assert got is not None and want is not None
                assert abs(got - want) <= 4 * se + 1e-12, (true_p, n_cards)
    cell = _cached(0.7, 100, 100, 1)
    exact = _enumerate_cell(0.7, 100)
    for name, var_name in (
        ("mean_absolute_error", "var_mae"),
        ("coverage", "var_cov"),
        ("mean_interval_width", "var_width"),
        ("correct_side", "var_side"),
    ):
        var = exact[var_name]
        assert isinstance(var, float)
        se = math.sqrt(var / 100)
        got = getattr(cell, name)
        want = exact[name]
        assert got is not None and want is not None
        assert abs(got - want) <= 4 * se + 1e-12, ("100", name)


def test_better_with_n_on_frozen_grid() -> None:
    for true_p in TRUE_PS:
        maes = [FROZEN_GRID[(true_p, n)][1] for n in N_CARDS]
        widths = [FROZEN_GRID[(true_p, n)][3] for n in N_CARDS]
        assert maes == sorted(maes, reverse=True)
        assert widths == sorted(widths, reverse=True)
        assert len(set(maes)) == 4 and len(set(widths)) == 4
        sides = [FROZEN_GRID[(true_p, n)][0] for n in N_CARDS]
        known = [s for s in sides if s is not None]
        assert known == sorted(known)


def test_exact_grid_coverage_is_inclusive_at_the_limit() -> None:
    lo, _ = credible_interval(2, 1)
    assert recover(lo, 1, 200, 1).coverage == 1.0


def test_better_with_n_on_simulated_cells() -> None:
    arm = (5, 13, 30, 100)
    for true_p in TRUE_PS:
        maes = [
            _cached(true_p, n, 200 if n == 100 else 500, 1).mean_absolute_error
            for n in arm
        ]
        widths = [
            _cached(true_p, n, 200 if n == 100 else 500, 1).mean_interval_width
            for n in arm
        ]
        assert maes == sorted(maes, reverse=True), true_p
        assert widths == sorted(widths, reverse=True), true_p
        sides = [
            _cached(true_p, n, 200 if n == 100 else 500, 1).correct_side for n in arm
        ]
        known = [s for s in sides if s is not None]
        assert known == sorted(known), true_p


def test_symmetry_at_03_against_07() -> None:
    exact_low = _enumerate_cell(0.3, 13)
    exact_high = _enumerate_cell(0.7, 13)
    assert exact_low["correct_side"] == pytest.approx(exact_high["correct_side"])
    assert exact_low["mean_absolute_error"] == pytest.approx(
        exact_high["mean_absolute_error"]
    )
    low = _cached(0.3, 13, 2000, 1)
    high = _cached(0.7, 13, 2000, 1)
    assert low.correct_side is not None and high.correct_side is not None
    assert abs(low.correct_side - high.correct_side) < 0.05


def test_deterministic_same_seed_and_alone_vs_table() -> None:
    first = _cached(0.7, 13, 500, 1)
    second = recover(0.7, 13, 500, 1)
    assert first == second
    other_seed = recover(0.7, 13, 500, 2)
    assert other_seed != first
    table = recover_table(seed=1, n_sims=100, true_ps=(0.7,), n_cards=(13,))
    alone = recover(0.7, 13, 100, 1)
    assert table.cells[0] == alone
    assert table.label == "simulated"
    assert table.n_sims == 100
    assert table.seed == 1


def test_frozen_recover_cell_literal() -> None:
    # Captured once from a reviewed run where everything else was green;
    # sanity-checked by hand against the frozen (0.7, 13) grid cell
    # (0.937625, 0.091485, 0.972088, 0.435385): each number sits within
    # simulation noise of it (468/500 side hits, 484/500 covered).
    cell = _cached(0.7, 13, 500, 1)
    assert cell.correct_side == 0.936
    assert cell.mean_absolute_error == 0.09213333333333333
    assert cell.coverage == 0.968
    assert cell.mean_interval_width == 0.4373819271704173


def test_recover_validation() -> None:
    with pytest.raises(ValueError):
        recover(0.0, 13, 500, 1)
    with pytest.raises(ValueError):
        recover(1.0, 13, 500, 1)
    with pytest.raises(ValueError):
        recover(0.7, 0, 500, 1)
    with pytest.raises(ValueError):
        recover(0.7, 13, 0, 1)
