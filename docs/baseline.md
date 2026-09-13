# Baseline and attribution

## Reference baseline

DeepScout uses the public architecture of:

- `langchain-ai/deepagents`
- `examples/deep_research`

Reference:
https://github.com/langchain-ai/deepagents/tree/main/examples/deep_research

The baseline currently uses a DeepAgents orchestrator with a research sub-agent, Tavily search, a reflection tool, and fixed research/concurrency limits.

## Phase 1 differences

1. **Typed Research DAG** instead of prompt-only task planning.
2. **Deterministic DAG validation** before execution.
3. **Derived readiness** from immutable plan + append-only results.
4. **Dynamic parallel fan-out** with `Send`.
5. **DeepAgents only at the research-worker boundary.**
6. **Typed worker responses** instead of free-form parser-dependent output.
7. **Dedicated Critic** with bounded re-planning.
8. **Immutable existing tasks during plan extension.**

## Reproducibility

Phase 1 pins `deepagents==0.7.13` and Python `>=3.11,<4.0`. Live benchmark numbers are deliberately not included until baseline and DeepScout variants are executed under the same model/tool configuration.
