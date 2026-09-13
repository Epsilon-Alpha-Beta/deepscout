"""构建 DeepScout Phase 2 LangGraph。"""

from langgraph.graph import END, START, StateGraph

from deepscout.agents.analyzer import analyze_query
from deepscout.agents.citation_verifier import citation_verifier
from deepscout.agents.critic import critic
from deepscout.agents.evidence_manager import evidence_manager
from deepscout.agents.planner import planner
from deepscout.agents.researcher import researcher
from deepscout.agents.writer import writer
from deepscout.graph.routing import (
    dispatch_ready_tasks,
    route_after_citation_verifier,
    route_after_critic,
)
from deepscout.graph.state import DeepScoutState
from deepscout.runtime.budget import sync_budget


def build_graph():
    builder = StateGraph(DeepScoutState)
    builder.add_node("analyze_query", analyze_query)
    builder.add_node("planner", planner)
    builder.add_node("supervisor", sync_budget)
    builder.add_node("researcher", researcher)
    builder.add_node("evidence_manager", evidence_manager)
    builder.add_node("critic", critic)
    builder.add_node("writer", writer)
    builder.add_node("citation_verifier", citation_verifier)

    builder.add_edge(START, "analyze_query")
    builder.add_edge("analyze_query", "planner")
    builder.add_edge("planner", "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        dispatch_ready_tasks,
        ["researcher", "evidence_manager"],
    )
    builder.add_edge("researcher", "supervisor")
    builder.add_edge("evidence_manager", "critic")
    builder.add_conditional_edges(
        "critic",
        route_after_critic,
        {"planner": "planner", "writer": "writer"},
    )
    builder.add_edge("writer", "citation_verifier")
    builder.add_conditional_edges(
        "citation_verifier",
        route_after_citation_verifier,
        {"planner": "planner", "end": END},
    )
    return builder.compile()


graph = build_graph()
