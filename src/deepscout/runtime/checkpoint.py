"""LangGraph checkpoint 工厂。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver


def memory_checkpointer() -> InMemorySaver:
    """用于本地开发、测试与故障恢复演示。"""
    return InMemorySaver()


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

    async with AsyncPostgresSaver.from_conn_string(dsn) as saver:
        if setup:
            await saver.setup()
        yield saver
