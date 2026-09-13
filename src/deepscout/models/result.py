"""Research execution and critique schemas."""

from typing import Literal

from pydantic import BaseModel, Field

from deepscout.models.evidence import Evidence


class ResearchOutput(BaseModel):
    summary: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)


class TaskResult(BaseModel):
    task_id: str
    status: Literal["completed", "failed"]
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)
    error: str | None = None


class Critique(BaseModel):
    coverage_score: float = Field(ge=0.0, le=1.0)
    missing_aspects: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    failed_task_ids: list[str] = Field(default_factory=list)
    replan_required: bool
    reasoning_summary: str = Field(min_length=1)
