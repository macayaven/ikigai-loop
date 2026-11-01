"""Ticket 15a: exact intervals against frozen quantile references."""

from fractions import Fraction

import pytest

from framework.learner.beta import (
    _cdf_at_least,
    beta_cdf,
    beta_quantile,
    credible_interval,
)

D = 2**64

# Frozen quantile references (q0.025, q0.975), computed with scipy
# outside this repo on 2026-11-01. Each pair is (a, b, lo, hi).
FROZEN_QUANTILES: tuple[tuple[int, int, float, float], ...] = (
    (1, 1, 0.025000000000, 0.975000000000),
    (2, 1, 0.158113883008, 0.987420882907),
    (1, 6, 0.004210744514, 0.459258126440),
    (6, 1, 0.540741873560, 0.995789255486),
    (3, 4, 0.118117248757, 0.777221904496),
    (4, 3, 0.222778095504, 0.881882751243),
    (8, 7, 0.288609400038, 0.769639458552),
    (10, 5, 0.418964742816, 0.872401570141),
    (14, 1, 0.768364238350, 0.998193219341),
    (51, 51, 0.403643067510, 0.596356932490),
    (71, 31, 0.603852871352, 0.781021273696),
    (1, 101, 0.000250639951, 0.035864620390),
)


def test_frozen_quantiles_within_1e_9() -> None:
    for a, b, lo, hi in FROZEN_QUANTILES:
        got_lo, got_hi = credible_interval(a, b)
        assert abs(got_lo - lo) < 1e-9, (a, b, got_lo, lo)
        assert abs(got_hi - hi) < 1e-9, (a, b, got_hi, hi)


def test_closed_form_beta_1_n() -> None:
    for n in (1, 2, 5, 13, 30):
        lo, hi = credible_interval(1, n)
        assert abs(lo - (1 - 0.975 ** (1 / n))) < 1e-9
        assert abs(hi - (1 - 0.025 ** (1 / n))) < 1e-9


def test_closed_form_beta_n_1() -> None:
    for n in (1, 2, 5, 13, 30):
        lo, hi = credible_interval(n, 1)
        assert abs(lo - 0.025 ** (1 / n)) < 1e-9
        assert abs(hi - 0.975 ** (1 / n)) < 1e-9


def test_cdf_mass_between_interval_ends() -> None:
    for total in (5, 13):
        for a in range(1, total + 2):
            b = total + 2 - a
            lo, hi = credible_interval(a, b)
            mass = beta_cdf(Fraction(hi), a, b) - beta_cdf(Fraction(lo), a, b)
            assert abs(float(mass) - 0.95) < 1e-9, (a, b, mass)


def test_beta_cdf_edges() -> None:
    assert beta_cdf(Fraction(0), 3, 4) == 0
    assert beta_cdf(Fraction(-1, 2), 3, 4) == 0
    assert beta_cdf(Fraction(1), 3, 4) == 1
    assert beta_cdf(Fraction(3, 2), 3, 4) == 1
    assert beta_cdf(Fraction(1, 2), 1, 1) == Fraction(1, 2)


def test_beta_quantile_edges() -> None:
    assert beta_quantile(Fraction(0), 3, 4) == 0.0
    assert beta_quantile(Fraction(-1, 5), 3, 4) == 0.0
    assert beta_quantile(Fraction(1), 3, 4) == 1.0
    assert beta_quantile(Fraction(6, 5), 3, 4) == 1.0


def test_quantiles_monotone_in_q() -> None:
    for a, b in ((1, 1), (3, 4), (10, 5), (51, 51)):
        qs = [
            Fraction(1, 40),
            Fraction(1, 4),
            Fraction(1, 2),
            Fraction(3, 4),
            Fraction(39, 40),
        ]
        vals = [beta_quantile(q, a, b) for q in qs]
        assert vals == sorted(vals)
        assert len(set(vals)) == len(vals)


def test_bad_parameters_raise() -> None:
    with pytest.raises(ValueError):
        beta_cdf(Fraction(1, 2), 0, 1)
    with pytest.raises(ValueError):
        beta_cdf(Fraction(1, 2), 1, 0)
    with pytest.raises(ValueError):
        beta_cdf(Fraction(1, 2), 1.5, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        beta_cdf(Fraction(1, 2), True, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        beta_quantile(Fraction(1, 2), 0, 2)
    with pytest.raises(ValueError):
        beta_quantile(Fraction(1, 2), 2, -3)
    with pytest.raises(ValueError):
        beta_quantile(Fraction(1, 2), False, 2)  # type: ignore[arg-type]


def test_cdf_at_least_agrees_with_beta_cdf() -> None:
    cases = [
        (0, 1, 1, Fraction(1, 2)),
        (D, 1, 1, Fraction(1, 2)),
        (D // 2, 3, 4, Fraction(1, 2)),
        (D // 4, 6, 1, Fraction(39, 40)),
        (3 * D // 4, 2, 5, Fraction(1, 40)),
        (123456789, 8, 7, Fraction(1, 2)),
        (D - 1, 10, 5, Fraction(39, 40)),
        (7, 14, 1, Fraction(1, 40)),
    ]
    for k, a, b, q in cases:
        assert _cdf_at_least(k, a, b, q) == (beta_cdf(Fraction(k, D), a, b) >= q), (
            k,
            a,
            b,
            q,
        )
