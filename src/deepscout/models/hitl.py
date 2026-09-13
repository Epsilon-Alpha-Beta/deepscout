"""Human-in-the-loop review models."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class HumanReview(BaseModel):
    """Final-report review decision returned by a human or automatic bypass."""

    action: Literal["approve", "revise"]
    feedback: str | None = None
    source: Literal["human", "automatic"] = "human"

    @model_validator(mode="after")
    def require_feedback_for_revision(self):
        if self.action == "revise" and not (self.feedback or "").strip():
            raise ValueError("revise 决策必须提供 feedback。")
        return self


class HumanReviewRequest(BaseModel):
    """Payload surfaced through LangGraph interrupt()."""

    kind: Literal["final_report_review"] = "final_report_review"
    final_report: str
    citation_coverage: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str] = Field(default_factory=list)
