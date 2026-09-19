"""运行后质量 sidecar 聚合：来源合规、人工 gold、agreement 与配对差分。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from statistics import fmean
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from deepscout.evaluation.human_review import (
    AgreementReport,
    EvaluatedHumanReview,
    calculate_inter_rater_agreement,
)
from deepscout.evaluation.power import minimum_units_for_exact_holm
from deepscout.evaluation.repeated import RepeatedExperimentReport
from deepscout.evaluation.review_audit import HumanReviewAuditReport
from deepscout.evaluation.significance import (
    SignificanceReport,
    apply_multiple_corrections,
    build_paired_comparison,
)
from deepscout.evaluation.source_compliance import SourcePolicyComplianceReport
from deepscout.evaluation.statistics import (
    DistributionStatistics,
    stable_seed,
    summarize_distribution,
)

QualityScope = Literal["profile", "profile_case"]
QualityDeltaScope = Literal["profile_delta", "profile_case_delta"]
QUALITY_METRICS = (
    "source_policy_pass",
    "human_gold_score",
    "human_gold_pass",
    "freshness_metadata_coverage",
)


class BlindReviewAssignment(BaseModel):
    """私有 sidecar：blind item 到真实实验单元的映射，不交给 reviewer。"""

    blind_item_id: str = Field(min_length=1)
    repetition: int = Field(ge=1)
    profile: str = Field(min_length=1)
    case_id: str = Field(min_length=1)


class SourceQualityObservation(BaseModel):
    """某个 profile/repetition/case 的来源合规 sidecar。"""

    repetition: int = Field(ge=1)
    profile: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    report: SourcePolicyComplianceReport

    @model_validator(mode="after")
    def validate_case_id(self) -> SourceQualityObservation:
        if self.case_id != self.report.case_id:
            raise ValueError("source observation case_id 与 report.case_id 不一致。")
        return self


class RuntimeQualityObservation(BaseModel):
    repetition: int = Field(ge=1)
    run_status: Literal["completed", "interrupted", "error", "not_run"]
    profile: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    source_policy_observed: bool = False
    source_policy_evaluable: bool | None = None
    source_policy_passed: bool | None = None
    freshness_metadata_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    blind_item_id: str | None = None
    human_review_resolved: bool | None = None
    human_gold_score: float | None = Field(default=None, ge=0.0, le=1.0)
    human_gold_passed: bool | None = None
    reviewer_pass_agreement: bool | None = None
    reviewer_score_gap: float | None = Field(default=None, ge=0.0)


class QualityScopeStatistics(BaseModel):
    scope: QualityScope
    profile: str = Field(min_length=1)
    case_id: str | None = None
    completed_run_count: int = Field(ge=0)
    source_observation_count: int = Field(ge=0)
    source_evaluable_count: int = Field(ge=0)
    source_unverifiable_count: int = Field(ge=0)
    source_observation_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    source_evaluable_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    source_compliance_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    human_assignment_count: int = Field(ge=0)
    human_resolved_count: int = Field(ge=0)
    human_review_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    human_gold_pass_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    metrics: dict[str, DistributionStatistics] = Field(default_factory=dict)
    reviewer_agreement: AgreementReport


class QualityDeltaStatistics(BaseModel):
    scope: QualityDeltaScope
    profile: str = Field(min_length=1)
    baseline: str = Field(min_length=1)
    case_id: str | None = None
    paired_units: int = Field(ge=0)
    metrics: dict[str, DistributionStatistics] = Field(default_factory=dict)


class RuntimeQualityAggregateReport(BaseModel):
    matrix_name: str
    matrix_version: str
    corpus_name: str
    corpus_version: str
    baseline_profile: str
    repetitions: int = Field(ge=1)
    generated_at: str
    bootstrap_resamples: int = Field(ge=1)
    confidence_level: float = Field(gt=0.0, lt=1.0)
    bootstrap_seed: int
    observations: list[RuntimeQualityObservation]
    profile_statistics: list[QualityScopeStatistics]
    profile_case_statistics: list[QualityScopeStatistics]
    profile_delta_statistics: list[QualityDeltaStatistics]
    profile_case_delta_statistics: list[QualityDeltaStatistics]
    human_gold_significance: SignificanceReport | None = None


def _run_key(repetition: int, profile: str, case_id: str) -> tuple[int, str, str]:
    return repetition, profile, case_id


def _source_evaluable(report: SourcePolicyComplianceReport) -> bool:
    return all(check.status != "unverifiable" for check in report.checks)


def _freshness_coverage(report: SourcePolicyComplianceReport) -> float | None:
    if report.evidence_count <= 0:
        return None
    freshness_checks = [check for check in report.checks if check.name == "minimum_recent_sources"]
    if not freshness_checks:
        return None
    return report.freshness_evaluable_count / report.evidence_count


def _review_pair_metrics(
    reviews: list[EvaluatedHumanReview],
) -> tuple[bool | None, float | None]:
    if len(reviews) != 2:
        return None, None
    left, right = reviews
    return left.passed == right.passed, abs(left.weighted_score - right.weighted_score)


def _validate_sidecars(
    repeated: RepeatedExperimentReport,
    source_observations: list[SourceQualityObservation],
    assignments: list[BlindReviewAssignment],
    human_audit: HumanReviewAuditReport | None,
) -> tuple[
    dict[tuple[int, str, str], SourceQualityObservation],
    dict[str, BlindReviewAssignment],
]:
    run_keys = {
        _run_key(record.repetition, record.profile, record.result.case.case_id)
        for record in repeated.runs
    }
    source_index: dict[tuple[int, str, str], SourceQualityObservation] = {}
    for item in source_observations:
        key = _run_key(item.repetition, item.profile, item.case_id)
        if key not in run_keys:
            raise ValueError(f"source observation 不属于 repeated run: {key}")
        if key in source_index:
            raise ValueError(f"同一 run 只能有一个 source observation: {key}")
        source_index[key] = item

    assignment_index: dict[str, BlindReviewAssignment] = {}
    assignment_run_keys: set[tuple[int, str, str]] = set()
    for item in assignments:
        key = _run_key(item.repetition, item.profile, item.case_id)
        if key not in run_keys:
            raise ValueError(f"blind assignment 不属于 repeated run: {key}")
        if item.blind_item_id in assignment_index:
            raise ValueError(f"blind_item_id 必须唯一: {item.blind_item_id}")
        if key in assignment_run_keys:
            raise ValueError(f"同一 run 只能绑定一个 blind item: {key}")
        assignment_index[item.blind_item_id] = item
        assignment_run_keys.add(key)

    if human_audit is not None:
        audit_ids = {item.blind_item_id for item in human_audit.item_outcomes}
        review_ids = {item.blind_item_id for item in human_audit.evaluated_reviews}
        unknown = (audit_ids | review_ids) - set(assignment_index)
        if unknown:
            raise ValueError(
                "human audit 存在未绑定 repeated run 的 blind item: " + ", ".join(sorted(unknown))
            )
    return source_index, assignment_index


def _build_runtime_observations(
    repeated: RepeatedExperimentReport,
    source_index: dict[tuple[int, str, str], SourceQualityObservation],
    assignment_index: dict[str, BlindReviewAssignment],
    human_audit: HumanReviewAuditReport | None,
) -> list[RuntimeQualityObservation]:
    assignments_by_key = {
        _run_key(item.repetition, item.profile, item.case_id): item
        for item in assignment_index.values()
    }
    outcomes = (
        {item.blind_item_id: item for item in human_audit.item_outcomes}
        if human_audit is not None
        else {}
    )
    reviews_by_item: dict[str, list[EvaluatedHumanReview]] = defaultdict(list)
    if human_audit is not None:
        for review in human_audit.evaluated_reviews:
            reviews_by_item[review.blind_item_id].append(review)

    observations: list[RuntimeQualityObservation] = []
    for record in repeated.runs:
        key = _run_key(record.repetition, record.profile, record.result.case.case_id)
        source_item = source_index.get(key)
        assignment = assignments_by_key.get(key)

        source_observed = source_item is not None
        source_evaluable: bool | None = None
        source_passed: bool | None = None
        freshness_coverage: float | None = None
        if source_item is not None:
            source_evaluable = _source_evaluable(source_item.report)
            source_passed = source_item.report.passed if source_evaluable else None
            freshness_coverage = _freshness_coverage(source_item.report)

        blind_item_id = assignment.blind_item_id if assignment is not None else None
        outcome = outcomes.get(blind_item_id) if blind_item_id is not None else None
        human_resolved = outcome.resolved if outcome is not None else None
        human_score = outcome.final_score if outcome is not None and outcome.resolved else None
        human_passed = outcome.final_passed if outcome is not None and outcome.resolved else None
        pass_agreement, score_gap = _review_pair_metrics(
            reviews_by_item.get(blind_item_id, []) if blind_item_id is not None else []
        )

        observations.append(
            RuntimeQualityObservation(
                repetition=record.repetition,
                run_status=record.result.status,
                profile=record.profile,
                case_id=record.result.case.case_id,
                source_policy_observed=source_observed,
                source_policy_evaluable=source_evaluable,
                source_policy_passed=source_passed,
                freshness_metadata_coverage=freshness_coverage,
                blind_item_id=blind_item_id,
                human_review_resolved=human_resolved,
                human_gold_score=human_score,
                human_gold_passed=human_passed,
                reviewer_pass_agreement=pass_agreement,
                reviewer_score_gap=score_gap,
            )
        )
    return observations


def _quality_metric_value(
    observation: RuntimeQualityObservation,
    metric: str,
) -> float | None:
    if metric == "source_policy_pass":
        value = observation.source_policy_passed
    elif metric == "human_gold_score":
        value = observation.human_gold_score
    elif metric == "human_gold_pass":
        value = observation.human_gold_passed
    elif metric == "freshness_metadata_coverage":
        value = observation.freshness_metadata_coverage
    else:
        raise KeyError(metric)
    if value is None:
        return None
    return float(value)


def _summarize_quality_metric(
    values: list[float],
    *,
    confidence_level: float,
    resamples: int,
    seed: int,
    seed_parts: tuple[str, ...],
) -> DistributionStatistics:
    return summarize_distribution(
        values,
        confidence_level=confidence_level,
        resamples=resamples,
        seed=stable_seed(seed, *seed_parts),
    )


def _agreement_for_scope(
    human_audit: HumanReviewAuditReport | None,
    assignment_index: dict[str, BlindReviewAssignment],
    *,
    profile: str,
    case_id: str | None,
) -> AgreementReport:
    if human_audit is None:
        return AgreementReport(paired_items=0)
    selected: list[EvaluatedHumanReview] = []
    for review in human_audit.evaluated_reviews:
        assignment = assignment_index.get(review.blind_item_id)
        if assignment is None or assignment.profile != profile:
            continue
        if case_id is not None and assignment.case_id != case_id:
            continue
        selected.append(review)
    return calculate_inter_rater_agreement(selected)


def _build_quality_scope(
    observations: list[RuntimeQualityObservation],
    completed_keys: set[tuple[int, str, str]],
    human_audit: HumanReviewAuditReport | None,
    assignment_index: dict[str, BlindReviewAssignment],
    *,
    scope: QualityScope,
    profile: str,
    case_id: str | None,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> QualityScopeStatistics:
    selected = [
        item
        for item in observations
        if item.profile == profile
        and (case_id is None or item.case_id == case_id)
        and _run_key(item.repetition, item.profile, item.case_id) in completed_keys
    ]
    completed_count = len(selected)
    source_observed = [item for item in selected if item.source_policy_observed]
    source_evaluable = [item for item in source_observed if item.source_policy_evaluable is True]
    source_unverifiable = [
        item for item in source_observed if item.source_policy_evaluable is False
    ]
    human_assigned = [item for item in selected if item.blind_item_id is not None]
    human_resolved = [item for item in human_assigned if item.human_review_resolved is True]

    metrics: dict[str, DistributionStatistics] = {}
    for metric in QUALITY_METRICS:
        values = [
            value for item in selected if (value := _quality_metric_value(item, metric)) is not None
        ]
        if values:
            metrics[metric] = _summarize_quality_metric(
                values,
                confidence_level=confidence_level,
                resamples=resamples,
                seed=seed,
                seed_parts=(scope, profile, case_id or "all", metric),
            )

    source_passed = sum(item.source_policy_passed is True for item in source_evaluable)
    human_passed = sum(item.human_gold_passed is True for item in human_resolved)
    return QualityScopeStatistics(
        scope=scope,
        profile=profile,
        case_id=case_id,
        completed_run_count=completed_count,
        source_observation_count=len(source_observed),
        source_evaluable_count=len(source_evaluable),
        source_unverifiable_count=len(source_unverifiable),
        source_observation_coverage=(
            len(source_observed) / completed_count if completed_count else None
        ),
        source_evaluable_rate=(
            len(source_evaluable) / len(source_observed) if source_observed else None
        ),
        source_compliance_rate=(
            source_passed / len(source_evaluable) if source_evaluable else None
        ),
        human_assignment_count=len(human_assigned),
        human_resolved_count=len(human_resolved),
        human_review_coverage=(len(human_resolved) / completed_count if completed_count else None),
        human_gold_pass_rate=(human_passed / len(human_resolved) if human_resolved else None),
        metrics=metrics,
        reviewer_agreement=_agreement_for_scope(
            human_audit,
            assignment_index,
            profile=profile,
            case_id=case_id,
        ),
    )


def _paired_quality_values(
    observations: list[RuntimeQualityObservation],
    *,
    profile: str,
    baseline: str,
    metric: str,
    case_id: str | None,
) -> tuple[list[float], list[float], list[float]]:
    current_index = {
        (item.repetition, item.case_id): item
        for item in observations
        if item.profile == profile
        and item.run_status == "completed"
        and (case_id is None or item.case_id == case_id)
    }
    baseline_index = {
        (item.repetition, item.case_id): item
        for item in observations
        if item.profile == baseline
        and item.run_status == "completed"
        and (case_id is None or item.case_id == case_id)
    }
    current_values: list[float] = []
    baseline_values: list[float] = []
    differences: list[float] = []
    for key in sorted(set(current_index).intersection(baseline_index)):
        left = _quality_metric_value(current_index[key], metric)
        right = _quality_metric_value(baseline_index[key], metric)
        if left is None or right is None:
            continue
        current_values.append(left)
        baseline_values.append(right)
        differences.append(left - right)
    return current_values, baseline_values, differences


def _build_quality_delta(
    observations: list[RuntimeQualityObservation],
    *,
    scope: QualityDeltaScope,
    profile: str,
    baseline: str,
    case_id: str | None,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> QualityDeltaStatistics:
    metrics: dict[str, DistributionStatistics] = {}
    pair_keys: set[tuple[int, str]] = set()
    for metric in QUALITY_METRICS:
        current_index = {
            (item.repetition, item.case_id): item
            for item in observations
            if item.profile == profile
            and item.run_status == "completed"
            and (case_id is None or item.case_id == case_id)
        }
        baseline_index = {
            (item.repetition, item.case_id): item
            for item in observations
            if item.profile == baseline
            and item.run_status == "completed"
            and (case_id is None or item.case_id == case_id)
        }
        pair_keys.update(set(current_index).intersection(baseline_index))
        _, _, differences = _paired_quality_values(
            observations,
            profile=profile,
            baseline=baseline,
            metric=metric,
            case_id=case_id,
        )
        if differences:
            metrics[metric] = _summarize_quality_metric(
                differences,
                confidence_level=confidence_level,
                resamples=resamples,
                seed=seed,
                seed_parts=(scope, profile, case_id or "all", metric),
            )
    return QualityDeltaStatistics(
        scope=scope,
        profile=profile,
        baseline=baseline,
        case_id=case_id,
        paired_units=len(pair_keys),
        metrics=metrics,
    )


def _human_gold_case_mean_pairs(
    observations: list[RuntimeQualityObservation],
    *,
    profile: str,
    baseline: str,
) -> tuple[list[float], list[float], list[float]]:
    current_values: list[float] = []
    baseline_values: list[float] = []
    differences: list[float] = []
    case_ids = sorted({item.case_id for item in observations})
    for case_id in case_ids:
        left, right, paired = _paired_quality_values(
            observations,
            profile=profile,
            baseline=baseline,
            metric="human_gold_score",
            case_id=case_id,
        )
        if not paired:
            continue
        current_values.append(fmean(left))
        baseline_values.append(fmean(right))
        differences.append(fmean(paired))
    return current_values, baseline_values, differences


def _build_human_gold_significance(
    repeated: RepeatedExperimentReport,
    observations: list[RuntimeQualityObservation],
    *,
    alpha: float,
    exact_permutation_max_pairs: int,
    permutation_resamples: int,
    permutation_seed: int,
) -> SignificanceReport | None:
    profiles = sorted({item.profile for item in observations})
    profiles = [profile for profile in profiles if profile != repeated.baseline_profile]
    if not profiles:
        return None

    any_pairs = False
    comparisons = []
    case_ids = sorted({item.case_id for item in observations})
    for profile in profiles:
        current, baseline, differences = _human_gold_case_mean_pairs(
            observations,
            profile=profile,
            baseline=repeated.baseline_profile,
        )
        if differences:
            any_pairs = True
        comparisons.append(
            build_paired_comparison(
                scope="profile_across_cases",
                profile=profile,
                baseline_profile=repeated.baseline_profile,
                case_id=None,
                metric="human_gold_score",
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
            left, right, paired = _paired_quality_values(
                observations,
                profile=profile,
                baseline=repeated.baseline_profile,
                metric="human_gold_score",
                case_id=case_id,
            )
            if paired:
                any_pairs = True
            comparisons.append(
                build_paired_comparison(
                    scope="profile_case",
                    profile=profile,
                    baseline_profile=repeated.baseline_profile,
                    case_id=case_id,
                    metric="human_gold_score",
                    current=left,
                    baseline=right,
                    differences=paired,
                    alpha=alpha,
                    exact_max_pairs=exact_permutation_max_pairs,
                    permutation_resamples=permutation_resamples,
                    permutation_seed=permutation_seed,
                )
            )

    if not any_pairs:
        return None
    apply_multiple_corrections(comparisons, alpha=alpha)
    return SignificanceReport(
        matrix_name=repeated.matrix_name,
        matrix_version=repeated.matrix_version,
        corpus_name=repeated.corpus_name,
        corpus_version=repeated.corpus_version,
        repetitions=repeated.repetitions,
        generated_at=datetime.now(UTC).isoformat(),
        baseline_profile=repeated.baseline_profile,
        alpha=alpha,
        exact_permutation_max_pairs=exact_permutation_max_pairs,
        permutation_resamples=permutation_resamples,
        permutation_seed=permutation_seed,
        correction_family="same scope + case + human_gold_score across non-baseline profiles",
        minimum_nonzero_pairs_for_holm=minimum_units_for_exact_holm(
            alpha,
            max(1, len(profiles)),
        ),
        comparisons=comparisons,
    )


def build_runtime_quality_aggregate(
    repeated: RepeatedExperimentReport,
    *,
    source_observations: list[SourceQualityObservation] | None = None,
    assignments: list[BlindReviewAssignment] | None = None,
    human_audit: HumanReviewAuditReport | None = None,
    bootstrap_resamples: int | None = None,
    confidence_level: float | None = None,
    bootstrap_seed: int | None = None,
    alpha: float = 0.05,
    exact_permutation_max_pairs: int = 16,
    permutation_resamples: int = 20000,
    permutation_seed: int = 20260915,
) -> RuntimeQualityAggregateReport:
    source_observations = source_observations or []
    assignments = assignments or []
    resamples = bootstrap_resamples or repeated.bootstrap_resamples
    confidence = confidence_level or repeated.confidence_level
    seed = bootstrap_seed if bootstrap_seed is not None else repeated.bootstrap_seed

    source_index, assignment_index = _validate_sidecars(
        repeated,
        source_observations,
        assignments,
        human_audit,
    )
    observations = _build_runtime_observations(
        repeated,
        source_index,
        assignment_index,
        human_audit,
    )
    completed_keys = {
        _run_key(record.repetition, record.profile, record.result.case.case_id)
        for record in repeated.runs
        if record.result.status == "completed"
    }

    profile_stats: list[QualityScopeStatistics] = []
    profile_case_stats: list[QualityScopeStatistics] = []
    delta_stats: list[QualityDeltaStatistics] = []
    delta_case_stats: list[QualityDeltaStatistics] = []

    profiles = sorted({record.profile for record in repeated.runs})
    case_ids = sorted({record.result.case.case_id for record in repeated.runs})
    for profile in profiles:
        profile_stats.append(
            _build_quality_scope(
                observations,
                completed_keys,
                human_audit,
                assignment_index,
                scope="profile",
                profile=profile,
                case_id=None,
                confidence_level=confidence,
                resamples=resamples,
                seed=seed,
            )
        )
        delta_stats.append(
            _build_quality_delta(
                observations,
                scope="profile_delta",
                profile=profile,
                baseline=repeated.baseline_profile,
                case_id=None,
                confidence_level=confidence,
                resamples=resamples,
                seed=seed,
            )
        )
        for case_id in case_ids:
            profile_case_stats.append(
                _build_quality_scope(
                    observations,
                    completed_keys,
                    human_audit,
                    assignment_index,
                    scope="profile_case",
                    profile=profile,
                    case_id=case_id,
                    confidence_level=confidence,
                    resamples=resamples,
                    seed=seed,
                )
            )
            delta_case_stats.append(
                _build_quality_delta(
                    observations,
                    scope="profile_case_delta",
                    profile=profile,
                    baseline=repeated.baseline_profile,
                    case_id=case_id,
                    confidence_level=confidence,
                    resamples=resamples,
                    seed=seed,
                )
            )

    significance = _build_human_gold_significance(
        repeated,
        observations,
        alpha=alpha,
        exact_permutation_max_pairs=exact_permutation_max_pairs,
        permutation_resamples=permutation_resamples,
        permutation_seed=permutation_seed,
    )
    return RuntimeQualityAggregateReport(
        matrix_name=repeated.matrix_name,
        matrix_version=repeated.matrix_version,
        corpus_name=repeated.corpus_name,
        corpus_version=repeated.corpus_version,
        baseline_profile=repeated.baseline_profile,
        repetitions=repeated.repetitions,
        generated_at=datetime.now(UTC).isoformat(),
        bootstrap_resamples=resamples,
        confidence_level=confidence,
        bootstrap_seed=seed,
        observations=observations,
        profile_statistics=profile_stats,
        profile_case_statistics=profile_case_stats,
        profile_delta_statistics=delta_stats,
        profile_case_delta_statistics=delta_case_stats,
        human_gold_significance=significance,
    )
