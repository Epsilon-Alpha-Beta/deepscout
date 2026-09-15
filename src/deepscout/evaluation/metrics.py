"""DeepScout final state 的确定性 Benchmark 指标计算。"""

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from deepscout.evaluation.models import (
    BenchmarkCase,
    BenchmarkMetrics,
    BenchmarkPricing,
    ExpectationCheck,
    TrajectoryEvent,
)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _keyword_recall(report: str, keywords: Sequence[str]) -> float | None:
    if not keywords:
        return None
    normalized = report.casefold()
    hits = sum(1 for keyword in keywords if keyword.casefold() in normalized)
    return hits / len(keywords)


def _costs(tokens: int, searches: int, pricing: BenchmarkPricing) -> tuple[float | None, ...]:
    model_cost = None
    if pricing.research_token_usd_per_million is not None:
        model_cost = tokens / 1_000_000 * pricing.research_token_usd_per_million
    search_cost = None
    if pricing.search_usd_per_1000_calls is not None:
        search_cost = searches / 1000 * pricing.search_usd_per_1000_calls
    total = None
    if model_cost is not None and search_cost is not None:
        total = model_cost + search_cost
    return model_cost, search_cost, total


def calculate_metrics(
    case: BenchmarkCase,
    state: Mapping[str, Any],
    trajectory: Sequence[TrajectoryEvent],
    wall_seconds: float,
    pricing: BenchmarkPricing | None = None,
) -> BenchmarkMetrics:
    """从最终 Graph State 和轨迹计算可复现指标。"""
    pricing = pricing or BenchmarkPricing()
    tasks = list(state.get("task_results", []))
    completed_tasks = sum(_field(task, "status") == "completed" for task in tasks)
    failed_tasks = sum(_field(task, "status") == "failed" for task in tasks)
    searches = sum(int(_field(task, "search_calls", 0) or 0) for task in tasks)
    tokens = sum(int(_field(task, "model_tokens", 0) or 0) for task in tasks)
    worker_seconds = sum(float(_field(task, "worker_seconds", 0.0) or 0.0) for task in tasks)

    evidence = list(state.get("evidence_store", []))
    hosts = {
        str(_field(item, "source_host", "")) for item in evidence if _field(item, "source_host", "")
    }
    relevances = [
        float(score) for item in evidence if (score := _field(item, "relevance_score")) is not None
    ]
    avg_relevance = sum(relevances) / len(relevances) if relevances else None

    citation_report = state.get("citation_report")
    citation_coverage = float(_field(citation_report, "coverage_score", 0.0) or 0.0)
    unsupported = len(_field(citation_report, "unsupported_claims", []) or [])
    final_report = str(state.get("final_report", "") or "")
    keyword_recall = _keyword_recall(final_report, case.expected_keywords)
    source_diversity = _ratio(len(hosts), len(evidence))
    task_success = _ratio(completed_tasks, len(tasks))

    quality_components = [citation_coverage, task_success, source_diversity]
    if avg_relevance is not None:
        quality_components.append(avg_relevance)
    if keyword_recall is not None:
        quality_components.append(keyword_recall)
    quality_proxy = sum(quality_components) / len(quality_components)

    visits = dict(Counter(event.node for event in trajectory))
    model_cost, search_cost, total_cost = _costs(tokens, searches, pricing)
    return BenchmarkMetrics(
        wall_seconds=wall_seconds,
        node_visits=visits,
        total_node_events=len(trajectory),
        replan_count=int(state.get("replan_count", 0) or 0),
        task_count=len(tasks),
        completed_tasks=completed_tasks,
        failed_tasks=failed_tasks,
        task_success_rate=task_success,
        evidence_count=len(evidence),
        unique_source_hosts=len(hosts),
        source_diversity_ratio=source_diversity,
        average_evidence_relevance=avg_relevance,
        citation_coverage=citation_coverage,
        unsupported_claims=unsupported,
        search_calls=searches,
        research_tokens=tokens,
        worker_seconds=worker_seconds,
        final_report_chars=len(final_report),
        keyword_recall=keyword_recall,
        quality_proxy_score=quality_proxy,
        research_token_cost_usd=model_cost,
        search_cost_usd=search_cost,
        estimated_tracked_cost_usd=total_cost,
    )


def evaluate_expectations(case: BenchmarkCase, metrics: BenchmarkMetrics) -> list[ExpectationCheck]:
    """将 Case 阈值转成显式、可审计的逐项判定。"""
    exp = case.expectations
    checks: list[ExpectationCheck] = []

    def minimum(name: str, actual: float | int, expected: float | int | None) -> None:
        if expected is not None:
            checks.append(
                ExpectationCheck(
                    name=name,
                    passed=actual >= expected,
                    actual=actual,
                    expected=expected,
                    comparator=">=",
                )
            )

    def maximum(name: str, actual: float | int, expected: float | int | None) -> None:
        if expected is not None:
            checks.append(
                ExpectationCheck(
                    name=name,
                    passed=actual <= expected,
                    actual=actual,
                    expected=expected,
                    comparator="<=",
                )
            )

    minimum("citation_coverage", metrics.citation_coverage, exp.min_citation_coverage)
    minimum("task_success_rate", metrics.task_success_rate, exp.min_task_success_rate)
    minimum("unique_source_hosts", metrics.unique_source_hosts, exp.min_unique_source_hosts)
    maximum("unsupported_claims", metrics.unsupported_claims, exp.max_unsupported_claims)
    maximum("search_calls", metrics.search_calls, exp.max_search_calls)
    maximum("research_tokens", metrics.research_tokens, exp.max_research_tokens)
    maximum("wall_seconds", metrics.wall_seconds, exp.max_wall_seconds)
    if exp.min_keyword_recall is not None:
        actual = metrics.keyword_recall or 0.0
        minimum("keyword_recall", actual, exp.min_keyword_recall)
    return checks
