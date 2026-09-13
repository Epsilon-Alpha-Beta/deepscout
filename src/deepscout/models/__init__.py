"""Typed domain models."""

from deepscout.models.evidence import Evidence
from deepscout.models.plan import PlanExtension, QueryAnalysis, ResearchPlan, ResearchTask, TaskType
from deepscout.models.result import Critique, ResearchOutput, TaskResult

__all__ = [
    "Critique",
    "Evidence",
    "PlanExtension",
    "QueryAnalysis",
    "ResearchOutput",
    "ResearchPlan",
    "ResearchTask",
    "TaskResult",
    "TaskType",
]
