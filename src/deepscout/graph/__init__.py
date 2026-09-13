"""LangGraph orchestration package with lazy public exports."""

from typing import Any

__all__ = ["build_graph", "graph"]


def __getattr__(name: str) -> Any:
    """Avoid importing the graph builder while graph submodules initialize."""
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from deepscout.graph.builder import build_graph, graph

    return {"build_graph": build_graph, "graph": graph}[name]
