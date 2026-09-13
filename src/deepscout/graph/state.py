"""Shared LangGraph state."""

import operator
from typing import Annotated, TypedDict

from deepscout.models.plan import QueryAnalysis, ResearchPlan
from deepscout.models.result import Critique, TaskResult


class DeepScoutState(TypedDict, total=False):
    query: str
    analysis: QueryAnalysis
    plan: ResearchPlan
    task_results: Annotated[list[TaskResult], operator.add]
    critique: Critique
    iteration: int
    final_report: str
