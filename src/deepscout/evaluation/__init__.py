"""DeepScout benchmark、轨迹与评测基础设施。"""

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
    "build_report",
    "calculate_metrics",
    "evaluate_expectations",
    "load_corpus",
    "render_markdown",
    "run_case",
    "run_corpus",
    "save_report",
]
