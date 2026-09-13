"""LangGraph checkpoint 工厂与安全序列化配置。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

_DEEPSCOUT_MSGPACK_ALLOWLIST = [
    ("deepscout.models.budget", "BudgetSnapshot"),
    ("deepscout.models.citation", "CitationCheck"),
    ("deepscout.models.citation", "CitationVerificationReport"),
    ("deepscout.models.evidence", "Evidence"),
    ("deepscout.models.evidence", "ManagedEvidence"),
    ("deepscout.models.evidence", "ClaimEvidenceLink"),
    ("deepscout.models.hitl", "HumanReview"),
    ("deepscout.models.plan", "QueryAnalysis"),
    ("deepscout.models.plan", "ResearchTask"),
    ("deepscout.models.plan", "ResearchPlan"),
    ("deepscout.models.plan", "PlanExtension"),
    ("deepscout.models.plan", "TaskType"),
    ("deepscout.models.result", "ResearchOutput"),
    ("deepscout.models.result", "TaskResult"),
    ("deepscout.models.result", "Critique"),
]


def deepscout_serializer() -> JsonPlusSerializer:
    """只允许 DeepScout 已知状态模型参与 msgpack 反序列化。"""
    return JsonPlusSerializer(
        allowed_msgpack_modules=_DEEPSCOUT_MSGPACK_ALLOWLIST,
    )


def memory_checkpointer() -> InMemorySaver:
    """用于本地开发、测试与故障恢复演示。"""
    return InMemorySaver(serde=deepscout_serializer())


@asynccontextmanager
async def postgres_checkpointer(
    dsn: str,
    *,
    setup: bool = True,
) -> AsyncIterator[BaseCheckpointSaver]:
    """创建生产用 AsyncPostgresSaver，并管理连接生命周期。"""
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:
        raise RuntimeError("PostgreSQL checkpoint 需要安装 `uv sync --extra postgres`。") from exc

    async with AsyncPostgresSaver.from_conn_string(
        dsn,
        serde=deepscout_serializer(),
    ) as saver:
        if setup:
            await saver.setup()
        yield saver
