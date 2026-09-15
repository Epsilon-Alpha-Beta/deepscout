"""Phase 4 benchmark 与轨迹评测数据模型。"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BenchmarkExpectations(BaseModel):
    """一个 Benchmark Case 的可机器校验阈值。"""

    min_citation_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    min_task_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    min_unique_source_hosts: int | None = Field(default=None, ge=0)
    max_unsupported_claims: int | None = Field(default=None, ge=0)
    max_search_calls: int | None = Field(default=None, ge=0)
    max_research_tokens: int | None = Field(default=None, ge=0)
    max_wall_seconds: float | None = Field(default=None, gt=0.0)
    min_keyword_recall: float | None = Field(default=None, ge=0.0, le=1.0)


class BenchmarkCase(BaseModel):
    """单个研究 Benchmark Case。"""

    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    category: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    tags: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    expectations: BenchmarkExpectations = Field(default_factory=BenchmarkExpectations)


class BenchmarkCorpus(BaseModel):
    """版本化 Benchmark Corpus。"""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: str = ""
    cases: list[BenchmarkCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "BenchmarkCorpus":
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Benchmark corpus case_id 必须唯一。")
        return self


class TrajectoryEvent(BaseModel):
    """不记录正文内容的低敏感轨迹事件。"""

    sequence: int = Field(ge=0)
    node: str = Field(min_length=1)
    elapsed_ms: float = Field(ge=0.0)
    output_keys: list[str] = Field(default_factory=list)


class BenchmarkPricing(BaseModel):
    """可选成本估算参数；未配置时不虚构美元成本。"""

    research_token_usd_per_million: float | None = Field(default=None, ge=0.0)
    search_usd_per_1000_calls: float | None = Field(default=None, ge=0.0)


class BenchmarkMetrics(BaseModel):
    wall_seconds: float = Field(ge=0.0)
    node_visits: dict[str, int] = Field(default_factory=dict)
    total_node_events: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    task_count: int = Field(ge=0)
    completed_tasks: int = Field(ge=0)
    failed_tasks: int = Field(ge=0)
    task_success_rate: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)
    unique_source_hosts: int = Field(ge=0)
    source_diversity_ratio: float = Field(ge=0.0, le=1.0)
    average_evidence_relevance: float | None = Field(default=None, ge=0.0, le=1.0)
    citation_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claims: int = Field(ge=0)
    search_calls: int = Field(ge=0)
    research_tokens: int = Field(ge=0)
    worker_seconds: float = Field(ge=0.0)
    final_report_chars: int = Field(ge=0)
    keyword_recall: float | None = Field(default=None, ge=0.0, le=1.0)
    quality_proxy_score: float = Field(ge=0.0, le=1.0)
    research_token_cost_usd: float | None = Field(default=None, ge=0.0)
    search_cost_usd: float | None = Field(default=None, ge=0.0)
    estimated_tracked_cost_usd: float | None = Field(default=None, ge=0.0)


class ExpectationCheck(BaseModel):
    name: str = Field(min_length=1)
    passed: bool
    actual: float | int | None = None
    expected: float | int | None = None
    comparator: Literal[">=", "<="]


class BenchmarkRunResult(BaseModel):
    case: BenchmarkCase
    status: Literal["completed", "interrupted", "error", "not_run"]
    passed: bool
    metrics: BenchmarkMetrics
    expectations: list[ExpectationCheck] = Field(default_factory=list)
    trajectory: list[TrajectoryEvent] = Field(default_factory=list)
    error: str | None = None


class BenchmarkSummary(BaseModel):
    total_cases: int = Field(ge=0)
    completed_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    average_quality_proxy_score: float = Field(ge=0.0, le=1.0)
    average_citation_coverage: float = Field(ge=0.0, le=1.0)
    total_search_calls: int = Field(ge=0)
    total_research_tokens: int = Field(ge=0)
    total_worker_seconds: float = Field(ge=0.0)
    total_wall_seconds: float = Field(ge=0.0)
    estimated_tracked_cost_usd: float | None = Field(default=None, ge=0.0)


class BenchmarkReport(BaseModel):
    corpus_name: str
    corpus_version: str
    generated_at: str
    summary: BenchmarkSummary
    results: list[BenchmarkRunResult]
