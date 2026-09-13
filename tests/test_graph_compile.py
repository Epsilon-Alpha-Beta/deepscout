from langgraph.graph.state import CompiledStateGraph

from deepscout.graph.builder import build_graph


def test_phase2_graph_compiles():
    graph = build_graph()
    assert isinstance(graph, CompiledStateGraph)
