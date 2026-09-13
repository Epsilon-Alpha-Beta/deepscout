"""研究预算状态模型。"""

from pydantic import BaseModel, Field


class BudgetSnapshot(BaseModel):
    """从当前 Graph State 推导出的 Research Worker 预算快照。"""

    max_research_tasks: int = Field(ge=1)
    max_replans: int = Field(ge=0)
    max_evidence_items: int = Field(ge=1)
    max_searches: int = Field(default=40, ge=1)
    max_research_tokens: int = Field(default=200000, ge=1)
    max_worker_seconds: float = Field(default=900.0, gt=0.0)
    research_tasks_attempted: int = Field(ge=0)
    replans_used: int = Field(ge=0)
    evidence_items: int = Field(ge=0)
    searches_used: int = Field(default=0, ge=0)
    research_tokens_used: int = Field(default=0, ge=0)
    worker_seconds_used: float = Field(default=0.0, ge=0.0)

    @property
    def remaining_research_tasks(self) -> int:
        return max(0, self.max_research_tasks - self.research_tasks_attempted)

    @property
    def remaining_replans(self) -> int:
        return max(0, self.max_replans - self.replans_used)

    @property
    def remaining_searches(self) -> int:
        return max(0, self.max_searches - self.searches_used)

    @property
    def remaining_research_tokens(self) -> int:
        return max(0, self.max_research_tokens - self.research_tokens_used)

    @property
    def remaining_worker_seconds(self) -> float:
        return max(0.0, self.max_worker_seconds - self.worker_seconds_used)

    @property
    def can_dispatch(self) -> bool:
        return (
            self.remaining_research_tasks > 0
            and self.remaining_research_tokens > 0
            and self.remaining_worker_seconds > 0
        )

    @property
    def can_replan(self) -> bool:
        return self.remaining_replans > 0 and self.can_dispatch and self.remaining_searches > 0
