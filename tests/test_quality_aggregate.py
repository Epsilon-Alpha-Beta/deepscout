from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest

from deepscout.evaluation.ablation import AblationMatrix, AblationProfile
from deepscout.evaluation.human_review import CriterionRating, HumanGoldReview
from deepscout.evaluation.models import (
    BenchmarkCorpus,
    BenchmarkMetrics,
    BenchmarkRunResult,
)
from deepscout.evaluation.quality_aggregate import (
    BlindReviewAssignment,
    SourceQualityObservation,
    build_runtime_quality_aggregate,
)
from deepscout.evaluation.quality_aggregate_report import save_runtime_quality_aggregate
from deepscout.evaluation.repeated import RepeatedRunRecord, build_repeated_report
from deepscout.evaluation.review_audit import build_human_review_audit
from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.source_compliance import (
    SourcePolicyCheck,
    SourcePolicyComplianceReport,
)


def _corpus() -> BenchmarkCorpus:
    core = load_corpus("benchmarks/corpora/core.json")
    return BenchmarkCorpus(
        name="quality-fixture",
        version="1.0",
        cases=core.cases[:2],
    )


def _metrics(quality: float) -> BenchmarkMetrics:
    return BenchmarkMetrics(
        wall_seconds=1.0,
        node_visits={},
        total_node_events=1,
        replan_count=0,
        task_count=1,
        completed_tasks=1,
        failed_tasks=0,
        task_success_rate=1.0,
        evidence_count=2,
        unique_source_hosts=2,
        source_diversity_ratio=1.0,
        citation_coverage=1.0,
        unsupported_claims=0,
        search_calls=1,
        research_tokens=100,
        worker_seconds=0.1,
        final_report_chars=100,
        quality_proxy_score=quality,
    )


def _repeated_report():
    corpus = _corpus()
    matrix = AblationMatrix(
        name="quality-matrix",
        version="1.0",
        baseline_profile="full",
        profiles=[
            AblationProfile(name="full"),
            AblationProfile(name="variant"),
        ],
    )
    runs: list[RepeatedRunRecord] = []
    order = 0
    for repetition in (1, 2):
        for profile in ("full", "variant"):
            for case in corpus.cases:
                quality = 0.9 if profile == "full" else 0.6
                result = BenchmarkRunResult(
                    case=case,
                    status="completed",
                    passed=True,
                    metrics=_metrics(quality),
                )
                runs.append(
                    RepeatedRunRecord(
                        repetition=repetition,
                        execution_order=order,
                        profile_order=0 if profile == "full" else 1,
                        profile=profile,
                        result=result,
                    )
                )
                order += 1
    report = build_repeated_report(
        corpus,
        matrix,
        runs,
        repetitions=2,
        order_strategy="fixed",
        bootstrap_resamples=200,
        confidence_level=0.95,
        bootstrap_seed=17,
    )
    return corpus, report


def _source_observation(repetition: int, profile: str, case_id: str, passed: bool):
    return SourceQualityObservation(
        repetition=repetition,
        profile=profile,
        case_id=case_id,
        report=SourcePolicyComplianceReport(
            case_id=case_id,
            evaluated_at=datetime(2026, 9, 19, tzinfo=UTC),
            evidence_count=2,
            primary_source_count=2 if passed else 0,
            preferred_domain_count=1,
            recent_source_count=1,
            freshness_evaluable_count=2,
            freshness_unknown_count=0,
            passed=passed,
            checks=[
                SourcePolicyCheck(
                    name="minimum_primary_sources",
                    status="passed" if passed else "failed",
                    actual=2 if passed else 0,
                    expected=1,
                )
            ],
        ),
    )


def _ratings(case, score: int):
    assert case.gold_rubric is not None
    return [
        CriterionRating(criterion_id=item.criterion_id, score=score)
        for item in case.gold_rubric.criteria
    ]


def _human_sidecars(corpus: BenchmarkCorpus):
    assignments: list[BlindReviewAssignment] = []
    reviews: list[HumanGoldReview] = []
    for repetition in (1, 2):
        for profile in ("full", "variant"):
            for case in corpus.cases:
                blind_id = f"blind_{profile}_{repetition}_{case.case_id}"
                assignments.append(
                    BlindReviewAssignment(
                        blind_item_id=blind_id,
                        repetition=repetition,
                        profile=profile,
                        case_id=case.case_id,
                    )
                )
                score = 4 if profile == "full" else 2
                assert case.gold_rubric is not None
                for reviewer in ("r1", "r2"):
                    reviews.append(
                        HumanGoldReview(
                            blind_item_id=blind_id,
                            case_id=case.case_id,
                            reviewer_id=f"{reviewer}_{blind_id}",
                            ratings=_ratings(case, score),
                            covered_required_points=case.gold_rubric.required_points,
                        )
                    )
    return assignments, build_human_review_audit(corpus, reviews)


