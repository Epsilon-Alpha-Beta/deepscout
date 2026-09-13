"""API graph runtime lifecycle."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from deepscout.config import Settings, get_settings
from deepscout.graph.builder import build_graph
from deepscout.runtime.checkpoint import memory_checkpointer, postgres_checkpointer


@asynccontextmanager
async def api_graph_runtime(settings: Settings | None = None) -> AsyncIterator[object]:
    """Build an API graph backed by memory or PostgreSQL checkpoints."""
    settings = settings or get_settings()
    if settings.api_checkpoint == "memory":
        yield build_graph(checkpointer=memory_checkpointer())
        return

    if not settings.postgres_dsn:
        raise RuntimeError("DEEPSCOUT_API_CHECKPOINT=postgres 时必须提供 DEEPSCOUT_POSTGRES_DSN。")
    async with postgres_checkpointer(settings.postgres_dsn) as saver:
        yield build_graph(checkpointer=saver)
