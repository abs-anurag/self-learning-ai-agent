"""
Replan node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node constructs a revised plan addressing the diagnosed failure.
It uses the LLM provider's plan() method with reflection context.

Design rules:
- Calls runtime.llm_provider.plan(state) with reflection context
- Returns updated plan and current_step
- Emits planning_started event
- Errors logged but don't halt execution (fallback to generic plan)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.nodes.plan import _fallback_plan, build_plan_context
from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def replan_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: construct revised plan addressing diagnosed failure.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with reflection, evaluation, observations, etc.
        config: Configuration dict containing:
            - runtime: AgentRuntime for LLM provider and event emission

    Returns:
        dict: State update with updated plan and current_step.

    Notes:
        - Uses reflection from previous iteration to inform revised plan
        - Emits planning_started event
        - On error, returns fallback plan
    """
    logger.info(
        f"[replan_node] Starting replan for task {state['task_id']}, "
        f"run {state['run_id']}, iteration {state['iteration_count']}"
    )

    runtime: AgentRuntime | None = config.get("runtime")
    if not runtime:
        logger.error("[replan_node] No runtime in config")
        return _fallback_plan()

    try:
        # Build context with reflection from the failed iteration
        context = build_plan_context(state)

        # Call LLM provider for revised plan
        plan_result = await runtime.llm_provider.plan(state)
        plan = plan_result.get("plan", [])
        current_step = plan_result.get(
            "current_step", plan[0] if plan else "Begin execution"
        )

        if not plan or not isinstance(plan, list):
            logger.warning("[replan_node] Invalid plan from LLM, using fallback")
            return _fallback_plan()

        plan = [str(step) for step in plan if step]
        if not plan:
            logger.warning("[replan_node] Empty plan from LLM, using fallback")
            return _fallback_plan()

        logger.info(f"[replan_node] Revised plan generated with {len(plan)} steps")

        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="planning_started",
                status="running",
                metadata={
                    "plan_length": len(plan),
                    "is_replan": True,
                    "iteration_count": state.get("iteration_count", 0),
                    "has_reflection": bool(state.get("reflection")),
                },
            )
            logger.debug("[replan_node] Emitted planning_started event")
        except Exception as e:
            logger.warning(f"[replan_node] Failed to emit planning_started event: {e}")

        return {"plan": plan, "current_step": current_step}
    except Exception as e:
        logger.error(f"[replan_node] Unexpected error during replan: {e}", exc_info=True)
        return _fallback_plan()


__all__ = ["replan_node"]