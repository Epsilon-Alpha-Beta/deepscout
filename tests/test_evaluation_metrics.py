from deepscout.evaluation.metrics import calculate_metrics, evaluate_expectations
from deepscout.evaluation.models import (
    BenchmarkCase,
    BenchmarkExpectations,
    BenchmarkPricing,
    TrajectoryEvent,
)


def _case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="fixture",
        query="比较 LangGraph 与 MCP",
        category="architecture",
        expected_keywords=["LangGraph", "MCP"],
        expectations=BenchmarkExpectations(
            min_citation_coverage=0.8,
            min_task_success_rate=0.5,
            min_unique_source_hosts=2,
            max_unsupported_claims=1,
            max_search_calls=5,
            max_research_tokens=5000,
            min_keyword_recall=1.0,
        ),
    )


def _state() -> dict:
    return {
        "task_results": [
            {"status": "completed", "search_calls": 2, "model_tokens": 1000, "worker_seconds": 1.5},
            {"status": "failed", "search_calls": 1, "model_tokens": 500, "worker_seconds": 0.5},
        ],
        "evidence_store": [
            {"source_host": "a.example", "relevance_score": 0.9},
            {"source_host": "b.example", "relevance_score": 0.7},
        ],
        "citation_report": {"coverage_score": 0.8, "unsupported_claims": ["x"]},
        "replan_count": 1,
        "final_report": "LangGraph 可以通过 MCP 接入外部工具。",
    }


def test_calculate_metrics_and_expectations():
    trajectory = [
        TrajectoryEvent(sequence=0, node="planner", elapsed_ms=1, output_keys=["plan"]),
        TrajectoryEvent(sequence=1, node="researcher", elapsed_ms=2, output_keys=["task_results"]),
        TrajectoryEvent(sequence=2, node="planner", elapsed_ms=3, output_keys=["plan"]),
    ]
    metrics = calculate_metrics(
        _case(),
        _state(),
        trajectory,
        wall_seconds=2.5,
        pricing=BenchmarkPricing(
            research_token_usd_per_million=10,
            search_usd_per_1000_calls=5,
        ),
    )
    assert metrics.node_visits == {"planner": 2, "researcher": 1}
    assert metrics.task_success_rate == 0.5
    assert metrics.unique_source_hosts == 2
    assert metrics.source_diversity_ratio == 1.0
    assert metrics.average_evidence_relevance == 0.8
    assert metrics.citation_coverage == 0.8
    assert metrics.keyword_recall == 1.0
    assert metrics.search_calls == 3
    assert metrics.research_tokens == 1500
    assert metrics.research_token_cost_usd == 0.015
    assert metrics.search_cost_usd == 0.015
    assert metrics.estimated_tracked_cost_usd == 0.03
    assert all(check.passed for check in evaluate_expectations(_case(), metrics))


def test_cost_is_not_fabricated_without_pricing():
    metrics = calculate_metrics(_case(), _state(), [], wall_seconds=0.1)
    assert metrics.research_token_cost_usd is None
    assert metrics.search_cost_usd is None
    assert metrics.estimated_tracked_cost_usd is None
