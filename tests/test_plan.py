import pytest

from deepscout.models.plan import (
    PlanExtension,
    ResearchPlan,
    ResearchTask,
    TaskType,
    extend_plan,
    validate_plan_graph,
)


def task(task_id, deps=None):
    return ResearchTask(
        id=task_id,
        question=f"Research {task_id}",
        task_type=TaskType.WEB_RESEARCH,
        dependencies=deps or [],
    )


def test_valid_dag():
    plan = ResearchPlan(goal="test", tasks=[task("T1"), task("T2"), task("T3", ["T1", "T2"])])
    assert validate_plan_graph(plan) is plan


def test_unknown_dependency_rejected():
    with pytest.raises(ValueError, match="unknown dependencies"):
        validate_plan_graph(ResearchPlan(goal="test", tasks=[task("T1", ["MISSING"])]))


def test_cycle_rejected():
    plan = ResearchPlan(goal="test", tasks=[task("T1", ["T2"]), task("T2", ["T1"])])
    with pytest.raises(ValueError, match="cycle"):
        validate_plan_graph(plan)


def test_extension_cannot_replace_existing_task():
    with pytest.raises(ValueError, match="reuse existing"):
        extend_plan(
            ResearchPlan(goal="test", tasks=[task("T1")]), PlanExtension(tasks=[task("T1")])
        )


def test_extension_can_depend_on_existing_task():
    merged = extend_plan(
        ResearchPlan(goal="test", tasks=[task("T1")]), PlanExtension(tasks=[task("T2", ["T1"])])
    )
    assert [item.id for item in merged.tasks] == ["T1", "T2"]
