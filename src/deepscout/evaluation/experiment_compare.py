"""Experiment Bundle 跨批次兼容性与 regression comparison。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from deepscout.evaluation.experiment_bundle import (
    ExperimentBundleManifest,
    artifact_path,
    load_bundle_manifest,
    validate_experiment_bundle,
)
from deepscout.evaluation.quality_aggregate import RuntimeQualityAggregateReport
from deepscout.evaluation.repeated import RepeatedExperimentReport

Direction = Literal["higher_is_better", "lower_is_better"]
MetricStatus = Literal["improved", "stable", "regression"]


class MetricRule(BaseModel):
    metric: str
    direction: Direction
    absolute_threshold: float = Field(ge=0.0)
    relative_threshold: float = Field(ge=0.0)


class MetricComparison(BaseModel):
    source: Literal["repeated", "quality"]
    profile: str
    metric: str
    direction: Direction
    before: float
    after: float
    delta: float
    relative_change: float | None = None
    absolute_threshold: float = Field(ge=0.0)
    relative_threshold: float = Field(ge=0.0)
    effective_threshold: float = Field(ge=0.0)
    status: MetricStatus


class ExperimentComparisonReport(BaseModel):
    comparable: bool
    baseline_experiment_id: str
    candidate_experiment_id: str
    incompatibilities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    comparisons: list[MetricComparison] = Field(default_factory=list)
    regression_count: int = Field(ge=0)
    improvement_count: int = Field(ge=0)


DEFAULT_RULES = (
    MetricRule(
        metric="quality_proxy_score",
        direction="higher_is_better",
        absolute_threshold=0.02,
        relative_threshold=0.05,
    ),
    MetricRule(
        metric="citation_coverage",
        direction="higher_is_better",
        absolute_threshold=0.02,
        relative_threshold=0.05,
    ),
    MetricRule(
        metric="source_diversity_ratio",
        direction="higher_is_better",
        absolute_threshold=0.02,
        relative_threshold=0.05,
    ),
    MetricRule(
        metric="search_calls",
        direction="lower_is_better",
        absolute_threshold=1.0,
        relative_threshold=0.10,
    ),
    MetricRule(
        metric="research_tokens",
        direction="lower_is_better",
        absolute_threshold=100.0,
        relative_threshold=0.10,
    ),
    MetricRule(
        metric="worker_seconds",
        direction="lower_is_better",
        absolute_threshold=0.10,
        relative_threshold=0.10,
    ),
    MetricRule(
        metric="wall_seconds",
        direction="lower_is_better",
        absolute_threshold=0.10,
        relative_threshold=0.10,
    ),
    MetricRule(
        metric="estimated_tracked_cost_usd",
        direction="lower_is_better",
        absolute_threshold=0.01,
        relative_threshold=0.10,
    ),
    MetricRule(
        metric="source_compliance_rate",
        direction="higher_is_better",
        absolute_threshold=0.02,
        relative_threshold=0.05,
    ),
    MetricRule(
        metric="human_gold_score",
        direction="higher_is_better",
        absolute_threshold=0.03,
        relative_threshold=0.05,
    ),
    MetricRule(
        metric="human_gold_pass_rate",
        direction="higher_is_better",
        absolute_threshold=0.05,
        relative_threshold=0.10,
    ),
)


def _compatibility(
    baseline: ExperimentBundleManifest, candidate: ExperimentBundleManifest
) -> tuple[list[str], list[str]]:
    left, right = baseline.identity, candidate.identity
    incompatible: list[str] = []
    for field in (
        "corpus_name",
        "corpus_version",
        "matrix_name",
        "matrix_version",
        "baseline_profile",
    ):
        if getattr(left, field) != getattr(right, field):
            incompatible.append(f"{field}: {getattr(left, field)!r} != {getattr(right, field)!r}")
    if left.profiles != right.profiles:
        incompatible.append(f"profiles: {left.profiles!r} != {right.profiles!r}")
    warnings: list[str] = []
    if left.repetitions != right.repetitions:
        warnings.append(f"repetitions differ: {left.repetitions} -> {right.repetitions}")
    if baseline.provider != candidate.provider:
        warnings.append(f"provider differs: {baseline.provider!r} -> {candidate.provider!r}")
    if baseline.model != candidate.model:
        warnings.append(f"model differs: {baseline.model!r} -> {candidate.model!r}")
    if baseline.git_dirty:
        warnings.append("baseline bundle came from a dirty worktree")
    if candidate.git_dirty:
        warnings.append("candidate bundle came from a dirty worktree")
    return incompatible, warnings


def _load_repeated(bundle: Path, manifest: ExperimentBundleManifest) -> RepeatedExperimentReport:
    return RepeatedExperimentReport.model_validate_json(
        artifact_path(bundle, manifest, "repeated").read_text(encoding="utf-8")
    )


def _load_quality(
    bundle: Path, manifest: ExperimentBundleManifest
) -> RuntimeQualityAggregateReport | None:
    if not any(item.role == "quality_aggregate" for item in manifest.artifacts):
        return None
    return RuntimeQualityAggregateReport.model_validate_json(
        artifact_path(bundle, manifest, "quality_aggregate").read_text(encoding="utf-8")
    )


def _classify(
    before: float, after: float, rule: MetricRule
) -> tuple[MetricStatus, float, float | None]:
    delta = after - before
    relative = delta / abs(before) if abs(before) > 1e-12 else None
    threshold = max(rule.absolute_threshold, abs(before) * rule.relative_threshold)
    signed_improvement = delta if rule.direction == "higher_is_better" else -delta
    if signed_improvement > threshold:
        status: MetricStatus = "improved"
    elif signed_improvement < -threshold:
        status = "regression"
    else:
        status = "stable"
    return status, threshold, relative


def _append_comparison(
    rows: list[MetricComparison],
    *,
    source: Literal["repeated", "quality"],
    profile: str,
    rule: MetricRule,
    before: float,
    after: float,
) -> None:
    status, threshold, relative = _classify(before, after, rule)
    rows.append(
        MetricComparison(
            source=source,
            profile=profile,
            metric=rule.metric,
            direction=rule.direction,
            before=before,
            after=after,
            delta=after - before,
            relative_change=relative,
            absolute_threshold=rule.absolute_threshold,
            relative_threshold=rule.relative_threshold,
            effective_threshold=threshold,
            status=status,
        )
    )


def compare_experiment_bundles(
    baseline_dir: str | Path, candidate_dir: str | Path, *, rules: list[MetricRule] | None = None
) -> ExperimentComparisonReport:
    baseline_path, candidate_path = Path(baseline_dir), Path(candidate_dir)
    baseline_validation = validate_experiment_bundle(baseline_path)
    candidate_validation = validate_experiment_bundle(candidate_path)
    if not baseline_validation.valid or not candidate_validation.valid:
        errors = [
            *(f"baseline bundle: {item}" for item in baseline_validation.errors),
            *(f"candidate bundle: {item}" for item in candidate_validation.errors),
        ]
        baseline_manifest = load_bundle_manifest(baseline_path)
        candidate_manifest = load_bundle_manifest(candidate_path)
        return ExperimentComparisonReport(
            comparable=False,
            baseline_experiment_id=baseline_manifest.experiment_id,
            candidate_experiment_id=candidate_manifest.experiment_id,
            incompatibilities=errors,
            regression_count=0,
            improvement_count=0,
        )

    baseline_manifest = load_bundle_manifest(baseline_path)
    candidate_manifest = load_bundle_manifest(candidate_path)
    incompatible, warnings = _compatibility(baseline_manifest, candidate_manifest)
    if incompatible:
        return ExperimentComparisonReport(
            comparable=False,
            baseline_experiment_id=baseline_manifest.experiment_id,
            candidate_experiment_id=candidate_manifest.experiment_id,
            incompatibilities=incompatible,
            warnings=warnings,
            regression_count=0,
            improvement_count=0,
        )

    rule_map = {item.metric: item for item in (rules or list(DEFAULT_RULES))}
    rows: list[MetricComparison] = []
    left_repeated = _load_repeated(baseline_path, baseline_manifest)
    right_repeated = _load_repeated(candidate_path, candidate_manifest)
    left_profiles = {item.profile: item for item in left_repeated.profile_statistics}
    right_profiles = {item.profile: item for item in right_repeated.profile_statistics}
    for profile in baseline_manifest.identity.profiles:
        left_scope, right_scope = left_profiles.get(profile), right_profiles.get(profile)
        if left_scope is None or right_scope is None:
            warnings.append(f"missing repeated profile statistics: {profile}")
            continue
        for metric, rule in rule_map.items():
            if metric not in left_scope.metrics or metric not in right_scope.metrics:
                continue
            _append_comparison(
                rows,
                source="repeated",
                profile=profile,
                rule=rule,
                before=left_scope.metrics[metric].mean,
                after=right_scope.metrics[metric].mean,
            )

    left_quality = _load_quality(baseline_path, baseline_manifest)
    right_quality = _load_quality(candidate_path, candidate_manifest)
    if (left_quality is None) != (right_quality is None):
        warnings.append("quality_aggregate is present in only one bundle; quality metrics skipped")
    elif left_quality is not None and right_quality is not None:
        left_q = {item.profile: item for item in left_quality.profile_statistics}
        right_q = {item.profile: item for item in right_quality.profile_statistics}
        for profile in baseline_manifest.identity.profiles:
            left_scope, right_scope = left_q.get(profile), right_q.get(profile)
            if left_scope is None or right_scope is None:
                continue
            rate_values = {
                "source_compliance_rate": (
                    left_scope.source_compliance_rate,
                    right_scope.source_compliance_rate,
                ),
                "human_gold_pass_rate": (
                    left_scope.human_gold_pass_rate,
                    right_scope.human_gold_pass_rate,
                ),
            }
            for metric, (before, after) in rate_values.items():
                if metric in rule_map and before is not None and after is not None:
                    _append_comparison(
                        rows,
                        source="quality",
                        profile=profile,
                        rule=rule_map[metric],
                        before=before,
                        after=after,
                    )
            metric = "human_gold_score"
            if (
                metric in rule_map
                and metric in left_scope.metrics
                and metric in right_scope.metrics
            ):
                _append_comparison(
                    rows,
                    source="quality",
                    profile=profile,
                    rule=rule_map[metric],
                    before=left_scope.metrics[metric].mean,
                    after=right_scope.metrics[metric].mean,
                )

    return ExperimentComparisonReport(
        comparable=True,
        baseline_experiment_id=baseline_manifest.experiment_id,
        candidate_experiment_id=candidate_manifest.experiment_id,
        warnings=warnings,
        comparisons=rows,
        regression_count=sum(item.status == "regression" for item in rows),
        improvement_count=sum(item.status == "improved" for item in rows),
    )
