"""Deterministic DAG scheduling and conditional routing."""

from langgraph.types import Send

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.models.plan import ResearchPlan, ResearchTask
from deepscout.models.result import TaskResult


def completed_task_ids(results: list[TaskResult]) -> set[str]:
    return {result.task_id for result in results if result.status == "completed"}


def attempted_task_ids(results: list[TaskResult]) -> set[str]:
    return {result.task_id for result in results}


def find_ready_tasks(
    plan: ResearchPlan, results: list[TaskResult], *, limit: int | None = None
) -> list[ResearchTask]:
    completed = completed_task_ids(results)
    attempted = attempted_task_ids(results)
    ready = [
        task
        for task in plan.tasks
        if task.id not in attempted
        and all(dependency in completed for dependency in task.dependencies)
    ]
    ready.sort(key=lambda task: (-task.priority, task.id))
    return ready[:limit] if limit is not None else ready


def all_tasks_attempted(plan: ResearchPlan, results: list[TaskResult]) -> bool:
    return {task.id for task in plan.tasks}.issubset(attempted_task_ids(results))


def dispatch_ready_tasks(state: DeepScoutState):
    results = state.get("task_results", [])
    ready = find_ready_tasks(state["plan"], results, limit=get_settings().max_concurrency)
    if not ready:
        return "critic"
    return [
        Send("researcher", {"query": state["query"], "task": task, "task_results": results})
        for task in ready
    ]


def route_after_critic(state: DeepScoutState) -> str:
    critique = state["critique"]
    settings = get_settings()
    if critique.replan_required and state.get("iteration", 0) <= settings.max_replans:
        return "planner"
    return "writer"
