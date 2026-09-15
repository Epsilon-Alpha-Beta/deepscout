from pathlib import Path
from xml.etree import ElementTree

import pytest

from deepscout.evaluation.power import (
    approximate_paired_power,
    build_power_plan,
    exact_resolution_plan,
    minimum_detectable_dz,
    minimum_units_for_exact_holm,
    required_units_for_power,
)
from deepscout.evaluation.power_report import save_power_plan


def test_exact_holm_resolution_matches_known_core_boundaries():
    old = exact_resolution_plan(6, 5, 0.05)
    assert old.raw_minimum_two_sided_p == pytest.approx(0.03125)
    assert old.worst_case_holm_minimum_p == pytest.approx(0.15625)
    assert old.holm_reachable is False
    assert old.minimum_units_for_holm == 8
    assert minimum_units_for_exact_holm(0.05, 5) == 8

    expanded = exact_resolution_plan(12, 5, 0.05)
    assert expanded.holm_reachable is True
    assert expanded.worst_case_holm_minimum_p < 0.05


def test_approximate_power_and_mde_are_monotonic():
    low_n = approximate_paired_power(8, 0.8, alpha=0.05, family_size=5)
    high_n = approximate_paired_power(24, 0.8, alpha=0.05, family_size=5)
    assert 0.0 < low_n < high_n < 1.0

    mde_12 = minimum_detectable_dz(12, 0.8, alpha=0.05, family_size=5)
    mde_24 = minimum_detectable_dz(24, 0.8, alpha=0.05, family_size=5)
    assert mde_24 < mde_12

    required = required_units_for_power(0.8, 0.8, alpha=0.05, family_size=5)
    assert approximate_paired_power(required, 0.8, alpha=0.05, family_size=5) >= 0.8
    if required > 2:
        assert approximate_paired_power(required - 1, 0.8, alpha=0.05, family_size=5) < 0.8


def test_power_plan_outputs_reports(tmp_path: Path):
    plan = build_power_plan(
        current_units=12,
        family_size=5,
        effect_sizes=(0.5, 0.8),
        paired_std=2.0,
    )
    assert plan.exact_resolution.holm_reachable is True
    assert plan.minimum_detectable_absolute_effect == pytest.approx(
        plan.minimum_detectable_dz_at_current_units * 2.0
    )
    paths = save_power_plan(plan, tmp_path)
    for path in paths.values():
        assert path.exists()
    ElementTree.parse(paths["power_curve_svg"])
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "Approximate paired-normal planning" in markdown
    assert "Bonferroni" in markdown


def test_current_core_corpus_meets_large_effect_planning_target():
    from deepscout.evaluation.ablation import load_ablation_matrix
    from deepscout.evaluation.runner import load_corpus

    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    family_size = len(
        [profile for profile in matrix.profiles if profile.name != matrix.baseline_profile]
    )
    plan = build_power_plan(
        current_units=len(corpus.cases),
        family_size=family_size,
        effect_sizes=(0.8,),
    )
    assert len(corpus.cases) == 20
    assert plan.exact_resolution.holm_reachable is True
    assert plan.minimum_detectable_dz_at_current_units < 0.8
    assert plan.scenarios[0].approximate_power_at_current_units >= 0.8
