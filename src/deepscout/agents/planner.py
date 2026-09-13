"""Research DAG planner node."""

import json

from langchain_core.messages import HumanMessage

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.llm import get_chat_model
from deepscout.models.plan import PlanExtension, ResearchPlan, extend_plan, validate_plan_graph
from deepscout.prompts.planner import INITIAL_PLAN_PROMPT, REPLAN_PROMPT


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def planner(state: DeepScoutState) -> dict:
    settings = get_settings()
    model = get_chat_model(settings.model_for("planner"))
    existing_plan = state.get("plan")
    if existing_plan is None:
        structured = model.with_structured_output(ResearchPlan)
        prompt = INITIAL_PLAN_PROMPT.format(
            query=state["query"], analysis=_json(state.get("analysis"))
        )
        last_error = None
        for _ in range(settings.planner_retries + 1):
            try:
                candidate = await structured.ainvoke([HumanMessage(content=prompt)])
                return {"plan": validate_plan_graph(candidate)}
            except (ValueError, TypeError) as exc:
                last_error = exc
                prompt += (
                    "\n\nPrevious plan failed deterministic validation: "
                    f"{exc}. Return a corrected DAG."
                )
        raise RuntimeError("Planner failed to produce a valid Research DAG.") from last_error
    critique = state.get("critique")
    if critique is None or not critique.replan_required:
        return {"plan": existing_plan}
    structured = model.with_structured_output(PlanExtension)
    prompt = REPLAN_PROMPT.format(
        query=state["query"],
        plan=_json(existing_plan),
        results=_json(state.get("task_results", [])),
        critique=_json(critique),
    )
    last_error = None
    for _ in range(settings.planner_retries + 1):
        try:
            extension = await structured.ainvoke([HumanMessage(content=prompt)])
            return {
                "plan": extend_plan(existing_plan, extension),
                "replan_count": state.get("replan_count", 0) + 1,
            }
        except (ValueError, TypeError) as exc:
            last_error = exc
            prompt += (
                "\n\nPlan extension failed deterministic validation: "
                f"{exc}. Return corrected NEW tasks only."
            )
    raise RuntimeError("Re-planner failed to produce a valid plan extension.") from last_error
