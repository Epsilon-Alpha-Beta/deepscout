"""构建 DeepScout Phase 3 LangGraph。"""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from deepscout.agents.analyzer import analyze_query
from deepscout.agents.citation_verifier import citation_verifier
from deepscout.agents.critic import critic
from deepscout.agents.evidence_manager import evidence_manager
from deepscout.agents.human_review import human_review
from deepscout.agents.planner import planner
from deepscout.agents.researcher import researcher
from deepscout.agents.writer import writer
from deepscout.graph.routing import (
    dispatch_ready_tasks,
    route_after_citation_verifier,
    route_after_critic,
    route_after_human_review,
)
from deepscout.graph.state import DeepScoutState
from deepscout.runtime.budget import sync_budget
from deepscout.runtime.retry import llm_retry_policy


def build_graph(*, checkpointer: BaseCheckpointSaver | None = None):
    builder = StateGraph(DeepScoutState)
    retry_policy = llm_retry_policy()

    builder.add_node("analyze_query", analyze_query, retry_policy=retry_policy)
    builder.add_node("planner", planner, retry_policy=retry_policy)
    builder.add_node("supervisor", sync_budget)
    builder.add_node("researcher", researcher)
    builder.add_node("evidence_manager", evidence_manager)
    builder.add_node("critic", critic, retry_policy=retry_policy)
    builder.add_node("writer", writer, retry_policy=retry_policy)
    builder.add_node(
        "citation_verifier",
        citation_verifier,
        retry_policy=retry_policy,
    )
    builder.add_node("human_review", human_review)

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
        {"planner": "planner", "human_review": "human_review"},
    )
    builder.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {"planner": "planner", "end": END},
    )
    return builder.compile(checkpointer=checkpointer)


graph = build_graph()
