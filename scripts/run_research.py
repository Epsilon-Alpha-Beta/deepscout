"""从命令行运行一次 DeepScout 研究任务。"""

import argparse
import asyncio
import os

from deepscout.graph.builder import build_graph
from deepscout.runtime.checkpoint import memory_checkpointer, postgres_checkpointer


def _input_state(query: str) -> dict:
    return {"query": query, "task_results": [], "iteration": 0}


def _run_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def _invoke(query: str, checkpoint: str, thread_id: str, postgres_dsn: str | None):
    state = _input_state(query)
    if checkpoint == "none":
        return await build_graph().ainvoke(state)
    if checkpoint == "memory":
        graph = build_graph(checkpointer=memory_checkpointer())
        return await graph.ainvoke(state, _run_config(thread_id))
    if not postgres_dsn:
        raise ValueError("使用 postgres checkpoint 时必须提供 PostgreSQL DSN。")
    async with postgres_checkpointer(postgres_dsn) as saver:
        graph = build_graph(checkpointer=saver)
        return await graph.ainvoke(state, _run_config(thread_id))


async def _main(args: argparse.Namespace) -> None:
    result = await _invoke(
        args.query,
        args.checkpoint,
        args.thread_id,
        args.postgres_dsn,
    )
    print(result.get("final_report", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 DeepScout 研究任务。")
    parser.add_argument("query")
    parser.add_argument(
        "--checkpoint",
        choices=("none", "memory", "postgres"),
        default="none",
    )
    parser.add_argument("--thread-id", default="deepscout-cli")
    parser.add_argument(
        "--postgres-dsn",
        default=os.getenv("DEEPSCOUT_POSTGRES_DSN"),
        help="PostgreSQL checkpoint DSN，也可通过 DEEPSCOUT_POSTGRES_DSN 提供。",
    )
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
