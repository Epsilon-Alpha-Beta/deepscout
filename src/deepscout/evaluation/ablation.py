"""Phase 4 消融实验矩阵、执行与比较模型。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from deepscout.config import settings_override
from deepscout.evaluation.models import BenchmarkCorpus, BenchmarkPricing, BenchmarkReport
from deepscout.evaluation.report import build_report
from deepscout.evaluation.runner import run_corpus
from deepscout.graph.options import GraphOptions


class AblationSettings(BaseModel):
    """允许在单个消融 profile 中覆盖的运行参数。"""

    max_concurrency: int | None = Field(default=None, ge=1, le=32)
    max_replans: int | None = Field(default=None, ge=0, le=10)
    max_research_tasks: int | None = Field(default=None, ge=1, le=200)
    max_evidence_items: int | None = Field(default=None, ge=1, le=500)
    max_searches: int | None = Field(default=None, ge=1, le=1000)
    max_research_tokens: int | None = Field(default=None, ge=1)
    max_worker_seconds: float | None = Field(default=None, gt=0.0)
    search_max_calls_per_task: int | None = Field(default=None, ge=1, le=50)

    def as_overrides(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class AblationGraphOptions(BaseModel):
    citation_feedback_enabled: bool = True
    evidence_dedup_enabled: bool = True

    def to_graph_options(self) -> GraphOptions:
        return GraphOptions(**self.model_dump())


class AblationProfile(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = ""
    settings: AblationSettings = Field(default_factory=AblationSettings)
    graph: AblationGraphOptions = Field(default_factory=AblationGraphOptions)


class AblationMatrix(BaseModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    baseline_profile: str = Field(min_length=1)
    profiles: list[AblationProfile] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_profiles(self) -> "AblationMatrix":
        names = [profile.name for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("Ablation profile name 必须唯一。")
        if self.baseline_profile not in names:
            raise ValueError("baseline_profile 必须引用已定义 profile。")
        return self


class AblationComparison(BaseModel):
    profile: str
    baseline: str
    case_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    delta_pass_rate: float
    average_quality_proxy_score: float = Field(ge=0.0, le=1.0)
    delta_quality_proxy_score: float
    average_citation_coverage: float = Field(ge=0.0, le=1.0)
    delta_citation_coverage: float
    average_source_diversity_ratio: float = Field(ge=0.0, le=1.0)
    delta_source_diversity_ratio: float
    replans_per_case: float = Field(ge=0.0)
    delta_replans_per_case: float
    evidence_count_per_case: float = Field(ge=0.0)
    delta_evidence_count_per_case: float
    search_calls_per_case: float = Field(ge=0.0)
    delta_search_calls_per_case: float
    research_tokens_per_case: float = Field(ge=0.0)
    delta_research_tokens_per_case: float
    wall_seconds_per_case: float = Field(ge=0.0)
    delta_wall_seconds_per_case: float
    tracked_cost_per_case_usd: float | None = Field(default=None, ge=0.0)
    delta_tracked_cost_per_case_usd: float | None = None


class AblationProfileReport(BaseModel):
    profile: AblationProfile
    benchmark: BenchmarkReport


class AblationReport(BaseModel):
    matrix_name: str
    matrix_version: str
    corpus_name: str
    corpus_version: str
    baseline_profile: str
    generated_at: str
    profiles: list[AblationProfileReport]
    comparisons: list[AblationComparison]


def load_ablation_matrix(path: str | Path) -> AblationMatrix:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return AblationMatrix.model_validate(payload)


def _per_case(total: float | int, count: int) -> float:
    return float(total) / count if count else 0.0


def compare_to_baseline(
    profile: BenchmarkReport,
    baseline: BenchmarkReport,
    *,
    profile_name: str,
    baseline_name: str,
) -> AblationComparison:
    current = profile.summary
    base = baseline.summary
    count = current.total_cases
    base_count = base.total_cases
    current_cost = (
        _per_case(current.estimated_tracked_cost_usd, count)
        if current.estimated_tracked_cost_usd is not None
        else None
    )
    base_cost = (
        _per_case(base.estimated_tracked_cost_usd, base_count)
        if base.estimated_tracked_cost_usd is not None
        else None
    )
    return AblationComparison(
        profile=profile_name,
        baseline=baseline_name,
        case_count=count,
        pass_rate=current.pass_rate,
        delta_pass_rate=current.pass_rate - base.pass_rate,
        average_quality_proxy_score=current.average_quality_proxy_score,
        delta_quality_proxy_score=(
            current.average_quality_proxy_score - base.average_quality_proxy_score
        ),
        average_citation_coverage=current.average_citation_coverage,
        delta_citation_coverage=(
            current.average_citation_coverage - base.average_citation_coverage
        ),
        average_source_diversity_ratio=current.average_source_diversity_ratio,
        delta_source_diversity_ratio=(
            current.average_source_diversity_ratio - base.average_source_diversity_ratio
        ),
        replans_per_case=_per_case(current.total_replans, count),
        delta_replans_per_case=(
            _per_case(current.total_replans, count) - _per_case(base.total_replans, base_count)
        ),
        evidence_count_per_case=_per_case(current.total_evidence_count, count),
        delta_evidence_count_per_case=(
            _per_case(current.total_evidence_count, count)
            - _per_case(base.total_evidence_count, base_count)
        ),
        search_calls_per_case=_per_case(current.total_search_calls, count),
        delta_search_calls_per_case=(
            _per_case(current.total_search_calls, count)
            - _per_case(base.total_search_calls, base_count)
        ),
        research_tokens_per_case=_per_case(current.total_research_tokens, count),
        delta_research_tokens_per_case=(
            _per_case(current.total_research_tokens, count)
            - _per_case(base.total_research_tokens, base_count)
        ),
        wall_seconds_per_case=_per_case(current.total_wall_seconds, count),
        delta_wall_seconds_per_case=(
            _per_case(current.total_wall_seconds, count)
            - _per_case(base.total_wall_seconds, base_count)
        ),
        tracked_cost_per_case_usd=current_cost,
        delta_tracked_cost_per_case_usd=(
            current_cost - base_cost if current_cost is not None and base_cost is not None else None
        ),
    )


def build_ablation_report(
    matrix: AblationMatrix,
    corpus: BenchmarkCorpus,
    profile_reports: list[AblationProfileReport],
) -> AblationReport:
    reports = {item.profile.name: item.benchmark for item in profile_reports}
    baseline = reports[matrix.baseline_profile]
    comparisons = [
        compare_to_baseline(
            item.benchmark,
            baseline,
            profile_name=item.profile.name,
            baseline_name=matrix.baseline_profile,
        )
        for item in profile_reports
    ]
    return AblationReport(
        matrix_name=matrix.name,
        matrix_version=matrix.version,
        corpus_name=corpus.name,
        corpus_version=corpus.version,
        baseline_profile=matrix.baseline_profile,
        generated_at=datetime.now(UTC).isoformat(),
        profiles=profile_reports,
        comparisons=comparisons,
    )


async def run_ablation_matrix(
    corpus: BenchmarkCorpus,
    matrix: AblationMatrix,
    *,
    graph_factory: Any = None,
    limit: int | None = None,
    pricing: BenchmarkPricing | None = None,
) -> AblationReport:
    """顺序执行所有 profile，避免 profile 间资源竞争污染对比。"""
    if graph_factory is None:
        from deepscout.graph.builder import build_graph

        graph_factory = build_graph

    profile_reports: list[AblationProfileReport] = []
    for profile in matrix.profiles:
        with settings_override(profile.settings.as_overrides()):
            graph = graph_factory(options=profile.graph.to_graph_options())
            results = await run_corpus(graph, corpus, limit=limit, pricing=pricing)
        profile_reports.append(
            AblationProfileReport(
                profile=profile,
                benchmark=build_report(corpus, results),
            )
        )
    return build_ablation_report(matrix, corpus, profile_reports)
