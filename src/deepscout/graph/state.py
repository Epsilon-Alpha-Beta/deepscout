"""Shared LangGraph state."""

import operator
from typing import Annotated, TypedDict

from deepscout.models.budget import BudgetSnapshot
from deepscout.models.citation import CitationVerificationReport
from deepscout.models.evidence import ClaimEvidenceLink, ManagedEvidence
from deepscout.models.hitl import HumanReview
from deepscout.models.plan import QueryAnalysis, ResearchPlan
from deepscout.models.result import Critique, TaskResult


class DeepScoutState(TypedDict, total=False):
    query: str
    analysis: QueryAnalysis
    plan: ResearchPlan
    task_results: Annotated[list[TaskResult], operator.add]
    critique: Critique
    evidence_store: list[ManagedEvidence]
    claim_links: list[ClaimEvidenceLink]
    citation_report: CitationVerificationReport
    human_review: HumanReview
    require_approval: bool
    budget: BudgetSnapshot
    iteration: int
    replan_count: int
    final_report: str
