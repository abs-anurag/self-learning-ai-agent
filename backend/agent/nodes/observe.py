"""
Observation node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node formats and truncates tool results into structured observations.
Updates the observations list in state.

Design rules:
- Reads tool_calls from state
- Formats each tool result into observation dict
- Truncates large results per BLUEPRINT.md §9 (10000 chars)
- Returns updated observations list
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState, truncate_observation

logger = logging.getLogger(__name__)


async def observe_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: format and truncate tool results into structured observations.

    Source: BLUEPRINT.md §8, §9.

    Args:
        state: Current AgentState with tool_calls.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission (optional)

    Returns:
        dict: State update with observations list.

    Notes:
        - Truncates large tool results before state assignment
        - Per BLUEPRINT.md §9: 'Large tool results are truncated before state assignment'
        - Returns cumulative observations (not just new ones)
    """
    logger.info(f"[observe_node] Starting observation for task {state['task_id']}, run {state['run_id']}")

    tool_calls = state.get("tool_calls", [])
    existing_observations = state.get("observations", [])

    # Only process new tool calls (those not yet observed)
    observed_count = len(existing_observations)
    new_tool_calls = tool_calls[observed_count:]

    if not new_tool_calls:
        logger.debug("[observe_node] No new tool calls to observe")
        return {"observations": existing_observations}

    new_observations = []

    for call in new_tool_calls:
        tool_name = call.get("tool", "unknown")
        status = call.get("status", "unknown")
        result = call.get("result")
        error = call.get("error")
        error_code = call.get("error_code")
        execution_time_ms = call.get("execution_time_ms", 0)

        if error:
            content = f"Tool '{tool_name}' failed: {error}"
            if error_code:
                content += f" (error_code: {error_code})"
        else:
            content = str(result) if result is not None else "Tool completed with no output"

        # Truncate per BLUEPRINT.md §9
        content = truncate_observation(content)

        observation = {
            "tool": tool_name,
            "status": status,
            "content": content,
            "error": error,
            "error_code": error_code,
            "execution_time_ms": execution_time_ms,
        }

        new_observations.append(observation)

    updated_observations = existing_observations + new_observations

    logger.info(f"[observe_node] Added {len(new_observations)} observations, total: {len(updated_observations)}")

    return {"observations": updated_observations}


__all__ = ["observe_node"]
