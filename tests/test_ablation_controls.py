import asyncio

import pytest
from langgraph.graph.state import CompiledStateGraph

from deepscout.config import get_settings, settings_override
from deepscout.evidence.manager import consolidate_evidence
from deepscout.graph.builder import build_graph
from deepscout.graph.options import GraphOptions
from deepscout.graph.routing import route_after_citation_verifier
from deepscout.models.budget import BudgetSnapshot
from deepscout.models.citation import CitationVerificationReport
from deepscout.models.evidence import Evidence
from deepscout.models.result import TaskResult


def test_settings_override_is_context_local_and_restored():
    original = get_settings().max_concurrency
    with settings_override({"max_concurrency": 1}) as effective:
        assert effective.max_concurrency == 1
        assert get_settings().max_concurrency == 1
    assert get_settings().max_concurrency == original


def test_settings_override_rejects_unknown_field():
    with (
        pytest.raises(ValueError, match="未知 Settings override"),
        settings_override({"not_a_setting": 1}),
    ):
        pass


def _replan_budget() -> BudgetSnapshot:
    return BudgetSnapshot(
        max_research_tasks=10,
        max_replans=2,
        max_evidence_items=20,
        research_tasks_attempted=1,
        replans_used=0,
        evidence_items=1,
    )


def test_citation_feedback_can_be_disabled_without_removing_measurement():
    state = {
        "citation_report": CitationVerificationReport(
            coverage_score=0.5,
            unsupported_claims=["missing"],
            requires_research=True,
        ),
        "budget": _replan_budget(),
    }
    assert route_after_citation_verifier(state, allow_replan=True) == "planner"
    assert route_after_citation_verifier(state, allow_replan=False) == "human_review"


def test_evidence_dedup_ablation_preserves_duplicate_observations():
    evidence = Evidence(title="A", url="https://example.com/a", content="same")
    result = TaskResult(
        task_id="T1",
        status="completed",
        summary="ok",
        evidence=[evidence, evidence.model_copy()],
    )
    deduped = consolidate_evidence([result], max_items=10, deduplicate=True)
    raw = consolidate_evidence([result], max_items=10, deduplicate=False)
    assert len(deduped) == 1
    assert deduped[0].duplicate_count == 2
    assert len(raw) == 2
    assert raw[0].evidence_id != raw[1].evidence_id


def test_graph_compiles_with_ablation_options():
    graph = build_graph(
        options=GraphOptions(
            citation_feedback_enabled=False,
            evidence_dedup_enabled=False,
        )
    )
    assert isinstance(graph, CompiledStateGraph)


@pytest.mark.asyncio
async def test_settings_override_propagates_to_asyncio_child_task():
    async def read_concurrency() -> int:
        return get_settings().max_concurrency

    with settings_override({"max_concurrency": 1}):
        assert await asyncio.create_task(read_concurrency()) == 1
