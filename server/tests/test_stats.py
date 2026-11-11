from __future__ import annotations

import math

import pytest

from edgebench.stats import betainc, mean_interval, percentile, t_cdf, t_quantile, welch_test


def test_the_t_quantiles_match_the_published_table() -> None:
    # two-sided 95% critical values from any statistics table
    for df, expected in ((1, 12.706), (2, 4.303), (4, 2.776), (9, 2.262), (29, 2.045), (120, 1.980)):
        assert t_quantile(0.975, df) == pytest.approx(expected, abs=0.001)
    assert t_quantile(0.5, 5) == 0.0 and t_quantile(0.025, 4) == pytest.approx(-2.776, abs=0.001)


def test_the_t_distribution_is_symmetric_and_the_beta_function_is_right_at_known_points() -> None:
    assert t_cdf(0.0, 7) == pytest.approx(0.5) and t_cdf(1.3, 7) + t_cdf(-1.3, 7) == pytest.approx(1.0)
    assert betainc(1, 1, 0.3) == pytest.approx(0.3)  # the uniform distribution
    assert betainc(2, 3, 0.5) == pytest.approx(0.6875)  # I_0.5(2, 3) = 11/16
    assert betainc(0.5, 0.5, 0.5) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        t_quantile(1.0, 3)


def test_the_interval_for_three_repeats_is_wide_and_says_so() -> None:
    # 10, 12, 14: mean 12, s = 2, half width = 4.303 * 2 / sqrt(3)
    iv = mean_interval([10.0, 12.0, 14.0])
    assert iv.mean == 12.0 and iv.half_width == pytest.approx(4.303 * 2 / math.sqrt(3), abs=0.005)
    assert iv.wide and iv.n == 3 and iv.low == pytest.approx(12 - iv.half_width, abs=1e-9)  # type: ignore[operator]
    five = mean_interval([10.0, 11.0, 12.0, 13.0, 14.0])
    assert not five.wide and five.half_width == pytest.approx(2.776 * math.sqrt(2.5) / math.sqrt(5), abs=0.005)


def test_one_repeat_has_no_interval_and_no_values_is_an_error() -> None:
    iv = mean_interval([5.0])
    assert iv.mean == 5.0 and iv.half_width is None and iv.low is None and iv.high is None and iv.wide
    with pytest.raises(ValueError):
        mean_interval([])


def test_welch_matches_scipy() -> None:
    # expected values from scipy.stats.ttest_ind(a, b, equal_var=False), scipy 1.18.1
    a = [27.5, 21.0, 19.0, 23.6, 17.0, 17.9, 16.9, 20.1, 21.9, 22.6, 23.9, 26.0, 22.9, 25.3, 19.5]
    b = [27.1, 22.0, 20.8, 23.4, 23.4, 23.5, 25.8, 22.0, 24.8, 20.2, 21.9, 22.2, 24.2, 23.6, 22.9]
    w = welch_test(a, b)
    assert w is not None
    assert w.t == pytest.approx(-1.563076, abs=1e-5) and w.df == pytest.approx(21.8630, abs=1e-3)
    assert w.p == pytest.approx(0.132395, abs=1e-5) and not w.significant


def test_a_clear_difference_is_significant_and_an_unclear_one_is_not() -> None:
    clear = welch_test([10.0, 10.1, 9.9, 10.0], [12.0, 12.1, 11.9, 12.0])
    assert clear is not None and clear.significant and clear.p < 0.001 and clear.t < 0
    noisy = welch_test([10.0, 12.0, 14.0], [11.0, 13.0, 15.0])
    assert noisy is not None and not noisy.significant  # the same spread, shifted by 1: three repeats cannot tell
    assert welch_test([1.0], [2.0, 3.0]) is None and welch_test([], [1.0, 2.0]) is None


def test_identical_repeats_on_both_sides_are_an_exact_comparison() -> None:
    same = welch_test([5.0, 5.0], [5.0, 5.0])
    assert same is not None and same.p == 1.0 and not same.significant
    different = welch_test([5.0, 5.0], [6.0, 6.0])
    assert different is not None and different.p == 0.0 and different.significant


def test_percentiles_interpolate_like_numpy() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(values, 50) == pytest.approx(5.5) and percentile(values, 95) == pytest.approx(9.55)
    assert percentile(values, 0) == 1.0 and percentile(values, 100) == 10.0 and percentile([4.0], 99) == 4.0
    with pytest.raises(ValueError):
        percentile([], 50)
