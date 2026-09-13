# Phase 1 Architecture

DeepScout splits responsibilities across two levels. LangGraph owns query analysis, plan validation, dependency scheduling, fan-out/fan-in, critic routing, and bounded re-planning. DeepAgents owns the autonomous single-task researcher, including tool use, context handling, and typed research response.

Global state is mostly overwrite-by-node, except `task_results: Annotated[list[TaskResult], operator.add]`. Readiness is derived from immutable plan + append-only results.

A failed task is attempted but not completed. Tasks depending on it remain blocked; when no ready tasks remain, control goes to the Critic for bounded re-planning. Existing tasks are immutable during re-planning.

Phase 1 intentionally does not implement citation entailment verification, evidence deduplication, MCP routing, PostgreSQL checkpointing, Redis, FastAPI/SSE, long-term memory, or cost budget enforcement.
