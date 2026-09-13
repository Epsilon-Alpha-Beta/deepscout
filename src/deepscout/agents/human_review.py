"""Human review gate for the final report."""

from langgraph.types import interrupt

from deepscout.graph.state import DeepScoutState
from deepscout.models.hitl import HumanReview, HumanReviewRequest
from deepscout.models.result import Critique


def human_review(state: DeepScoutState) -> dict:
    """Optionally pause execution and collect an approve/revise decision."""
    if not state.get("require_approval", False):
        return {"human_review": HumanReview(action="approve", source="automatic")}

    citation = state.get("citation_report")
    request = HumanReviewRequest(
        final_report=state.get("final_report", ""),
        citation_coverage=citation.coverage_score if citation is not None else 0.0,
        unsupported_claims=citation.unsupported_claims if citation is not None else [],
    )
    response = interrupt(request.model_dump(mode="json"))
    review = HumanReview.model_validate(response)
    updates: dict[str, object] = {"human_review": review}

    if review.action == "revise":
        feedback = (review.feedback or "").strip()
        updates["critique"] = Critique(
            coverage_score=citation.coverage_score if citation is not None else 0.0,
            missing_aspects=[feedback],
            conflicts=[],
            failed_task_ids=[],
            replan_required=True,
            reasoning_summary="人工审核要求根据反馈补充研究并修订最终报告。",
        )
    return updates
