"""重复 Ablation 实验执行、配对差分与统计聚合。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from deepscout.config import settings_override
from deepscout.evaluation.ablation import AblationMatrix, AblationProfile
from deepscout.evaluation.models import BenchmarkCorpus, BenchmarkPricing, BenchmarkRunResult
from deepscout.evaluation.runner import run_case
from deepscout.evaluation.statistics import (
    DistributionStatistics,
    stable_seed,
    summarize_distribution,
)

OrderStrategy = Literal["fixed", "rotate"]

STAT_METRICS = (
    "quality_proxy_score",
    "citation_coverage",
    "source_diversity_ratio",
    "task_success_rate",
    "replan_count",
    "evidence_count",
    "search_calls",
    "research_tokens",
    "worker_seconds",
    "wall_seconds",
    "unsupported_claims",
    "estimated_tracked_cost_usd",
)


class RepeatedRunRecord(BaseModel):
    """一个 profile/case 在某次 repetition 中的原始运行记录。"""

    repetition: int = Field(ge=1)
    execution_order: int = Field(ge=0)
    profile_order: int = Field(ge=0)
    profile: str = Field(min_length=1)
    result: BenchmarkRunResult


class RepeatedScopeStatistics(BaseModel):
    """profile 或 profile/case 范围内的统计汇总。"""

    scope: Literal["profile", "profile_case", "profile_delta", "profile_case_delta"]
    profile: str = Field(min_length=1)
    baseline: str | None = None
    case_id: str | None = None
    attempted_units: int = Field(ge=0)
    completed_units: int = Field(ge=0)
    error_units: int = Field(ge=0)
    interrupted_units: int = Field(ge=0)
    completion_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    overall_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    metrics: dict[str, DistributionStatistics] = Field(default_factory=dict)


class RepeatedExperimentReport(BaseModel):
    matrix_name: str
    matrix_version: str
    corpus_name: str
    corpus_version: str
    baseline_profile: str
    repetitions: int = Field(ge=1)
    order_strategy: OrderStrategy
    bootstrap_resamples: int = Field(ge=1)
    confidence_level: float = Field(gt=0.0, lt=1.0)
    bootstrap_seed: int
    ci_method: str = "percentile_bootstrap_mean"
    generated_at: str
    runs: list[RepeatedRunRecord]
    profile_case_statistics: list[RepeatedScopeStatistics]
    profile_statistics: list[RepeatedScopeStatistics]
    profile_case_delta_statistics: list[RepeatedScopeStatistics]
    profile_delta_statistics: list[RepeatedScopeStatistics]


def _metric_value(result: BenchmarkRunResult, metric: str) -> float | None:
    value = getattr(result.metrics, metric)
    return None if value is None else float(value)


def _profile_order(profiles: list[AblationProfile], repetition: int, strategy: OrderStrategy):
    if strategy == "fixed" or len(profiles) <= 1:
        return list(profiles)
    offset = (repetition - 1) % len(profiles)
    return profiles[offset:] + profiles[:offset]


def _summarize_metric(
    values: list[float],
    *,
    seed: int,
    confidence_level: float,
    resamples: int,
    seed_parts: tuple[str, ...],
) -> DistributionStatistics:
    return summarize_distribution(
        values,
        confidence_level=confidence_level,
        resamples=resamples,
        seed=stable_seed(seed, *seed_parts),
    )


def _completed_results(records: list[RepeatedRunRecord]) -> list[BenchmarkRunResult]:
    return [record.result for record in records if record.result.status == "completed"]


def _scope_counts(records: list[RepeatedRunRecord]) -> dict[str, int | float]:
    attempted = len(records)
    completed = sum(record.result.status == "completed" for record in records)
    errors = sum(record.result.status == "error" for record in records)
    interrupted = sum(record.result.status == "interrupted" for record in records)
    passed = sum(record.result.passed for record in records)
    return {
        "attempted_units": attempted,
        "completed_units": completed,
        "error_units": errors,
        "interrupted_units": interrupted,
        "completion_rate": completed / attempted if attempted else None,
        "overall_pass_rate": passed / attempted if attempted else None,
    }


def _build_scope_statistics(
    records: list[RepeatedRunRecord],
    *,
    scope: Literal["profile", "profile_case"],
    profile: str,
    case_id: str | None,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> RepeatedScopeStatistics:
    completed = _completed_results(records)
    metrics: dict[str, DistributionStatistics] = {}
    for metric in STAT_METRICS:
        values = [
            value for result in completed if (value := _metric_value(result, metric)) is not None
        ]
        if not values:
            continue
        metrics[metric] = _summarize_metric(
            values,
            seed=seed,
            confidence_level=confidence_level,
            resamples=resamples,
            seed_parts=(scope, profile, case_id or "all", metric),
        )
    return RepeatedScopeStatistics(
        scope=scope,
        profile=profile,
        case_id=case_id,
        metrics=metrics,
        **_scope_counts(records),
    )


def _paired_delta_values(
    profile_records: list[RepeatedRunRecord],
    baseline_records: list[RepeatedRunRecord],
    metric: str,
) -> list[float]:
    baseline_index = {
        (record.repetition, record.result.case.case_id): record for record in baseline_records
    }
    values: list[float] = []
    for record in profile_records:
        base = baseline_index.get((record.repetition, record.result.case.case_id))
        if base is None:
            continue
        if record.result.status != "completed" or base.result.status != "completed":
            continue
        current = _metric_value(record.result, metric)
        baseline = _metric_value(base.result, metric)
        if current is not None and baseline is not None:
            values.append(current - baseline)
    return values


def _build_delta_statistics(
    profile_records: list[RepeatedRunRecord],
    baseline_records: list[RepeatedRunRecord],
    *,
    scope: Literal["profile_delta", "profile_case_delta"],
    profile: str,
    baseline: str,
    case_id: str | None,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> RepeatedScopeStatistics:
    baseline_index = {
        (record.repetition, record.result.case.case_id): record for record in baseline_records
    }
    pairs = [
        (record, baseline_index[(record.repetition, record.result.case.case_id)])
        for record in profile_records
        if (record.repetition, record.result.case.case_id) in baseline_index
    ]
    completed = sum(
        current.result.status == "completed" and base.result.status == "completed"
        for current, base in pairs
    )
    errors = sum(
        current.result.status == "error" or base.result.status == "error" for current, base in pairs
    )
    interrupted = sum(
        current.result.status == "interrupted" or base.result.status == "interrupted"
        for current, base in pairs
    )
    metrics: dict[str, DistributionStatistics] = {}
    for metric in STAT_METRICS:
        values = _paired_delta_values(profile_records, baseline_records, metric)
        if values:
            metrics[metric] = _summarize_metric(
                values,
                seed=seed,
                confidence_level=confidence_level,
                resamples=resamples,
                seed_parts=(scope, profile, case_id or "all", metric),
            )
    attempted = len(pairs)
    return RepeatedScopeStatistics(
        scope=scope,
        profile=profile,
        baseline=baseline,
        case_id=case_id,
        attempted_units=attempted,
        completed_units=completed,
        error_units=errors,
        interrupted_units=interrupted,
        completion_rate=completed / attempted if attempted else None,
        overall_pass_rate=None,
        metrics=metrics,
    )


def build_repeated_report(
    corpus: BenchmarkCorpus,
    matrix: AblationMatrix,
    runs: list[RepeatedRunRecord],
    *,
    repetitions: int,
    order_strategy: OrderStrategy,
    bootstrap_resamples: int,
    confidence_level: float,
    bootstrap_seed: int,
) -> RepeatedExperimentReport:
    """从原始重复 run 构建 profile/case 和配对 baseline delta 统计。"""
    profile_case_stats: list[RepeatedScopeStatistics] = []
    profile_stats: list[RepeatedScopeStatistics] = []
    delta_case_stats: list[RepeatedScopeStatistics] = []
    delta_profile_stats: list[RepeatedScopeStatistics] = []

    baseline_records = [record for record in runs if record.profile == matrix.baseline_profile]
    for profile in matrix.profiles:
        profile_records = [record for record in runs if record.profile == profile.name]
        profile_stats.append(
            _build_scope_statistics(
                profile_records,
                scope="profile",
                profile=profile.name,
                case_id=None,
                confidence_level=confidence_level,
                resamples=bootstrap_resamples,
                seed=bootstrap_seed,
            )
        )
        delta_profile_stats.append(
            _build_delta_statistics(
                profile_records,
                baseline_records,
                scope="profile_delta",
                profile=profile.name,
                baseline=matrix.baseline_profile,
                case_id=None,
                confidence_level=confidence_level,
                resamples=bootstrap_resamples,
                seed=bootstrap_seed,
            )
        )
        case_ids = sorted({record.result.case.case_id for record in profile_records})
        for case_id in case_ids:
            case_records = [
                record for record in profile_records if record.result.case.case_id == case_id
            ]
            base_case_records = [
                record for record in baseline_records if record.result.case.case_id == case_id
            ]
            profile_case_stats.append(
                _build_scope_statistics(
                    case_records,
                    scope="profile_case",
                    profile=profile.name,
                    case_id=case_id,
                    confidence_level=confidence_level,
                    resamples=bootstrap_resamples,
                    seed=bootstrap_seed,
                )
            )
            delta_case_stats.append(
                _build_delta_statistics(
                    case_records,
                    base_case_records,
                    scope="profile_case_delta",
                    profile=profile.name,
                    baseline=matrix.baseline_profile,
                    case_id=case_id,
                    confidence_level=confidence_level,
                    resamples=bootstrap_resamples,
                    seed=bootstrap_seed,
                )
            )
    return RepeatedExperimentReport(
        matrix_name=matrix.name,
        matrix_version=matrix.version,
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        baseline_profile=matrix.baseline_profile,
        repetitions=repetitions,
        order_strategy=order_strategy,
        bootstrap_resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        bootstrap_seed=bootstrap_seed,
        generated_at=datetime.now(UTC).isoformat(),
        runs=runs,
        profile_case_statistics=profile_case_stats,
        profile_statistics=profile_stats,
        profile_case_delta_statistics=delta_case_stats,
        profile_delta_statistics=delta_profile_stats,
    )


async def run_repeated_ablation(
    corpus: BenchmarkCorpus,
    matrix: AblationMatrix,
    *,
    repetitions: int = 5,
    order_strategy: OrderStrategy = "rotate",
    bootstrap_resamples: int = 2000,
    confidence_level: float = 0.95,
    bootstrap_seed: int = 20260915,
    graph_factory: Any = None,
    limit: int | None = None,
    pricing: BenchmarkPricing | None = None,
) -> RepeatedExperimentReport:
    """按 repetition-major 顺序执行 profile/case，并构建重复实验统计。"""
    if repetitions < 1:
        raise ValueError("repetitions 必须 >= 1。")
    if bootstrap_resamples < 1:
        raise ValueError("bootstrap_resamples 必须 >= 1。")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence_level 必须位于 (0, 1)。")
    if graph_factory is None:
        from deepscout.graph.builder import build_graph

        graph_factory = build_graph

    cases = corpus.cases[:limit] if limit is not None else corpus.cases
    runs: list[RepeatedRunRecord] = []
    execution_order = 0
    for repetition in range(1, repetitions + 1):
        ordered_profiles = _profile_order(matrix.profiles, repetition, order_strategy)
        for profile_order, profile in enumerate(ordered_profiles):
            with settings_override(profile.settings.as_overrides()):
                graph = graph_factory(options=profile.graph.to_graph_options())
                for case in cases:
                    result = await run_case(graph, case, pricing)
                    runs.append(
                        RepeatedRunRecord(
                            repetition=repetition,
                            execution_order=execution_order,
                            profile_order=profile_order,
                            profile=profile.name,
                            result=result,
                        )
                    )
                    execution_order += 1

    return build_repeated_report(
        corpus,
        matrix,
        runs,
        repetitions=repetitions,
        order_strategy=order_strategy,
        bootstrap_resamples=bootstrap_resamples,
        confidence_level=confidence_level,
        bootstrap_seed=bootstrap_seed,
    )
