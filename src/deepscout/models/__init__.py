"""Typed domain models."""

from deepscout.models.budget import BudgetSnapshot
from deepscout.models.citation import CitationCheck, CitationVerificationReport
from deepscout.models.evidence import ClaimEvidenceLink, Evidence, ManagedEvidence
from deepscout.models.plan import PlanExtension, QueryAnalysis, ResearchPlan, ResearchTask, TaskType
from deepscout.models.result import Critique, ResearchOutput, TaskResult

__all__ = [
    "BudgetSnapshot",
    "CitationCheck",
    "CitationVerificationReport",
    "ClaimEvidenceLink",
    "Critique",
    "Evidence",
    "ManagedEvidence",
    "PlanExtension",
    "QueryAnalysis",
    "ResearchOutput",
    "ResearchPlan",
    "ResearchTask",
    "TaskResult",
    "TaskType",
]
