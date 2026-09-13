"""研究预算计算与运行时约束。"""

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.models.budget import BudgetSnapshot


def make_budget(state: DeepScoutState) -> BudgetSnapshot:
    """根据配置与 TaskResult 实际用量生成预算快照。"""
    settings = get_settings()
    results = state.get("task_results", [])
    return BudgetSnapshot(
        max_research_tasks=settings.max_research_tasks,
        max_replans=settings.max_replans,
        max_evidence_items=settings.max_evidence_items,
        max_searches=settings.max_searches,
        max_research_tokens=settings.max_research_tokens,
        max_worker_seconds=settings.max_worker_seconds,
        research_tasks_attempted=len(results),
        replans_used=state.get("replan_count", 0),
        evidence_items=len(state.get("evidence_store", [])),
        searches_used=sum(item.search_calls for item in results),
        research_tokens_used=sum(item.model_tokens for item in results),
        worker_seconds_used=sum(item.worker_seconds for item in results),
    )


def sync_budget(state: DeepScoutState) -> dict:
    """Supervisor 节点使用：把最新预算写回 Graph State。"""
    return {"budget": make_budget(state)}