def test_runtime_quality_aggregate_profile_delta_significance_and_reports(tmp_path: Path):
    corpus, repeated = _repeated_report()
    source_observations = []
    for repetition in (1, 2):
        for case in corpus.cases:
            source_observations.append(_source_observation(repetition, "full", case.case_id, True))
            source_observations.append(
                _source_observation(
                    repetition,
                    "variant",
                    case.case_id,
                    passed=case.case_id == corpus.cases[0].case_id,
                )
            )
    assignments, human_audit = _human_sidecars(corpus)
    report = build_runtime_quality_aggregate(
        repeated,
        source_observations=source_observations,
        assignments=assignments,
        human_audit=human_audit,
        permutation_seed=19,
    )

    profile_stats = {item.profile: item for item in report.profile_statistics}
    assert profile_stats["full"].source_compliance_rate == 1.0
    assert profile_stats["variant"].source_compliance_rate == 0.5
    assert profile_stats["full"].human_review_coverage == 1.0
    assert profile_stats["variant"].metrics["human_gold_score"].mean == pytest.approx(0.5)
    assert profile_stats["full"].reviewer_agreement.weighted_kappa == 1.0

    deltas = {item.profile: item for item in report.profile_delta_statistics}
    assert deltas["variant"].metrics["human_gold_score"].mean == pytest.approx(-0.5)
    assert deltas["variant"].metrics["human_gold_score"].count == 4

    significance = report.human_gold_significance
    assert significance is not None
    global_variant = next(
        item
        for item in significance.comparisons
        if item.scope == "profile_across_cases" and item.profile == "variant"
    )
    assert global_variant.metric == "human_gold_score"
    assert global_variant.paired_count == 2
    assert global_variant.mean_delta == pytest.approx(-0.5)

    paths = save_runtime_quality_aggregate(report, tmp_path)
    for key in (
        "json",
        "markdown",
        "observations_csv",
        "statistics_csv",
        "deltas_csv",
        "significance_json",
        "significance_csv",
        "significance_markdown",
    ):
        assert paths[key].exists()
    assert "Runtime Quality Aggregate" in paths["markdown"].read_text(encoding="utf-8")
    for key, path in paths.items():
        if key.startswith("chart_"):
            ElementTree.parse(path)


def test_unverifiable_source_policy_is_not_counted_as_failure():
    corpus, repeated = _repeated_report()
    case = corpus.cases[0]
    observation = SourceQualityObservation(
        repetition=1,
        profile="full",
        case_id=case.case_id,
        report=SourcePolicyComplianceReport(
            case_id=case.case_id,
            evaluated_at=datetime(2026, 9, 19, tzinfo=UTC),
            evidence_count=2,
            primary_source_count=2,
            preferred_domain_count=1,
            recent_source_count=0,
            freshness_evaluable_count=0,
            freshness_unknown_count=2,
            passed=False,
            checks=[
                SourcePolicyCheck(
                    name="minimum_primary_sources",
                    status="passed",
                    actual=2,
                    expected=1,
                ),
                SourcePolicyCheck(
                    name="minimum_recent_sources",
                    status="unverifiable",
                    actual=0,
                    expected=1,
                ),
            ],
        ),
    )
    report = build_runtime_quality_aggregate(repeated, source_observations=[observation])
    full = next(item for item in report.profile_statistics if item.profile == "full")
    assert full.source_observation_count == 1
    assert full.source_evaluable_count == 0
    assert full.source_unverifiable_count == 1
    assert full.source_evaluable_rate == 0.0
    assert full.source_compliance_rate is None
    assert "source_policy_pass" not in full.metrics


def test_sidecar_must_bind_to_existing_repeated_run():
    _, repeated = _repeated_report()
    bad = SourceQualityObservation(
        repetition=99,
        profile="full",
        case_id=repeated.runs[0].result.case.case_id,
        report=SourcePolicyComplianceReport(
            case_id=repeated.runs[0].result.case.case_id,
            evaluated_at=datetime(2026, 9, 19, tzinfo=UTC),
            evidence_count=1,
            primary_source_count=1,
            preferred_domain_count=1,
            recent_source_count=0,
            freshness_evaluable_count=0,
            freshness_unknown_count=0,
            passed=True,
            checks=[
                SourcePolicyCheck(
                    name="minimum_primary_sources",
                    status="passed",
                    actual=1,
                    expected=1,
                )
            ],
        ),
    )
    with pytest.raises(ValueError, match="不属于 repeated run"):
        build_runtime_quality_aggregate(repeated, source_observations=[bad])
