import pytest

from deepscout.evaluation.significance import (
    benjamini_hochberg_adjust,
    cliffs_delta,
    cohen_dz,
    holm_adjust,
    paired_sign_flip_test,
    wilcoxon_signed_rank_exact,
)


def test_exact_sign_flip_resolution_and_p_value():
    p_value, method, iterations, minimum = paired_sign_flip_test([1.0] * 5)
    assert method == "exact_sign_flip"
    assert iterations == 32
    assert p_value == pytest.approx(0.0625)
    assert minimum == pytest.approx(0.0625)


def test_wilcoxon_and_paired_effect_sizes():
    statistic, p_value, rank_biserial = wilcoxon_signed_rank_exact([1.0, 2.0, 3.0])
    assert statistic == 0.0
    assert p_value == pytest.approx(0.25)
    assert rank_biserial == 1.0
    assert cohen_dz([1.0, 2.0, 3.0]) == pytest.approx(2.0)
    assert cliffs_delta([2.0, 3.0], [1.0, 1.0]) == 1.0


def test_multiple_comparison_adjustments():
    p_values = [0.01, 0.04, 0.03]
    assert holm_adjust(p_values) == pytest.approx([0.03, 0.06, 0.06])
    assert benjamini_hochberg_adjust(p_values) == pytest.approx([0.03, 0.04, 0.04])


def test_cohen_dz_keeps_zero_differences():
    value = cohen_dz([0.0, 1.0, 2.0])
    assert value is not None
    assert value == pytest.approx(1.0)


def test_six_case_holm_resolution_limit():
    p_value, method, _, minimum = paired_sign_flip_test([1.0] * 6)
    assert method == "exact_sign_flip"
    assert p_value == pytest.approx(0.03125)
    assert minimum == pytest.approx(0.03125)
    adjusted = holm_adjust([minimum] * 5)
    assert adjusted == pytest.approx([0.15625] * 5)


def test_monte_carlo_sign_flip_is_seed_reproducible():
    first = paired_sign_flip_test([1.0, 2.0, 3.0], exact_max_pairs=2, resamples=500, seed=17)
    second = paired_sign_flip_test([1.0, 2.0, 3.0], exact_max_pairs=2, resamples=500, seed=17)
    assert first == second
    assert first[1] == "monte_carlo_sign_flip"
    assert first[2] == 500
