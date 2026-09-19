from pathlib import Path

from deepscout.evaluation.ablation import load_ablation_matrix
from deepscout.evaluation.experiment_bundle import (
    create_experiment_bundle,
    load_bundle_manifest,
    validate_experiment_bundle,
)
from deepscout.evaluation.experiment_compare import compare_experiment_bundles
from deepscout.evaluation.experiment_compare_report import save_experiment_comparison
from deepscout.evaluation.human_review import AgreementReport
from deepscout.evaluation.models import BenchmarkMetrics, BenchmarkRunResult
from deepscout.evaluation.quality_aggregate import (
    QualityScopeStatistics,
    RuntimeQualityAggregateReport,
)
from deepscout.evaluation.repeated import RepeatedRunRecord, build_repeated_report
from deepscout.evaluation.runner import load_corpus
from deepscout.evaluation.statistics import summarize_distribution


def _metrics(*, quality: float, wall: float, searches: int) -> BenchmarkMetrics:
    return BenchmarkMetrics(
        wall_seconds=wall,
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
        search_calls=searches,
        research_tokens=1000,
        worker_seconds=wall / 2,
        final_report_chars=100,
        quality_proxy_score=quality,
    )


def _repeated(path: Path, *, quality_shift: float = 0.0, wall_shift: float = 0.0):
    corpus = load_corpus("benchmarks/corpora/core.json")
    matrix = load_ablation_matrix("benchmarks/ablations/core.json")
    case = corpus.cases[0]
    records = []
    for order, profile in enumerate(matrix.profiles):
        quality = max(0.0, min(1.0, 0.8 + quality_shift - order * 0.01))
        wall = 1.0 + wall_shift + order * 0.01
        result = BenchmarkRunResult(
            case=case,
            status="completed",
            passed=True,
            metrics=_metrics(quality=quality, wall=wall, searches=2),
        )
        records.append(
            RepeatedRunRecord(
                repetition=1,
                execution_order=order,
                profile_order=order,
                profile=profile.name,
                result=result,
            )
        )
    report = build_repeated_report(
        corpus,
        matrix,
        records,
        repetitions=1,
        order_strategy="fixed",
        bootstrap_resamples=100,
        confidence_level=0.95,
        bootstrap_seed=7,
    )
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return report


def _dist(value: float):
    return summarize_distribution([value], confidence_level=0.95, resamples=20, seed=3)


def _quality(path: Path, repeated, *, gold_shift: float = 0.0):
    stats = []
    for idx, profile in enumerate(sorted({r.profile for r in repeated.runs})):
        gold = max(0.0, min(1.0, 0.85 + gold_shift - idx * 0.01))
        stats.append(
            QualityScopeStatistics(
                scope="profile",
                profile=profile,
                completed_run_count=1,
                source_observation_count=1,
                source_evaluable_count=1,
                source_unverifiable_count=0,
                source_observation_coverage=1.0,
                source_evaluable_rate=1.0,
                source_compliance_rate=0.9 + gold_shift,
                human_assignment_count=1,
                human_resolved_count=1,
                human_review_coverage=1.0,
                human_gold_pass_rate=1.0,
                metrics={"human_gold_score": _dist(gold)},
                reviewer_agreement=AgreementReport(paired_items=0),
            )
        )
    report = RuntimeQualityAggregateReport(
        matrix_name=repeated.matrix_name,
        matrix_version=repeated.matrix_version,
        corpus_name=repeated.corpus_name,
        corpus_version=repeated.corpus_version,
        baseline_profile=repeated.baseline_profile,
        repetitions=repeated.repetitions,
        generated_at="2026-09-19T00:00:00+00:00",
        bootstrap_resamples=100,
        confidence_level=0.95,
        bootstrap_seed=7,
        observations=[],
        profile_statistics=stats,
        profile_case_statistics=[],
        profile_delta_statistics=[],
        profile_case_delta_statistics=[],
    )
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _bundle(tmp_path: Path, name: str, *, quality_shift=0.0, wall_shift=0.0, gold_shift=0.0):
    source = tmp_path / f"{name}-source"
    source.mkdir()
    repeated_path = source / "repeated.json"
    quality_path = source / "quality.json"
    repeated = _repeated(repeated_path, quality_shift=quality_shift, wall_shift=wall_shift)
    _quality(quality_path, repeated, gold_shift=gold_shift)
    bundle = tmp_path / name
    create_experiment_bundle(
        repeated_path=repeated_path,
        output_dir=bundle,
        corpus_path="benchmarks/corpora/core.json",
        matrix_path="benchmarks/ablations/core.json",
        quality_aggregate_path=quality_path,
        provider="synthetic",
        model="fixture",
        experiment_id=name,
    )
    return bundle


def test_bundle_validates_and_detects_tampering(tmp_path: Path):
    bundle = _bundle(tmp_path, "baseline")
    report = validate_experiment_bundle(bundle)
    assert report.valid is True
    assert report.checked_artifacts == 4
    manifest = load_bundle_manifest(bundle)
    repeated = next(item for item in manifest.artifacts if item.role == "repeated")
    (bundle / repeated.path).write_text("tampered\n", encoding="utf-8")
    invalid = validate_experiment_bundle(bundle)
    assert invalid.valid is False
    assert any("sha256 mismatch" in item for item in invalid.errors)


def test_comparator_flags_quality_and_latency_regressions(tmp_path: Path):
    baseline = _bundle(tmp_path, "baseline")
    candidate = _bundle(
        tmp_path, "candidate", quality_shift=-0.10, wall_shift=0.30, gold_shift=-0.10
    )
    report = compare_experiment_bundles(baseline, candidate)
    assert report.comparable is True
    assert report.regression_count > 0
    rows = {(row.profile, row.metric): row for row in report.comparisons}
    assert rows[("full", "quality_proxy_score")].status == "regression"
    assert rows[("full", "wall_seconds")].status == "regression"
    assert rows[("full", "human_gold_score")].status == "regression"
    paths = save_experiment_comparison(report, tmp_path / "comparison")
    assert all(path.exists() for path in paths.values())


def test_incompatible_matrix_identity_blocks_comparison(tmp_path: Path):
    baseline = _bundle(tmp_path, "baseline")
    candidate = _bundle(tmp_path, "candidate")
    manifest_path = candidate / "manifest.json"
    manifest = load_bundle_manifest(candidate)
    manifest.identity.matrix_version = "999"
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    report = compare_experiment_bundles(baseline, candidate)
    assert report.comparable is False
    assert any("candidate bundle" in item or "matrix" in item for item in report.incompatibilities)
