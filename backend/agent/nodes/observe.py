"""
Observe node: formats and truncates tool execution results into structured observations.

Source of truth: BLUEPRINT.md §8 line 332, §9.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.state import AgentState, truncate_observation
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def observe(state: AgentState) -> dict[str, Any]:
    """
    Transforms recent tool calls into sanitized and size-bounded observations.
    Source: BLUEPRINT.md §8 line 332, §9.
    """
    tool_calls = state.get("tool_calls", [])
    observations: list[dict[str, Any]] = []

    for call in tool_calls:
        tool_name = call.get("tool_name", "unknown")
        raw_output = call.get("output", "")
        status = call.get("status", "unknown")
        error_code = call.get("error_code")

        # Truncate large tool outputs before state assignment per BLUEPRINT.md §9
        safe_output = truncate_observation(raw_output)

        obs_entry: dict[str, Any] = {
            "tool_name": tool_name,
            "output": safe_output,
            "status": status,
        }
        if error_code:
            obs_entry["error_code"] = error_code

        observations.append(obs_entry)

    logger.info(
        "Node 'observe' completed: %d observations formatted for run_id=%s",
        len(observations),
        state.get("run_id"),
    )

    return {
        "observations": observations,
        "current_step": "observe",
    }
