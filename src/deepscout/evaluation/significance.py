"""重复消融实验的配对显著性检验、效应量与多重比较校正。"""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean, stdev
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.power import minimum_units_for_exact_holm
from deepscout.evaluation.repeated import (
    STAT_METRICS,
    RepeatedExperimentReport,
    RepeatedRunRecord,
)
from deepscout.evaluation.statistics import stable_seed

SignificanceScope = Literal["profile_across_cases", "profile_case"]
PermutationMethod = Literal["exact_sign_flip", "monte_carlo_sign_flip", "degenerate"]


class SignificanceComparison(BaseModel):
    scope: SignificanceScope
    profile: str
    baseline: str
    case_id: str | None = None
    metric: str
    paired_count: int = Field(ge=0)
    nonzero_pairs: int = Field(ge=0)
    mean_delta: float
    permutation_p_value: float = Field(ge=0.0, le=1.0)
    permutation_method: PermutationMethod
    permutation_iterations: int = Field(ge=0)
    minimum_attainable_p: float = Field(ge=0.0, le=1.0)
    minimum_reportable_p: float = Field(ge=0.0, le=1.0)
    correction_family_size: int = Field(default=1, ge=1)
    minimum_reportable_holm_p: float = Field(default=1.0, ge=0.0, le=1.0)
    wilcoxon_statistic: float
    wilcoxon_p_value: float = Field(ge=0.0, le=1.0)
    cohen_dz: float | None = None
    matched_rank_biserial: float = Field(ge=-1.0, le=1.0)
    cliffs_delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    holm_adjusted_p: float = Field(default=1.0, ge=0.0, le=1.0)
    bh_adjusted_p: float = Field(default=1.0, ge=0.0, le=1.0)
    significant_holm: bool = False
    significant_bh: bool = False
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


class SignificanceReport(BaseModel):
    matrix_name: str
    matrix_version: str
    corpus_name: str
    corpus_version: str
    repetitions: int = Field(ge=1)
    generated_at: str
    baseline_profile: str
    alpha: float = Field(gt=0.0, lt=1.0)
    exact_permutation_max_pairs: int = Field(ge=1)
    permutation_resamples: int = Field(ge=1)
    permutation_seed: int
    primary_test: str = "paired_sign_flip_permutation"
    secondary_test: str = "wilcoxon_signed_rank_exact_dp"
    multiple_correction: str = "Holm-Bonferroni + Benjamini-Hochberg on primary p-values"
    correction_family: str = "same scope + case + metric across non-baseline profiles"
    minimum_nonzero_pairs_for_holm: int = Field(ge=1)
    comparisons: list[SignificanceComparison]


def _nonzero(values: list[float], *, tol: float = 1e-12) -> list[float]:
    return [value for value in values if not math.isclose(value, 0.0, abs_tol=tol)]


def paired_sign_flip_test(
    differences: list[float],
    *,
    exact_max_pairs: int = 16,
    resamples: int = 20000,
    seed: int = 20260915,
) -> tuple[float, PermutationMethod, int, float]:
    """Two-sided paired randomization test via sign flips of non-zero differences."""
    values = _nonzero(differences)
    n = len(values)
    if n == 0:
        return 1.0, "degenerate", 0, 1.0

    observed = abs(sum(values))
    min_p = min(1.0, 2.0 / (2**n))
    magnitudes = [abs(value) for value in values]
    if n <= exact_max_pairs:
        extreme = 0
        total = 2**n
        for signs in itertools.product((-1.0, 1.0), repeat=n):
            statistic = abs(
                sum(sign * value for sign, value in zip(signs, magnitudes, strict=True))
            )
            if statistic >= observed - 1e-12:
                extreme += 1
        return extreme / total, "exact_sign_flip", total, min_p

    rng = random.Random(seed)
    extreme = 0
    for _ in range(resamples):
        statistic = abs(sum((1.0 if rng.random() >= 0.5 else -1.0) * value for value in magnitudes))
        if statistic >= observed - 1e-12:
            extreme += 1
    return (extreme + 1) / (resamples + 1), "monte_carlo_sign_flip", resamples, min_p


def _average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and math.isclose(
            indexed[end][1], indexed[start][1], rel_tol=1e-12, abs_tol=1e-12
        ):
            end += 1
        average = ((start + 1) + end) / 2.0
        for index in range(start, end):
            ranks[indexed[index][0]] = average
        start = end
    return ranks


