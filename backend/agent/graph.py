"""
LangGraph StateGraph construction and compilation for the Self-Learning AI Agent.

Source of truth:
    BLUEPRINT.md §8 (Graph Topology, Iteration Semantics, Routing Logic).

LangGraph 0.2.x compatibility:
    AgentState contains a state key named "plan". LangGraph 0.2.x can
    conflict when a graph node has the same name, so the implementation
    uses "plan_node" and "execute_node" as internal graph node identifiers.
"""

from __future__ import annotations

from typing import Any, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from backend.agent.nodes import (
    evaluate,
    execute,
    maybe_learn,
    observe,
    plan,
    reflect,
    replan,
    respond,
    retrieve_memory,
    understand,
)
from backend.agent.state import AgentState, route_after_evaluate


# ---------------------------------------------------------------------------
# Internal graph node names
# ---------------------------------------------------------------------------

# Logical Blueprint node: "plan"
# Internal LangGraph node name avoids collision with AgentState["plan"].
PLAN_NODE = "plan_node"

# Logical Blueprint node: "execute"
EXECUTE_NODE = "execute_node"


def build_agent_graph() -> StateGraph:
    """
    Build the Agent Core LangGraph workflow.

    Logical Blueprint topology:

        START
          ↓
      understand
          ↓
    retrieve_memory
          ↓
        plan
          ↓
       execute
          ↓
       observe
          ↓
      evaluate
       ↙   ↓   ↘
    reflect  maybe_learn  respond
       ↓        ↓           ↓
     replan   respond       END
       ↓
     execute

    Implementation names:

        plan   -> plan_node
        execute -> execute_node

    The internal names are required for compatibility with LangGraph 0.2.x
    because "plan" is already an AgentState key.
    """

    workflow = StateGraph(AgentState)

    # -----------------------------------------------------------------------
    # Core nodes
    # -----------------------------------------------------------------------

    workflow.add_node("understand", understand)
    workflow.add_node("retrieve_memory", retrieve_memory)
    workflow.add_node(PLAN_NODE, plan)
    workflow.add_node(EXECUTE_NODE, execute)
    workflow.add_node("observe", observe)
    workflow.add_node("evaluate", evaluate)
    workflow.add_node("reflect", reflect)
    workflow.add_node("replan", replan)
    workflow.add_node("maybe_learn", maybe_learn)
    workflow.add_node("respond", respond)

    # -----------------------------------------------------------------------
    # Main execution path
    # -----------------------------------------------------------------------

    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "retrieve_memory")
    workflow.add_edge("retrieve_memory", PLAN_NODE)
    workflow.add_edge(PLAN_NODE, EXECUTE_NODE)
    workflow.add_edge(EXECUTE_NODE, "observe")
    workflow.add_edge("observe", "evaluate")

    # -----------------------------------------------------------------------
    # Conditional routing after evaluation
    # -----------------------------------------------------------------------

    workflow.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "maybe_learn": "maybe_learn",
            "respond": "respond",
            "reflect": "reflect",
        },
    )

    # -----------------------------------------------------------------------
    # Reflection / replanning retry loop
    # -----------------------------------------------------------------------

    workflow.add_edge("reflect", "replan")
    workflow.add_edge("replan", EXECUTE_NODE)

    # -----------------------------------------------------------------------
    # Learning / final response
    # -----------------------------------------------------------------------

    workflow.add_edge("maybe_learn", "respond")
    workflow.add_edge("respond", END)

    return workflow


def create_agent_graph(
    checkpointer: Optional[Any] = None,
) -> CompiledStateGraph:
    """
    Build and compile the Agent Core LangGraph.

    Args:
        checkpointer:
            Optional LangGraph checkpointer. When supplied, the graph
            is compiled with persistence enabled.

    Returns:
        A compiled LangGraph StateGraph.
    """

    workflow = build_agent_graph()

    if checkpointer is not None:
        return workflow.compile(checkpointer=checkpointer)

    return workflow.compile()


__all__ = [
    "build_agent_graph",
    "create_agent_graph",
]