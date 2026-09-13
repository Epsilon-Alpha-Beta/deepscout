"""Final report writer node."""

import json

from langchain_core.messages import HumanMessage

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.llm import get_chat_model
from deepscout.prompts.writer import WRITER_PROMPT


def _json(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, list):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


async def writer(state: DeepScoutState) -> dict:
    model = get_chat_model(get_settings().model_for("writer"))
    message = await model.ainvoke(
        [
            HumanMessage(
                content=WRITER_PROMPT.format(
                    query=state["query"],
                    critique=_json(state.get("critique")),
                    results=_json(state.get("task_results", [])),
                )
            )
        ]
    )
    content = message.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, default=str)
    return {"final_report": content}