def wilcoxon_signed_rank_exact(differences: list[float]) -> tuple[float, float, float]:
    """Exact two-sided signed-rank p-value using dynamic programming over midranks."""
    values = _nonzero(differences)
    if not values:
        return 0.0, 1.0, 0.0
    ranks = _average_ranks([abs(value) for value in values])
    scaled = [int(round(rank * 2.0)) for rank in ranks]
    positive = sum(rank for rank, value in zip(scaled, values, strict=True) if value > 0)
    total_rank = sum(scaled)
    statistic = min(positive, total_rank - positive) / 2.0
    observed_distance = abs(2 * positive - total_rank)

    distribution: dict[int, int] = {0: 1}
    for rank in scaled:
        updated = dict(distribution)
        for subtotal, count in distribution.items():
            updated[subtotal + rank] = updated.get(subtotal + rank, 0) + count
        distribution = updated
    extreme = sum(
        count
        for subtotal, count in distribution.items()
        if abs(2 * subtotal - total_rank) >= observed_distance
    )
    p_value = extreme / (2 ** len(values))
    rank_biserial = (2 * positive - total_rank) / total_rank if total_rank else 0.0
    return statistic, p_value, rank_biserial


def cohen_dz(differences: list[float]) -> float | None:
    values = list(differences)
    if not values:
        return 0.0
    if len(values) < 2:
        return None
    sigma = stdev(values)
    mean = fmean(values)
    if math.isclose(sigma, 0.0, abs_tol=1e-15):
        return 0.0 if math.isclose(mean, 0.0, abs_tol=1e-15) else None
    return mean / sigma


def cliffs_delta(current: list[float], baseline: list[float]) -> float | None:
    """Supplementary unpaired effect size; pairing is intentionally ignored here."""
    if not current or not baseline:
        return None
    greater = 0
    less = 0
    for left in current:
        for right in baseline:
            if left > right:
                greater += 1
            elif left < right:
                less += 1
    return (greater - less) / (len(current) * len(baseline))


def holm_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=p_values.__getitem__)
    adjusted = [1.0] * count
    running = 0.0
    for rank, index in enumerate(order):
        candidate = min(1.0, (count - rank) * p_values[index])
        running = max(running, candidate)
        adjusted[index] = running
    return adjusted


def benjamini_hochberg_adjust(p_values: list[float]) -> list[float]:
    count = len(p_values)
    order = sorted(range(count), key=p_values.__getitem__)
    adjusted = [1.0] * count
    running = 1.0
    for reverse_rank in range(count - 1, -1, -1):
        index = order[reverse_rank]
        rank = reverse_rank + 1
        running = min(running, p_values[index] * count / rank)
        adjusted[index] = min(1.0, running)
    return adjusted


def _metric_value(record: RepeatedRunRecord, metric: str) -> float | None:
    value = getattr(record.result.metrics, metric)
    return None if value is None else float(value)


def _completed_index(
    records: list[RepeatedRunRecord], profile: str
) -> dict[tuple[int, str], RepeatedRunRecord]:
    return {
        (record.repetition, record.result.case.case_id): record
        for record in records
        if record.profile == profile and record.result.status == "completed"
    }


def _paired_values(
    report: RepeatedExperimentReport,
    profile: str,
    metric: str,
    case_id: str | None = None,
) -> tuple[list[float], list[float], list[float]]:
    current_index = _completed_index(report.runs, profile)
    baseline_index = _completed_index(report.runs, report.baseline_profile)
    current: list[float] = []
    baseline: list[float] = []
    differences: list[float] = []
    for key in sorted(set(current_index).intersection(baseline_index)):
        if case_id is not None and key[1] != case_id:
            continue
        left = _metric_value(current_index[key], metric)
        right = _metric_value(baseline_index[key], metric)
        if left is None or right is None:
            continue
        current.append(left)
        baseline.append(right)
        differences.append(left - right)
    return current, baseline, differences


def _case_mean_pairs(
    report: RepeatedExperimentReport,
    profile: str,
    metric: str,
) -> tuple[list[float], list[float], list[float]]:
    current: list[float] = []
    baseline: list[float] = []
    differences: list[float] = []
    case_ids = sorted({record.result.case.case_id for record in report.runs})
    for case_id in case_ids:
        left, right, paired = _paired_values(report, profile, metric, case_id)
        if not paired:
            continue
        left_mean = fmean(left)
        right_mean = fmean(right)
        current.append(left_mean)
        baseline.append(right_mean)
        differences.append(fmean(paired))
    return current, baseline, differences


