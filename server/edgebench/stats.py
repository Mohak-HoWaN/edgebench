"""The statistics of ADR 0004, with no dependency beyond the standard library.

A *repeat* is one run of N timed iterations; a configuration (a variant at a thread count on a dataset) is run several
times. The headline latency is the mean of the repeats' medians, with a Student t interval across repeats; two
configurations are compared with Welch's t-test on the repeat values. With three repeats the interval is wide, and this
module says so rather than hiding it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """P(T <= t) for Student's t with ``df`` degrees of freedom (not necessarily a whole number)."""
    tail = 0.5 * betainc(df / 2.0, 0.5, df / (df + t * t))
    return 1.0 - tail if t > 0 else tail


def t_quantile(p: float, df: float) -> float:
    """The t value with P(T <= t) = p, found by bisection (accurate to about 1e-10)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be between 0 and 1")
    if p == 0.5:
        return 0.0
    lo, hi = -1.0, 1.0
    while t_cdf(lo, df) > p:
        lo *= 2.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


@dataclass(frozen=True)
class Interval:
    mean: float
    half_width: float | None  # None with fewer than 2 values: no interval can be made
    n: int
    wide: bool  # True when the interval is too wide to trust (fewer than 5 repeats)

    @property
    def low(self) -> float | None:
        return None if self.half_width is None else self.mean - self.half_width

    @property
    def high(self) -> float | None:
        return None if self.half_width is None else self.mean + self.half_width


def mean_interval(values: Sequence[float], level: float = 0.95) -> Interval:
    """Mean and the Student t interval over the values (the repeats): ``mean +/- t * s / sqrt(n)``."""
    n = len(values)
    if n == 0:
        raise ValueError("no values")
    mean = sum(values) / n
    if n < 2:
        return Interval(mean, None, n, True)
    s = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
    t = t_quantile(1.0 - (1.0 - level) / 2.0, n - 1)
    return Interval(mean, t * s / math.sqrt(n), n, n < 5)


@dataclass(frozen=True)
class Welch:
    t: float
    df: float
    p: float  # two-sided
    significant: bool


def welch_test(a: Sequence[float], b: Sequence[float], alpha: float = 0.05) -> Welch | None:
    """Welch's t-test on two samples of repeat values. None when either has fewer than two values."""
    if len(a) < 2 or len(b) < 2:
        return None
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se2 = va / len(a) + vb / len(b)
    if se2 == 0.0:  # identical repeats on both sides: any difference at all is exact
        same = ma == mb
        return Welch(
            0.0 if same else math.copysign(math.inf, ma - mb),
            float(len(a) + len(b) - 2),
            1.0 if same else 0.0,
            not same,
        )
    t = (ma - mb) / math.sqrt(se2)
    df = se2**2 / ((va / len(a)) ** 2 / (len(a) - 1) + (vb / len(b)) ** 2 / (len(b) - 1))
    p = 2.0 * (1.0 - t_cdf(abs(t), df))
    return Welch(t, df, p, p < alpha)


def percentile(values: Sequence[float], q: float) -> float:
    """The q-th percentile (0 to 100) with linear interpolation, as NumPy does by default."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100.0
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)
