"""Coverage-critic node."""

import json

from langchain_core.messages import HumanMessage

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.llm import get_chat_model
from deepscout.models.result import Critique
from deepscout.prompts.critic import CRITIC_PROMPT


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def critic(state: DeepScoutState) -> dict:
    settings = get_settings()
    structured = get_chat_model(settings.model_for("critic")).with_structured_output(Critique)
    critique = await structured.ainvoke(
        [
            HumanMessage(
                content=CRITIC_PROMPT.format(
                    query=state["query"],
                    plan=_json(state["plan"]),
                    results=_json(state.get("task_results", [])),
                )
            )
        ]
    )
    return {"critique": critique, "iteration": state.get("iteration", 0) + 1}
