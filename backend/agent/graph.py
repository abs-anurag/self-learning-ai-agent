"""
LangGraph graph definition for METIS agent.

Source of truth: BLUEPRINT.md §8 Graph Topology & Routing Logic.
Topology:
    START -> understand -> retrieve_memory -> planning -> execute -> observe -> evaluate
    evaluate -> route_after_evaluate:
        - "maybe_learn" -> maybe_learn -> respond -> END
        - "respond" -> respond -> END
        - "reflect" -> reflect -> replan -> execute
"""

from __future__ import annotations

from typing import Any, Optional
from langgraph.graph import END, START, StateGraph

from backend.agent.nodes import (
    evaluate_node,
    execute_node,
    learn_node,
    observe_node,
    plan_node,
    reflect_node,
    replan_node,
    respond_node,
    retrieve_node,
    understand_node,
)
from backend.agent.state import AgentState, route_after_evaluate
from backend.core.logging import get_logger

logger = get_logger(__name__)


def create_agent_graph(checkpointer: Optional[Any] = None) -> Any:
    """
    Construct and compile the METIS LangGraph agent StateGraph.

    Args:
        checkpointer: Optional LangGraph checkpointer (e.g., AsyncPostgresSaver).

    Returns:
        Compiled LangGraph runnable.
    """
    workflow = StateGraph(AgentState)

    # 1. Register all 10 nodes (using 'planning' to avoid state key collision with 'plan')
    workflow.add_node("understand", understand_node)
    workflow.add_node("retrieve_memory", retrieve_node)
    workflow.add_node("planning", plan_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("observe", observe_node)
    workflow.add_node("evaluate", evaluate_node)
    workflow.add_node("reflect", reflect_node)
    workflow.add_node("replan", replan_node)
    workflow.add_node("maybe_learn", learn_node)
    workflow.add_node("respond", respond_node)

    # 2. Add sequential edges per BLUEPRINT.md §8
    workflow.add_edge(START, "understand")
    workflow.add_edge("understand", "retrieve_memory")
    workflow.add_edge("retrieve_memory", "planning")
    workflow.add_edge("planning", "execute")
    workflow.add_edge("execute", "observe")
    workflow.add_edge("observe", "evaluate")

    # 3. Add conditional edge after evaluate
    workflow.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {
            "maybe_learn": "maybe_learn",
            "respond": "respond",
            "reflect": "reflect",
        },
    )

    # 4. Add loop and terminal edges
    workflow.add_edge("reflect", "replan")
    workflow.add_edge("replan", "execute")
    workflow.add_edge("maybe_learn", "respond")
    workflow.add_edge("respond", END)

    # 5. Compile with optional checkpointer
    app = workflow.compile(checkpointer=checkpointer)
    logger.info("Compiled METIS agent LangGraph successfully.")
    return app
