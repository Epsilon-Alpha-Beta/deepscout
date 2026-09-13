"""Query-analysis node."""

from langchain_core.messages import HumanMessage

from deepscout.config import get_settings
from deepscout.graph.state import DeepScoutState
from deepscout.llm import get_chat_model
from deepscout.models.plan import QueryAnalysis


def _fallback_analysis(query: str) -> QueryAnalysis:
    lowered = query.lower()
    comparison_markers = ("compare", "comparison", "versus", " vs ", "对比", "比较")
    freshness_markers = ("latest", "current", "today", "recent", "最新", "目前", "当前")
    return QueryAnalysis(
        normalized_query=query.strip(),
        objective=query.strip(),
        comparison_required=any(marker in lowered for marker in comparison_markers),
        freshness_required=any(marker in lowered for marker in freshness_markers),
        estimated_complexity=2,
    )


async def analyze_query(state: DeepScoutState) -> dict:
    query = state["query"].strip()
    if not query:
        raise ValueError("query must not be empty")
    settings = get_settings()
    model = get_chat_model(settings.model_for("analysis"))
    structured = model.with_structured_output(QueryAnalysis)
    prompt = (
        "Analyze this research request. Normalize it without changing intent; "
        "identify key entities; decide whether explicit comparison or fresh "
        "information is required; estimate complexity from 1 to 5.\n\n"
        f"Query: {query}"
    )
    try:
        analysis = await structured.ainvoke([HumanMessage(content=prompt)])
    except Exception:
        analysis = _fallback_analysis(query)
    return {"analysis": analysis, "iteration": state.get("iteration", 0)}
