"""Exact equal-tailed intervals over integer Beta counts.

With integer alpha and beta the regularized incomplete beta is a finite
binomial sum, so the quantile comes from exact integer work and holds
byte-stable across platforms with no extra dependency.
"""

import functools
import math
from fractions import Fraction

D = 2**64


def _valid_params(a: int, b: int) -> None:
    # Exact-type checks: isinstance would read as needless against the
    # int annotation, and ValueError stays since the plan pins it.
    if type(a) is not int:
        raise ValueError("a must be an integer")
    if type(b) is not int:
        raise ValueError("b must be an integer")
    if a < 1 or b < 1:
        raise ValueError("a and b must be at least 1")


def beta_cdf(x: Fraction, a: int, b: int) -> Fraction:
    """P(Beta(a, b) <= x) as the binomial sum, in exact fractions."""
    _valid_params(a, b)
    if x <= 0:
        return Fraction(0)
    if x >= 1:
        return Fraction(1)
    n = a + b - 1
    total = Fraction(0)
    for j in range(a, n + 1):
        total += Fraction(math.comb(n, j)) * x**j * (1 - x) ** (n - j)
    return total


def _cdf_at_least(k: int, a: int, b: int, q: Fraction) -> bool:
    """True iff I_x(a, b) >= q at x = k / D, in exact integers. a, b >= 1."""
    n = a + b - 1
    m = D - k
    t, m_power, c = 1, 1, 1
    for j in range(n - 1, a - 1, -1):
        c = c * (j + 1) // (n - j)  # C(n, j) from C(n, j + 1)
        m_power *= m
        t = t * k + c * m_power
    return t * k**a * q.denominator >= q.numerator * D**n


@functools.cache
def beta_quantile(q: Fraction, a: int, b: int) -> float:
    """Least x = k / D with I_x(a, b) >= q, by integer bisection."""
    _valid_params(a, b)
    if q <= 0:
        return 0.0
    if q >= 1:
        return 1.0
    lo, hi = 0, D
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _cdf_at_least(mid, a, b, q):
            hi = mid
        else:
            lo = mid
    return hi / D


def credible_interval(alpha: int, beta: int) -> tuple[float, float]:
    """The equal-tailed 95% interval; coverage reads lo <= p <= hi."""
    return (
        beta_quantile(Fraction(1, 40), alpha, beta),
        beta_quantile(Fraction(39, 40), alpha, beta),
    )
