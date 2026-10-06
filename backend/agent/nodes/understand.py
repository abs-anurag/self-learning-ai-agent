"""
Understanding node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node processes the goal and extracts a structured understanding of the task.
Uses LLM provider's understand() method.

Design rules:
- Calls runtime.llm_provider.understand(state)
- Updates understood_task in state
- Emits understanding_completed event
- Errors logged but don't halt execution (fallback to raw goal)
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime, get_runtime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def understand_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: understand and structure the task goal.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with goal, task_type, user_id.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission (also in metadata.runtime)

    Returns:
        dict: State update with understood_task.

    Notes:
        - Uses LLM to parse goal into structured understanding
        - Falls back to raw goal if LLM fails
    """
    logger.info(f"[understand_node] Starting understanding for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = get_runtime(config)
    if not runtime:
        logger.error("[understand_node] No runtime in context")
        return {"understood_task": state.get("goal", "")}

    try:
        # Call understand if the provider supports it, otherwise use goal as-is
        if hasattr(runtime.llm_provider, "understand"):
            understand_result = await runtime.llm_provider.understand(state)
        else:
            understand_result = {"understood_task": state.get("goal", "")}

        understood_task = understand_result.get("understood_task", state.get("goal", ""))
        task_type = understand_result.get("task_type", state.get("task_type", ""))
        logger.info(f"[understand_node] Understood task: {understood_task[:100]}...")

        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="task_started",
                status="running",
                metadata={
                    "understood_length": len(understood_task),
                    "task_type": task_type,
                },
            )
            logger.debug("[understand_node] Emitted task_started event")
        except Exception as e:
            logger.warning(f"[understand_node] Failed to emit task_started event: {e}")

        result = {"understood_task": understood_task}
        if task_type:
            result["task_type"] = task_type
        return result

    except Exception as e:
        logger.error(f"[understand_node] Unexpected error during understanding: {e}", exc_info=True)
        return {"understood_task": state.get("goal", "")}


__all__ = ["understand_node"]