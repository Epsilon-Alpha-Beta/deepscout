from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deepscout.agents.human_review import human_review
from deepscout.graph.routing import route_after_human_review
from deepscout.graph.state import DeepScoutState
from deepscout.models.budget import BudgetSnapshot
from deepscout.models.citation import CitationVerificationReport


def _budget() -> BudgetSnapshot:
    return BudgetSnapshot(
        max_research_tasks=10,
        max_replans=2,
        max_evidence_items=20,
        research_tasks_attempted=1,
        replans_used=0,
        evidence_items=2,
    )


def _citation() -> CitationVerificationReport:
    return CitationVerificationReport(
        coverage_score=1.0,
        unsupported_claims=[],
        requires_research=False,
    )


def test_human_review_bypasses_when_not_required():
    result = human_review(
        {
            "require_approval": False,
            "final_report": "report",
            "citation_report": _citation(),
        }
    )
    assert result["human_review"].action == "approve"
    assert result["human_review"].source == "automatic"


def test_human_review_interrupt_and_resume():
    builder = StateGraph(DeepScoutState)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    graph = builder.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "hitl-test"}}

    first = graph.invoke(
        {
            "require_approval": True,
            "final_report": "report",
            "citation_report": _citation(),
            "budget": _budget(),
            "task_results": [],
        },
        config,
    )
    assert "__interrupt__" in first
    assert first["__interrupt__"][0].value["kind"] == "final_report_review"

    resumed = graph.invoke(Command(resume={"action": "approve"}), config)
    assert resumed["human_review"].action == "approve"
    assert resumed["human_review"].source == "human"


def test_revision_routes_back_to_planner_when_budget_allows():
    from deepscout.models.hitl import HumanReview

    state = {
        "human_review": HumanReview(action="revise", feedback="补充最新官方数据"),
        "budget": _budget(),
    }
    assert route_after_human_review(state) == "planner"
