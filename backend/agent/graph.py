"""
LangGraph state machine wiring for the Self-Learning AI Agent.

Source of truth: BLUEPRINT.md §8 (Graph Topology), §8 (Routing Logic).

This module is the single integration point that wires the existing
node implementations into a conditional LangGraph state machine.

Graph Topology (BLUEPRINT.md §8):
    START -> understand -> retrieve_memory -> plan -> execute -> observe
    -> evaluate -> route_after_evaluate -> {maybe_learn | respond | reflect}
    reflect -> replan -> execute (loop)
    maybe_learn -> respond -> END

Routing Logic (BLUEPRINT.md §8):
    route_after_evaluate(state):
        if evaluation.task_success: return "maybe_learn"
        if iteration_count >= max_iterations: return "respond"
        if termination_reason in terminal_reasons: return "respond"
        return "reflect"

Design rules:
- Reuses existing node implementations from backend.agent.nodes.*.
- Preserves the 20-field AgentState design from BLUEPRINT.md §9.
- LangGraph is imported defensively: if langgraph is not installed,
  the module still imports cleanly and exposes the graph factory
  function for callers that have langgraph available.
- The graph factory accepts an optional checkpointer for checkpoint
  persistence per BLUEPRINT.md §8.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from backend.agent.nodes.evaluate import evaluate_node
from backend.agent.nodes.execute import execute_node
from backend.agent.nodes.learn import learn_node
from backend.agent.nodes.observe import observe_node
from backend.agent.nodes.plan import plan_node
from backend.agent.nodes.reflect import reflect_node
from backend.agent.nodes.replan import replan_node
from backend.agent.nodes.retrieve import retrieve_node
from backend.agent.nodes.respond import respond_node
from backend.agent.nodes.understand import understand_node
from backend.agent.state import AgentState, route_after_evaluate

logger = logging.getLogger(__name__)

# Try to import LangGraph defensively so the module can be imported
# even when langgraph is not installed (e.g. in test environments).
try:
    from langgraph.graph import END, START, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when langgraph missing
    LANGGRAPH_AVAILABLE = False
    StateGraph = None  # type: ignore[assignment, misc]
    START = None  # type: ignore[assignment]
    END = None  # type: ignore[assignment]

    class _StubStateGraph:  # type: ignore[no-redef]
        """Minimal stub used when langgraph is unavailable."""

        def __init__(self, state_schema: Any) -> None:
            self.state_schema = state_schema
            self.nodes: dict[str, Any] = {}
            self.edges: list[Any] = []
            self.conditional_edges: dict[str, Any] = {}

        def add_node(self, name: str, node: Any) -> None:
            self.nodes[name] = node

        def add_edge(self, src: str, dst: str) -> None:
            self.edges.append((src, dst))
            if src is None or src == "_start_":
                self.entry_point = dst

        def add_conditional_edges(
            self,
            src: str,
            router: Any,
            path_map: dict[str, str],
        ) -> None:
            self.conditional_edges[src] = (router, path_map)

        def set_entry_point(self, name: str) -> None:
            self.entry_point = name

        def compile(self, **kwargs: Any) -> Any:
            return self

    StateGraph = _StubStateGraph  # type: ignore[assignment, misc]


def build_agent_graph(checkpointer: Optional[Any] = None) -> Any:
    """
    Build and compile the conditional LangGraph agent state machine.

    Source: BLUEPRINT.md §8 (Graph Topology).

    The graph wires the following nodes in order:
        START -> understand -> retrieve_memory -> plan -> execute
        -> observe -> evaluate -> route_after_evaluate
        -> {maybe_learn | respond | reflect}
        reflect -> replan -> execute (loop)
        maybe_learn -> respond -> END

    Args:
        checkpointer: Optional LangGraph checkpointer (AsyncPostgresSaver)
            for checkpoint persistence per BLUEPRINT.md §8.

    Returns:
        Compiled LangGraph graph (or stub graph if langgraph unavailable).

    Raises:
        RuntimeError: If langgraph is not installed and a real graph
            is required. The stub graph supports introspection but
            cannot execute.
    """
    if not LANGGRAPH_AVAILABLE:
        logger.warning(
            "langgraph is not installed; returning a stub graph for "
            "introspection only. Install langgraph to execute the agent."
        )

    graph = StateGraph(AgentState)

    # -- Register nodes (BLUEPRINT.md §8 Node Table) --------------
    graph.add_node("understand", understand_node)
    graph.add_node("retrieve_memory", retrieve_node)
    graph.add_node("plan", plan_node)
    graph.add_node("execute", execute_node)
    graph.add_node("observe", observe_node)
    graph.add_node("evaluate", evaluate_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("replan", replan_node)
    graph.add_node("maybe_learn", learn_node)
    graph.add_node("respond", respond_node)

    # -- Wire edges (BLUEPRINT.md §8 Graph Topology) --------------
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "retrieve_memory")
    graph.add_edge("retrieve_memory", "plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "observe")
    graph.add_edge("observe", "evaluate")

    # Conditional routing after evaluate (BLUEPRINT.md §8)
    graph.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "maybe_learn": "maybe_learn",
            "respond": "respond",
            "reflect": "reflect",
        },
    )

    # Reflect -> replan -> execute loop
    graph.add_edge("reflect", "replan")
    graph.add_edge("replan", "execute")

    # Success path: maybe_learn -> respond -> END
    graph.add_edge("maybe_learn", "respond")
    graph.add_edge("respond", END)

    # Compile with optional checkpointer
    compile_kwargs: dict[str, Any] = {}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer

    return graph.compile(**compile_kwargs)


__all__ = [
    "build_agent_graph",
    "route_after_evaluate",
    "LANGGRAPH_AVAILABLE",
]