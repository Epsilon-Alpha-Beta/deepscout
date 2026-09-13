# DeepScout

**Production-grade multi-agent deep research system built with LangGraph + DeepAgents.**

DeepScout starts from the architectural ideas in LangChain's `deepagents/examples/deep_research` baseline, but moves orchestration into an explicit LangGraph workflow:

- structured query analysis;
- dependency-aware Research DAG planning;
- deterministic DAG validation;
- dynamic parallel dispatch with LangGraph `Send`;
- DeepAgents-powered autonomous research workers;
- structured `TaskResult` + `Evidence` outputs;
- Critic-driven gap analysis and bounded re-planning;
- final synthesis using only collected evidence.

> Phase 1 deliberately focuses on agent orchestration. Persistence, MCP routing,
> citation verification, budget control, FastAPI/SSE, PostgreSQL, Redis, and the
> full evaluation suite are Phase 2+ work.

## Architecture

```text
START
  |
  v
analyze_query
  |
  v
planner  <------------------------+
  |                               |
  v                               |
supervisor                        |
  |                               |
  +---- ready tasks ----+         |
  |                     |         |
  v                     v         |
researcher ...      researcher    |
  |                     |         |
  +----------+----------+         |
             |                    |
             v                    |
         supervisor               |
             |                    |
       DAG exhausted              |
             v                    |
           critic                 |
          /      \                |
     re-plan      sufficient -----+
        |              |
        +--------------+
                       v
                     writer
                       |
                       v
                      END
```

The key design choice is:

> **LangGraph owns deterministic orchestration; DeepAgents owns local autonomous research.**

This prevents task dependency, retry boundaries, and control flow from being left entirely to an LLM prompt.

## Upstream baseline

Reference project:

- https://github.com/langchain-ai/deepagents
- `examples/deep_research`

Phase 1 is pinned to `deepagents==0.7.13` for reproducibility.

DeepScout is a separate implementation and does **not** claim the upstream DeepAgents code as original work. See [`docs/baseline.md`](docs/baseline.md).

## Phase 1 capabilities

### 1. Structured Research DAG

The planner emits typed tasks and DeepScout rejects duplicate task IDs, unknown dependencies, self-dependencies, and cycles.

### 2. Dependency-aware parallel scheduling

The supervisor derives state instead of mutating task status. Independent ready tasks are fanned out in parallel with LangGraph `Send`.

### 3. DeepAgents Research Worker

Each research task is delegated to a cached DeepAgent with an explicit model, web-search tools, a research system prompt, and a typed structured response schema.

### 4. Critic + bounded re-planning

After the current DAG is exhausted, the Critic checks coverage, missing aspects, conflicts, and failed tasks. Existing tasks are immutable; only new task IDs may be appended.

## Setup

Requirements: Python 3.11+, `uv`, one supported LLM provider API key, and Tavily API key.

```bash
git clone https://github.com/Epsilon-Alpha-Beta/deepscout.git
cd deepscout
cp .env.example .env
uv sync --group dev
```

Run tests:

```bash
uv run pytest
uv run ruff check .
```

Run a research query:

```bash
uv run python scripts/run_research.py "Compare LangGraph, AutoGen and CrewAI for production multi-agent systems."
```

## Roadmap

**Phase 2**: Evidence Manager, source deduplication, claim-evidence mapping, Citation Verifier, budget manager.

**Phase 3**: MCP Tool Registry, PostgreSQL checkpointing, retries/failure recovery, HITL, FastAPI + SSE.

**Phase 4**: benchmark dataset, trajectory evaluation, ablations, cost/latency/quality dashboards.
