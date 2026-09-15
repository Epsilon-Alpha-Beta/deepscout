"""DeepScout benchmark、轨迹与评测基础设施。"""

from deepscout.evaluation.ablation import (
    AblationComparison,
    AblationGraphOptions,
    AblationMatrix,
    AblationProfile,
    AblationProfileReport,
    AblationReport,
    AblationSettings,
    build_ablation_report,
    compare_to_baseline,
    load_ablation_matrix,
    run_ablation_matrix,
)
from deepscout.evaluation.ablation_report import (
    render_ablation_markdown,
    save_ablation_report,
)
from deepscout.evaluation.metrics import calculate_metrics, evaluate_expectations
from deepscout.evaluation.models import (
    BenchmarkCase,
    BenchmarkCorpus,
    BenchmarkExpectations,
    BenchmarkMetrics,
    BenchmarkPricing,
    BenchmarkReport,
    BenchmarkRunResult,
    BenchmarkSummary,
    ExpectationCheck,
    TrajectoryEvent,
)
from deepscout.evaluation.report import build_report, render_markdown, save_report
from deepscout.evaluation.runner import load_corpus, run_case, run_corpus
from deepscout.evaluation.trajectory import TrajectoryRecorder

__all__ = [
    "AblationComparison",
    "AblationGraphOptions",
    "AblationMatrix",
    "AblationProfile",
    "AblationProfileReport",
    "AblationReport",
    "AblationSettings",
    "BenchmarkCase",
    "BenchmarkCorpus",
    "BenchmarkExpectations",
    "BenchmarkMetrics",
    "BenchmarkPricing",
    "BenchmarkReport",
    "BenchmarkRunResult",
    "BenchmarkSummary",
    "ExpectationCheck",
    "TrajectoryEvent",
    "TrajectoryRecorder",
    "build_ablation_report",
    "build_report",
    "calculate_metrics",
    "compare_to_baseline",
    "evaluate_expectations",
    "load_ablation_matrix",
    "load_corpus",
    "render_ablation_markdown",
    "render_markdown",
    "run_ablation_matrix",
    "run_case",
    "run_corpus",
    "save_ablation_report",
    "save_report",
]
