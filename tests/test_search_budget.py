from deepscout.graph.routing import dispatch_ready_tasks
from deepscout.models.budget import BudgetSnapshot
from deepscout.models.plan import ResearchPlan, ResearchTask, TaskType
from deepscout.runtime.search_budget import consume_search, research_search_budget


def _task(task_id: str, task_type: TaskType = TaskType.WEB_RESEARCH) -> ResearchTask:
    return ResearchTask(
        id=task_id,
        question=f"Research {task_id}",
        task_type=task_type,
        expected_sources=3,
    )


def _budget(searches_used: int = 0) -> BudgetSnapshot:
    return BudgetSnapshot(
        max_research_tasks=10,
        max_replans=2,
        max_evidence_items=20,
        max_searches=2,
        research_tasks_attempted=0,
        replans_used=0,
        evidence_items=0,
        searches_used=searches_used,
    )


def test_context_search_budget_is_hard_limit():
    with research_search_budget(2) as counter:
        assert consume_search()
        assert consume_search()
        assert not consume_search()
        assert counter.used == 2


def test_dispatch_allocates_global_search_budget_across_parallel_tasks():
    plan = ResearchPlan(goal="test", tasks=[_task("T1"), _task("T2")])
    sends = dispatch_ready_tasks(
        {"query": "test", "plan": plan, "task_results": [], "budget": _budget()}
    )
    assert isinstance(sends, list)
    assert sum(send.arg["search_quota"] for send in sends) == 2
    assert all(send.arg["search_quota"] > 0 for send in sends)


def test_synthesis_can_run_when_search_budget_is_exhausted():
    plan = ResearchPlan(goal="test", tasks=[_task("T1", TaskType.SYNTHESIS)])
    sends = dispatch_ready_tasks(
        {"query": "test", "plan": plan, "task_results": [], "budget": _budget(2)}
    )
    assert isinstance(sends, list)
    assert len(sends) == 1
    assert sends[0].arg["search_quota"] == 0


def test_web_search_does_not_call_provider_after_budget_exhaustion():
    import json

    from deepscout.tools.web_search import web_search

    with research_search_budget(0) as counter:
        payload = json.loads(web_search.invoke({"query": "no network call"}))
    assert payload["error"] == "search_budget_exhausted"
    assert counter.used == 0
