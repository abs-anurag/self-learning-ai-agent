"""
Reflection node for LangGraph agent.

Source of truth: BLUEPRINT.md §8, §12.

This node generates a reflection on the execution so far.
Calls runtime.llm_provider.reflect(state).

Design rules:
- Calls runtime.llm_provider.reflect(state)
- Returns reflection string
- Emits reflection_completed event
- Errors logged but don't halt execution (fallback to empty reflection)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime, get_runtime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def reflect_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: generate reflection on execution so far.

    Source: BLUEPRINT.md §8, §12.

    Args:
        state: Current AgentState with goal, plan, tool_calls, observations, evaluation.
        config: Configuration dict containing:
            - runtime: AgentRuntime for LLM provider and event emission

    Returns:
        dict: State update with reflection string.

    Notes:
        - Reflection summarizes what worked, what didn't, and what to try next
        - Used by replan_node to adjust strategy
    """
    logger.info(f"[reflect_node] Starting reflection for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = get_runtime(config)
    if not runtime:
        logger.error("[reflect_node] No runtime in context")
        return {"reflection": "Reflection unavailable: missing runtime"}

    try:
        reflect_result = await runtime.llm_provider.reflect(state)
        reflection = reflect_result.get("reflection", "")
        logger.info(f"[reflect_node] Reflection generated: {reflection[:100]}...")

        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="reflection_completed",
                status="running",
                metadata={
                    "reflection_length": len(reflection),
                    "iteration_count": state.get("iteration_count", 0),
                },
            )
            logger.debug("[reflect_node] Emitted reflection_completed event")
        except Exception as e:
            logger.warning(f"[reflect_node] Failed to emit reflection_completed event: {e}")

        return {"reflection": reflection}

    except Exception as e:
        logger.error(f"[reflect_node] Unexpected error during reflection: {e}", exc_info=True)
        return {"reflection": f"Reflection error: {e}"}


__all__ = ["reflect_node"]