def build_paired_comparison(
    *,
    scope: SignificanceScope,
    profile: str,
    baseline_profile: str,
    case_id: str | None,
    metric: str,
    current: list[float],
    baseline: list[float],
    differences: list[float],
    alpha: float,
    exact_max_pairs: int,
    permutation_resamples: int,
    permutation_seed: int,
) -> SignificanceComparison:
    seed = stable_seed(permutation_seed, scope, profile, case_id or "all", metric)
    p_value, method, iterations, minimum = paired_sign_flip_test(
        differences,
        exact_max_pairs=exact_max_pairs,
        resamples=permutation_resamples,
        seed=seed,
    )
    wilcoxon_stat, wilcoxon_p, rank_biserial = wilcoxon_signed_rank_exact(differences)
    return SignificanceComparison(
        scope=scope,
        profile=profile,
        baseline=baseline_profile,
        case_id=case_id,
        metric=metric,
        paired_count=len(differences),
        nonzero_pairs=len(_nonzero(differences)),
        mean_delta=fmean(differences) if differences else 0.0,
        permutation_p_value=p_value,
        permutation_method=method,
        permutation_iterations=iterations,
        minimum_attainable_p=minimum,
        minimum_reportable_p=(
            minimum if method != "monte_carlo_sign_flip" else max(minimum, 1.0 / (iterations + 1))
        ),
        wilcoxon_statistic=wilcoxon_stat,
        wilcoxon_p_value=wilcoxon_p,
        cohen_dz=cohen_dz(differences),
        matched_rank_biserial=rank_biserial,
        cliffs_delta=cliffs_delta(current, baseline),
        alpha=alpha,
    )


def apply_multiple_corrections(
    comparisons: list[SignificanceComparison],
    *,
    alpha: float,
) -> None:
    families: dict[tuple[str, str | None, str], list[SignificanceComparison]] = defaultdict(list)
    for comparison in comparisons:
        key = (comparison.scope, comparison.case_id, comparison.metric)
        families[key].append(comparison)

    for family in families.values():
        family_size = len(family)
        p_values = [item.permutation_p_value for item in family]
        holm = holm_adjust(p_values)
        bh = benjamini_hochberg_adjust(p_values)
        for item, holm_p, bh_p in zip(family, holm, bh, strict=True):
            item.correction_family_size = family_size
            item.minimum_reportable_holm_p = min(1.0, family_size * item.minimum_reportable_p)
            item.holm_adjusted_p = holm_p
            item.bh_adjusted_p = bh_p
            item.significant_holm = holm_p <= alpha
            item.significant_bh = bh_p <= alpha


def build_significance_report(
    report: RepeatedExperimentReport,
    *,
    alpha: float = 0.05,
    exact_permutation_max_pairs: int = 16,
    permutation_resamples: int = 20000,
    permutation_seed: int = 20260915,
) -> SignificanceReport:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha 必须位于 (0, 1)。")
    if exact_permutation_max_pairs < 1:
        raise ValueError("exact_permutation_max_pairs 必须 >= 1。")
    if permutation_resamples < 1:
        raise ValueError("permutation_resamples 必须 >= 1。")

    profiles = sorted({record.profile for record in report.runs})
    profiles = [profile for profile in profiles if profile != report.baseline_profile]
    case_ids = sorted({record.result.case.case_id for record in report.runs})
    available_metrics = [
        metric
        for metric in STAT_METRICS
        if any(
            record.result.status == "completed" and _metric_value(record, metric) is not None
            for record in report.runs
        )
    ]
    comparisons: list[SignificanceComparison] = []
    for profile in profiles:
        for metric in available_metrics:
            current, baseline, differences = _case_mean_pairs(report, profile, metric)
            comparisons.append(
                build_paired_comparison(
                    scope="profile_across_cases",
                    profile=profile,
                    baseline_profile=report.baseline_profile,
                    case_id=None,
                    metric=metric,
                    current=current,
                    baseline=baseline,
                    differences=differences,
                    alpha=alpha,
                    exact_max_pairs=exact_permutation_max_pairs,
                    permutation_resamples=permutation_resamples,
                    permutation_seed=permutation_seed,
                )
            )
        for case_id in case_ids:
            for metric in available_metrics:
                current, baseline, differences = _paired_values(report, profile, metric, case_id)
                comparisons.append(
                    build_paired_comparison(
                        scope="profile_case",
                        profile=profile,
                        baseline_profile=report.baseline_profile,
                        case_id=case_id,
                        metric=metric,
                        current=current,
                        baseline=baseline,
                        differences=differences,
                        alpha=alpha,
                        exact_max_pairs=exact_permutation_max_pairs,
                        permutation_resamples=permutation_resamples,
                        permutation_seed=permutation_seed,
                    )
                )

    apply_multiple_corrections(comparisons, alpha=alpha)
    family_size = max(1, len(profiles))
    minimum_pairs = minimum_units_for_exact_holm(alpha, family_size)
    return SignificanceReport(
        matrix_name=report.matrix_name,
        matrix_version=report.matrix_version,
        corpus_name=report.corpus_name,
        corpus_version=report.corpus_version,
        repetitions=report.repetitions,
        generated_at=datetime.now(UTC).isoformat(),
        baseline_profile=report.baseline_profile,
        alpha=alpha,
        exact_permutation_max_pairs=exact_permutation_max_pairs,
        permutation_resamples=permutation_resamples,
        permutation_seed=permutation_seed,
        minimum_nonzero_pairs_for_holm=minimum_pairs,
        comparisons=comparisons,
    )
