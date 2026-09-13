"""FastAPI request/response schemas."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1)
    thread_id: str | None = None
    require_approval: bool = False


class ResumeRequest(BaseModel):
    action: Literal["approve", "revise"]
    feedback: str | None = None

    @model_validator(mode="after")
    def require_feedback_for_revision(self):
        if self.action == "revise" and not (self.feedback or "").strip():
            raise ValueError("revise 决策必须提供 feedback。")
        return self


class ResearchResponse(BaseModel):
    thread_id: str
    status: Literal["completed", "interrupted"]
    final_report: str | None = None
    interrupts: list[dict] = Field(default_factory=list)


class ThreadStateResponse(BaseModel):
    thread_id: str
    next_nodes: list[str] = Field(default_factory=list)
    values: dict = Field(default_factory=dict)
