"""
Reflection node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node formulates a structured diagnosis of failure for the next plan.
It uses the LLM provider's reflect() method to analyze what went wrong.

Design rules:
- Calls runtime.llm_provider.reflect(state)
- Returns reflection string (no chain-of-thought in state)
- Emits reflection_completed event
- Errors logged but don't halt execution (fallback to generic reflection)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def reflect_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: formulate structured diagnosis of failure for next plan.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with evaluation, observations, tool_calls, etc.
        config: Configuration dict containing:
            - runtime: AgentRuntime for LLM provider and event emission
            - settings: Application settings (optional)

    Returns:
        dict: State update with reflection string.

    Notes:
        - Per BLUEPRINT.md §17: chain-of-thought never placed in AgentState
        - Emits reflection_completed event
        - On error, returns generic reflection
    """
    logger.info(f"[reflect_node] Starting reflection for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = config.get("runtime")

    if not runtime:
        logger.error("[reflect_node] No runtime in config")
        return {"reflection": "Reflection unavailable: missing runtime"}

    try:
        # Call LLM provider for reflection
        reflect_result = await runtime.llm_provider.reflect(state)
        reflection = reflect_result.get("reflection", "")

        if not reflection or not reflection.strip():
            reflection = "Strategy adjustment needed based on observation and evaluation."

        logger.info(f"[reflect_node] Reflection generated: {reflection[:100]}...")

        # Emit reflection_completed event
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
        return {"reflection": "Reflection failed due to internal error. Retrying with adjusted strategy."}


__all__ = ["reflect_node"]
