import math

import pytest

from deepscout.evaluation.statistics import (
    bootstrap_mean_ci,
    percentile,
    stable_seed,
    summarize_distribution,
)


def test_percentile_uses_linear_interpolation():
    values = [1, 2, 3, 4, 5]
    assert percentile(values, 0.50) == 3.0
    assert percentile(values, 0.95) == pytest.approx(4.8)


def test_distribution_statistics_are_deterministic():
    values = [1, 2, 3, 4, 5]
    first = summarize_distribution(values, resamples=500, seed=42)
    second = summarize_distribution(values, resamples=500, seed=42)
    assert first == second
    assert first.count == 5
    assert first.mean == 3.0
    assert first.std == pytest.approx(math.sqrt(2.5))
    assert first.median == 3.0
    assert first.p50 == 3.0
    assert first.p95 == pytest.approx(4.8)
    assert first.ci_low <= first.mean <= first.ci_high


def test_single_sample_bootstrap_collapses_interval():
    low, high = bootstrap_mean_ci([7.5], resamples=100, seed=7)
    assert low == 7.5
    assert high == 7.5


def test_stable_seed_changes_with_scope():
    a = stable_seed(123, "profile", "full", "quality")
    b = stable_seed(123, "profile", "full", "quality")
    c = stable_seed(123, "profile", "low-budget", "quality")
    assert a == b
    assert a != c
