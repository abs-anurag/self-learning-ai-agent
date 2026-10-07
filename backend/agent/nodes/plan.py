"""
Plan node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §14.
Formulates initial action plan incorporating retrieved recipe context.
Emits planning_started telemetry.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def plan_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: plan.
    Calls LLM provider to construct ordered action plan.
    Emits planning_started event.
    """
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    plan_res = await llm.plan(state)
    plan = plan_res.get("plan", [])
    if not isinstance(plan, list):
        plan = [str(plan)]

    # Emit planning_started event
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=uuid.UUID(state["user_id"]),
            event_type=EventType.PLANNING_STARTED,
            status="running",
            metadata={
                "plan_steps": plan,
                "step_count": len(plan),
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit planning_started event: %s", exc)

    return {
        "plan": plan,
        "current_step": plan[0] if plan else "execute",
    }
