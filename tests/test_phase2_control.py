from deepscout.agents.citation_verifier import critique_from_verification
from deepscout.graph.routing import route_after_citation_verifier, route_after_critic
from deepscout.models.budget import BudgetSnapshot
from deepscout.models.citation import CitationVerificationReport
from deepscout.models.result import Critique


def _budget(replans_used: int = 0) -> BudgetSnapshot:
    return BudgetSnapshot(
        max_research_tasks=10,
        max_replans=2,
        max_evidence_items=20,
        research_tasks_attempted=2,
        replans_used=replans_used,
        evidence_items=3,
    )


def test_budget_can_replan_until_limit():
    assert _budget(0).can_replan
    assert not _budget(2).can_replan


def test_critic_replan_is_stopped_by_budget():
    critique = Critique(
        coverage_score=0.5,
        missing_aspects=["gap"],
        replan_required=True,
        reasoning_summary="gap",
    )
    assert route_after_critic({"critique": critique, "budget": _budget(0)}) == "planner"
    assert route_after_critic({"critique": critique, "budget": _budget(2)}) == "writer"


def test_citation_gap_becomes_planner_critique():
    report = CitationVerificationReport(
        coverage_score=0.4,
        unsupported_claims=["missing fact"],
        requires_research=True,
    )
    critique = critique_from_verification(report)
    assert critique.replan_required
    assert critique.missing_aspects == ["missing fact"]
    state = {"citation_report": report, "budget": _budget(0)}
    assert route_after_citation_verifier(state) == "planner"


def test_citation_gap_ends_when_replan_budget_is_exhausted():
    report = CitationVerificationReport(
        coverage_score=0.4,
        unsupported_claims=["missing fact"],
        requires_research=True,
    )
    state = {"citation_report": report, "budget": _budget(2)}
    assert route_after_citation_verifier(state) == "end"
