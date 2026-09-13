"""Planner prompts."""

INITIAL_PLAN_PROMPT = """
You are DeepScout's research planner.
Convert the user's research objective into a small dependency-aware DAG.

Rules:
1. Create atomic tasks and maximize safe parallelism.
2. Use dependencies only when necessary.
3. Keep IDs simple (T1, T2, ...).
4. Produce an acyclic graph with no missing dependency references.
5. Avoid redundant tasks.

User query:
{query}

Query analysis:
{analysis}
"""

REPLAN_PROMPT = """
You are DeepScout's re-planner.
Propose ONLY NEW tasks needed to close the Critic's material coverage gaps.
Do not repeat or modify existing tasks. Every new task ID must be globally
unique. New tasks may depend on existing task IDs or earlier new task IDs.
Return an empty task list if no additional research is useful.

Original query:
{query}

Existing plan:
{plan}

Existing results:
{results}

Critique:
{critique}
"""
