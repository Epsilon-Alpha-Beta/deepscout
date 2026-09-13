"""验证 PostgreSQL checkpoint 能跨进程恢复 HITL。"""

import argparse
import asyncio

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from deepscout.agents.human_review import human_review
from deepscout.graph.state import DeepScoutState
from deepscout.runtime.checkpoint import postgres_checkpointer


def _build_graph(checkpointer):
    builder = StateGraph(DeepScoutState)
    builder.add_node("human_review", human_review)
    builder.add_edge(START, "human_review")
    builder.add_edge("human_review", END)
    return builder.compile(checkpointer=checkpointer)


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def _pause(dsn: str, thread_id: str) -> None:
    async with postgres_checkpointer(dsn) as saver:
        graph = _build_graph(saver)
        result = await graph.ainvoke(
            {
                "query": "postgres recovery integration test",
                "task_results": [],
                "require_approval": True,
                "final_report": "integration-test draft",
            },
            _config(thread_id),
        )
        interrupts = result.get("__interrupt__", [])
        if not interrupts:
            raise RuntimeError("Graph did not pause at human_review.")
        snapshot = await graph.aget_state(_config(thread_id))
        if snapshot.next != ("human_review",):
            raise RuntimeError(f"Unexpected next nodes: {snapshot.next}")
        print(f"paused thread={thread_id} interrupt_id={interrupts[0].id}")


async def _resume(dsn: str, thread_id: str) -> None:
    async with postgres_checkpointer(dsn, setup=False) as saver:
        graph = _build_graph(saver)
        before = await graph.aget_state(_config(thread_id))
        if before.next != ("human_review",):
            raise RuntimeError(f"Checkpoint is not resumable: {before.next}")
        result = await graph.ainvoke(
            Command(resume={"action": "approve"}),
            _config(thread_id),
        )
        review = result.get("human_review")
        action = getattr(review, "action", None)
        if action is None and isinstance(review, dict):
            action = review.get("action")
        if action != "approve":
            raise RuntimeError(f"Unexpected human review result: {review!r}")
        after = await graph.aget_state(_config(thread_id))
        if after.next:
            raise RuntimeError(f"Graph did not finish after resume: {after.next}")
        print(f"resumed thread={thread_id} action={action} next={after.next}")


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 PostgreSQL checkpoint 跨进程恢复。")
    parser.add_argument("mode", choices=("pause", "resume"))
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--thread-id", required=True)
    args = parser.parse_args()
    operation = _pause if args.mode == "pause" else _resume
    asyncio.run(operation(args.dsn, args.thread_id))


if __name__ == "__main__":
    main()
