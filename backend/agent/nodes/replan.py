"""
Replan node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §14.
Constructs revised plan addressing diagnosed failure.
Enforces loop safety:
- Replan budget limit: if iteration_count >= max_iterations, terminates
- Repeated identical plan detection: if new plan == old plan, sets termination_reason = 'repeated_failure'
- Terminal failure check
Loops back to execute node.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from backend.agent.runtime import get_current_runtime
from backend.agent.state import TERMINAL_REASONS, AgentState
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

    iteration_count = state.get("iteration_count", 0)
    max_iterations = state.get("max_iterations", 3)
    termination_reason = state.get("termination_reason")

    # 1. Budget check: if iterations reached or terminal reason present, do not replan
    if iteration_count >= max_iterations or termination_reason in TERMINAL_REASONS:
        logger.info("Replan budget exhausted or terminal state reached; bypassing replan.")
        return {
            "current_step": "respond",
            "termination_reason": termination_reason or "max_iterations",
        }

    # 2. Formulate revised plan
    plan_res = await llm.plan(state)
    new_plan = plan_res.get("plan", [
        "Re-evaluate requirements with corrected parameters",
        "Re-execute computation/research",
        "Verify final result",
    ])

    old_plan = state.get("plan", [])

    # 3. Repeated plan detection
    if new_plan == old_plan:
        logger.warning("Repeated identical plan detected in replan node.")
        return {
            "plan": new_plan,
            "termination_reason": "repeated_failure",
            "error": "Identical plan repeated without adaptation.",
            "current_step": "execute",
        }

    # Emit planning_started event for revised plan
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=uuid.UUID(state["user_id"]),
            event_type=EventType.PLANNING_STARTED,
            status="running",
            metadata={
                "iteration_count": iteration_count,
                "step_count": len(new_plan),
                "is_replan": True,
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit planning_started event during replan: %s", exc)

    return {
        "plan": new_plan,
        "current_step": "execute",
    }
