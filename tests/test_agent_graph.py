"""
Tests for the agent graph structure.
"""
from backend.agent.graph import build_agent_graph, LANGGRAPH_AVAILABLE


def test_build_agent_graph_returns_graph():
    """Test that build_agent_graph returns a graph (or stub) without error."""
    graph = build_agent_graph()
    assert graph is not None


def test_agent_graph_stub_structure():
    """Test the stub graph has correct nodes and edges when langgraph is not available."""
    if LANGGRAPH_AVAILABLE:
        # Skip this test if langgraph is available
        return

    graph = build_agent_graph()

    # Check that we have a stub with the expected attributes
    assert hasattr(graph, 'nodes')
    assert hasattr(graph, 'edges')
    assert hasattr(graph, 'conditional_edges')

    # Check nodes
    expected_nodes = {
        "understand", "retrieve_memory", "plan", "execute",
        "observe", "evaluate", "reflect", "replan", "maybe_learn", "respond"
    }
    assert set(graph.nodes.keys()) == expected_nodes

    # Check edges (as tuples in the stub)
    edges = set(graph.edges)
    assert (None, "understand") in edges  # START -> understand
    assert ("understand", "retrieve_memory") in edges
    assert ("retrieve_memory", "plan") in edges
    assert ("plan", "execute") in edges
    assert ("execute", "observe") in edges
    assert ("observe", "evaluate") in edges

    # Check conditional edges
    assert "evaluate" in graph.conditional_edges
    router, path_map = graph.conditional_edges["evaluate"]
    # The router should be the route_after_evaluate function
    assert router is not None
    # The path_map should map to the three possible destinations
    assert set(path_map.values()) == {"maybe_learn", "respond", "reflect"}

    # Check other edges
    assert ("reflect", "replan") in edges
    assert ("replan", "execute") in edges
    assert ("maybe_learn", "respond") in edges
    assert ("respond", None) in edges  # respond -> END (None in stub)


def test_agent_graph_compiled_when_langgraph_available():
    """Test that the graph can be built and compiled when langgraph is available."""
    if not LANGGRAPH_AVAILABLE:
        # Skip this test if langgraph is not available
        return

    graph = build_agent_graph()

    # When langgraph is available, the graph should be a CompiledGraph instance
    # and should not have the stub's attributes
    assert not hasattr(graph, 'nodes')
    assert not hasattr(graph, 'edges')
    assert not hasattr(graph, 'conditional_edges')

    # The compiled graph should have an invoke method (for synchronous execution)
    assert hasattr(graph, 'invoke')
    # It should not have a compile method (that's on the StateGraph instance before compiling)
    assert not hasattr(graph, 'compile')
