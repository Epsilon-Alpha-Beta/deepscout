from deepscout.graph.routing import all_tasks_attempted, find_ready_tasks
from deepscout.models.plan import ResearchPlan, ResearchTask, TaskType
from deepscout.models.result import TaskResult


def task(task_id, deps=None, priority=0):
    return ResearchTask(
        id=task_id,
        question=f"Research {task_id}",
        task_type=TaskType.WEB_RESEARCH,
        dependencies=deps or [],
        priority=priority,
    )


def completed(task_id):
    return TaskResult(task_id=task_id, status="completed", summary="done")


def failed(task_id):
    return TaskResult(task_id=task_id, status="failed", summary="", error="boom")


def sample_plan():
    return ResearchPlan(
        goal="compare",
        tasks=[
            task("T1", priority=10),
            task("T2", priority=5),
            task("T3", priority=1),
            task("T4", ["T1", "T2", "T3"]),
        ],
    )


def test_initial_parallel_frontier():
    assert [item.id for item in find_ready_tasks(sample_plan(), [])] == ["T1", "T2", "T3"]


def test_dependency_unlocks_after_successes():
    assert [
        item.id
        for item in find_ready_tasks(
            sample_plan(), [completed("T1"), completed("T2"), completed("T3")]
        )
    ] == ["T4"]


def test_limit_applies_after_priority_sort():
    assert [item.id for item in find_ready_tasks(sample_plan(), [], limit=2)] == ["T1", "T2"]


def test_failed_dependency_blocks_downstream_task():
    assert find_ready_tasks(sample_plan(), [completed("T1"), completed("T2"), failed("T3")]) == []


def test_all_tasks_attempted_tracks_terminal_round():
    assert all_tasks_attempted(
        sample_plan(), [completed("T1"), completed("T2"), completed("T3"), completed("T4")]
    )
