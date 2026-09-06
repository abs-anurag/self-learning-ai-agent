"""
LangGraph StateGraph construction and compilation for the Self-Learning AI Agent.

Source of truth: BLUEPRINT.md §8 (Graph Topology, Iteration Semantics, Routing Logic).
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


def build_agent_graph() -> StateGraph:
    """
    Construct the uncompiled LangGraph StateGraph topology.
    Source: BLUEPRINT.md §8 (Graph Topology).
    """
    workflow = StateGraph(AgentState)

    # Register all 10 core nodes
    workflow.add_node("understand", understand)
    workflow.add_node("retrieve_memory", retrieve_memory)
    workflow.add_node("plan", plan)
    workflow.add_node("execute", execute)
    workflow.add_node("observe", observe)
    workflow.add_node("evaluate", evaluate)
    workflow.add_node("reflect", reflect)
    workflow.add_node("replan", replan)
    workflow.add_node("maybe_learn", maybe_learn)
    workflow.add_node("respond", respond)

    # Define linear execution edges
    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "plan")
    workflow.add_edge("plan", "execute")
    workflow.add_edge("execute", "observe")
    workflow.add_edge("observe", "evaluate")

    # Pure conditional routing evaluated immediately after evaluate node (§8 lines 268-322)
    workflow.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "maybe_learn": "maybe_learn",
            "respond": "respond",
            "reflect": "reflect",
        },
    )

    # Iteration retry loop: reflect -> replan -> execute
    workflow.add_edge("reflect", "replan")
    workflow.add_edge("replan", "execute")

    # Learning path: maybe_learn -> respond -> END
    workflow.add_edge("maybe_learn", "respond")
    workflow.add_edge("respond", END)

    return workflow


def create_agent_graph(checkpointer: Optional[Any] = None) -> CompiledStateGraph:
    """
    Build and compile the LangGraph workflow with an optional checkpointer.
    Source: BLUEPRINT.md §8.
    """
    workflow = build_agent_graph()
    if checkpointer is not None:
        return workflow.compile(checkpointer=checkpointer)
    return workflow.compile()


__all__ = [
    "build_agent_graph",
    "create_agent_graph",
]
