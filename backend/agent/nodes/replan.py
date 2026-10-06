"""
Replanning node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node generates a new plan incorporating reflection.
Calls runtime.llm_provider.plan(state) with reflection context.

Design rules:
- Calls runtime.llm_provider.plan(state) with reflection context
- Returns updated plan and current_step
- Emits replanning_completed event
- Errors logged but don't halt execution (fallback to generic plan)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime, get_runtime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def replan_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: generate new plan incorporating reflection.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with goal, plan, current_step, reflection, iteration_count.
        config: Configuration dict containing:
            - runtime: AgentRuntime for LLM provider and event emission

    Returns:
        dict: State update with plan (list of steps) and current_step.

    Notes:
        - Incorporates reflection to adjust strategy
        - Resets current_step to first step of new plan
    """
    logger.info(f"[replan_node] Starting replanning for task {state['task_id']}, run {state['run_id']}, iteration {state['iteration_count']}")

    runtime: AgentRuntime | None = get_runtime(config)
    if not runtime:
        logger.error("[replan_node] No runtime in context")
        return _fallback_plan()

    try:
        plan_result = await runtime.llm_provider.plan(state)
        plan = plan_result.get("plan", [])
        current_step = plan_result.get("current_step", plan[0] if plan else "Begin execution")

        if not plan or not isinstance(plan, list):
            logger.warning("[replan_node] Invalid plan from LLM, using fallback")
            return _fallback_plan()

        plan = [str(step) for step in plan if step]
        if not plan:
            logger.warning("[replan_node] Empty plan from LLM, using fallback")
            return _fallback_plan()

        logger.info(f"[replan_node] New plan generated with {len(plan)} steps")

        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="planning_started",
                status="running",
                metadata={
                    "plan_length": len(plan),
                    "iteration_count": state.get("iteration_count", 0),
                    "has_reflection": bool(state.get("reflection")),
                },
            )
            logger.debug("[replan_node] Emitted planning_started event")
        except Exception as e:
            logger.warning(f"[replan_node] Failed to emit replanning_completed event: {e}")

        return {"plan": plan, "current_step": current_step}

    except Exception as e:
        logger.error(f"[replan_node] Unexpected error during replanning: {e}", exc_info=True)
        return _fallback_plan()


def _fallback_plan() -> dict[str, Any]:
    return {
        "plan": [
            "Re-evaluate the approach based on previous failures",
            "Try alternative strategy or tool",
            "Execute and verify result",
        ],
        "current_step": "Re-evaluate the approach based on previous failures",
    }


__all__ = ["replan_node"]