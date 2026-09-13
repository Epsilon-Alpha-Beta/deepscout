"""确定性的 DAG 调度与条件路由。"""

from langgraph.types import Send

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.models.plan import ResearchPlan, ResearchTask, TaskType
from deepscout.models.result import TaskResult


def completed_task_ids(results: list[TaskResult]) -> set[str]:
    return {result.task_id for result in results if result.status == "completed"}


def attempted_task_ids(results: list[TaskResult]) -> set[str]:
    return {result.task_id for result in results}


def find_ready_tasks(
    plan: ResearchPlan,
    results: list[TaskResult],
    *,
    limit: int | None = None,
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
    """按 DAG frontier、并发上限和 Research Worker 预算派发任务。"""
    results = state.get("task_results", [])
    budget = state["budget"]
    settings = get_settings()
    if not budget.can_dispatch:
        return "evidence_manager"

    limit = min(budget.remaining_research_tasks, settings.max_concurrency)
    ready = find_ready_tasks(state["plan"], results, limit=limit)
    if not ready:
        return "evidence_manager"

    remaining_searches = budget.remaining_searches
    sends: list[Send] = []
    for task in ready:
        search_quota = 0
        if task.task_type == TaskType.WEB_RESEARCH:
            if remaining_searches <= 0:
                continue
            desired = max(1, task.expected_sources)
            search_quota = min(
                desired,
                settings.search_max_calls_per_task,
                remaining_searches,
            )
            remaining_searches -= search_quota
        sends.append(
            Send(
                "researcher",
                {
                    "query": state["query"],
                    "task": task,
                    "task_results": results,
                    "search_quota": search_quota,
                },
            )
        )

    return sends or "evidence_manager"


def route_after_critic(state: DeepScoutState) -> str:
    critique = state["critique"]
    budget = state["budget"]
    if critique.replan_required and budget.can_replan:
        return "planner"
    return "writer"


def route_after_citation_verifier(state: DeepScoutState) -> str:
    report = state["citation_report"]
    budget = state["budget"]
    if report.requires_research and budget.can_replan:
        return "planner"
    return "end"
