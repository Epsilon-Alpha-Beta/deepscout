"""Research planning schemas and deterministic DAG validation."""

from enum import StrEnum

from pydantic import BaseModel, Field


class TaskType(StrEnum):
    WEB_RESEARCH = "web_research"
    SYNTHESIS = "synthesis"


class QueryAnalysis(BaseModel):
    normalized_query: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    key_entities: list[str] = Field(default_factory=list)
    comparison_required: bool = False
    freshness_required: bool = False
    estimated_complexity: int = Field(default=2, ge=1, le=5)


class ResearchTask(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    question: str = Field(min_length=1)
    task_type: TaskType = TaskType.WEB_RESEARCH
    dependencies: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=-100, le=100)
    expected_sources: int = Field(default=3, ge=0, le=20)


class ResearchPlan(BaseModel):
    goal: str = Field(min_length=1)
    tasks: list[ResearchTask] = Field(min_length=1)


class PlanExtension(BaseModel):
    tasks: list[ResearchTask] = Field(default_factory=list)


def validate_plan_graph(plan: ResearchPlan) -> ResearchPlan:
    task_map = {task.id: task for task in plan.tasks}
    if len(task_map) != len(plan.tasks):
        raise ValueError("Research plan contains duplicate task IDs.")
    for task in plan.tasks:
        if task.id in task.dependencies:
            raise ValueError(f"Task {task.id} depends on itself.")
        unknown = sorted(set(task.dependencies) - task_map.keys())
        if unknown:
            raise ValueError(f"Task {task.id} references unknown dependencies: {unknown}.")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise ValueError(f"Research plan contains a cycle at {task_id}.")
        visiting.add(task_id)
        for dependency in task_map[task_id].dependencies:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in task_map:
        visit(task_id)
    return plan


def extend_plan(existing: ResearchPlan, extension: PlanExtension) -> ResearchPlan:
    existing_ids = {task.id for task in existing.tasks}
    new_ids = [task.id for task in extension.tasks]
    duplicates = existing_ids.intersection(new_ids)
    if duplicates:
        raise ValueError(
            f"Plan extension attempted to reuse existing task IDs: {sorted(duplicates)}."
        )
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("Plan extension contains duplicate task IDs.")
    merged = ResearchPlan(goal=existing.goal, tasks=[*existing.tasks, *extension.tasks])
    return validate_plan_graph(merged)
