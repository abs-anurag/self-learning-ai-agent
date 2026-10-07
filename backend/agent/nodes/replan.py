"""
Replan node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §14.
Constructs revised plan addressing diagnosed failure.
Loops back to execute node.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def replan_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: replan.
    Constructs an updated plan taking into account the reflection and previous observations.
    Emits planning_started event for the revised plan.
    """
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    # Formulate revised plan
    plan_res = await llm.plan(state)
    new_plan = plan_res.get("plan", [
        "Re-evaluate requirements with corrected parameters",
        "Re-execute computation/research",
        "Verify final result",
    ])

    # Emit planning_started event for revised plan
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=uuid.UUID(state["user_id"]),
            event_type=EventType.PLANNING_STARTED,
            status="running",
            metadata={
                "iteration_count": state.get("iteration_count", 1),
                "step_count": len(new_plan),
                "is_replan": True,
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit planning_started event during replan: %s", exc)

    return {
        "plan": new_plan,
        # Clear tool_calls for fresh retry attempt
        "tool_calls": [],
        "current_step": "execute",
    }
