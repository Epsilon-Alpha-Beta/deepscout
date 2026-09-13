"""DeepAgents-backed research worker."""

import json
import time
from functools import lru_cache

from deepagents import create_deep_agent

from deepscout.config import get_settings
from deepscout.llm import get_chat_model
from deepscout.models.plan import ResearchTask
from deepscout.models.result import ResearchOutput, TaskResult
from deepscout.prompts.researcher import RESEARCH_TASK_PROMPT, RESEARCHER_SYSTEM_PROMPT
from deepscout.runtime.search_budget import research_search_budget
from deepscout.tools.registry import get_research_tools


@lru_cache(maxsize=8)
def _get_research_agent(model_name: str):
    return create_deep_agent(
        model=get_chat_model(model_name),
        tools=get_research_tools(),
        system_prompt=RESEARCHER_SYSTEM_PROMPT,
        response_format=ResearchOutput,
        name="deepscout-researcher",
    )


def _serialize_dependency_results(results: list[TaskResult], task: ResearchTask) -> str:
    dependencies = set(task.dependencies)
    selected = [
        result.model_dump(mode="json")
        for result in results
        if result.task_id in dependencies and result.status == "completed"
    ]
    return json.dumps(selected, ensure_ascii=False, indent=2, default=str)


def _fallback_summary(result: dict) -> str:
    messages = result.get("messages", [])
    if not messages:
        return "Research worker completed without a structured response."
    content = getattr(messages[-1], "content", "")
    return (
        content
        if isinstance(content, str)
        else json.dumps(content, ensure_ascii=False, default=str)
    )


def _model_tokens(result: dict) -> int:
    total = 0
    for message in result.get("messages", []):
        usage = getattr(message, "usage_metadata", None)
        if not isinstance(usage, dict):
            continue
        value = usage.get("total_tokens")
        if value is None:
            value = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
        total += int(value or 0)
    return total


async def researcher(state: dict) -> dict:
    task: ResearchTask = state["task"]
    parent_results: list[TaskResult] = state.get("task_results", [])
    settings = get_settings()
    agent = _get_research_agent(settings.model_for("researcher"))
    prompt = RESEARCH_TASK_PROMPT.format(
        query=state["query"],
        task_id=task.id,
        task_type=task.task_type.value,
        question=task.question,
        expected_sources=task.expected_sources,
        dependency_context=_serialize_dependency_results(parent_results, task),
    )
    search_quota = max(0, int(state.get("search_quota", 0)))
    started = time.perf_counter()
    model_tokens = 0

    with research_search_budget(search_quota) as search_counter:
        try:
            result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
            model_tokens = _model_tokens(result)
            structured = result.get("structured_response")
            if isinstance(structured, ResearchOutput):
                output = structured
            elif structured is not None:
                output = ResearchOutput.model_validate(structured)
            else:
                output = ResearchOutput(summary=_fallback_summary(result), evidence=[])
            task_result = TaskResult(
                task_id=task.id,
                status="completed",
                summary=output.summary,
                evidence=output.evidence,
            )
        except Exception as exc:
            task_result = TaskResult(
                task_id=task.id,
                status="failed",
                summary="",
                evidence=[],
                error=f"{type(exc).__name__}: {exc}",
            )

    task_result.search_calls = search_counter.used
    task_result.model_tokens = model_tokens
    task_result.worker_seconds = time.perf_counter() - started
    return {"task_results": [task_result]}
