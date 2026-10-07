"""
Observe node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §9.
Formats and truncates tool results into structured observations.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from backend.agent.state import AgentState, truncate_observation
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def observe_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: observe.
    Sanitizes and truncates observation content before updating graph state.
    """
    raw_observations = list(state.get("observations", []))
    sanitized_observations: list[dict[str, Any]] = []

    for obs in raw_observations:
        if not isinstance(obs, dict):
            continue

        item = dict(obs)
        output = item.get("output")
        if output is not None:
            # If string or json, truncate if needed
            if isinstance(output, str):
                item["output"] = truncate_observation(output)
            elif isinstance(output, dict):
                # Ensure no oversized field inside output
                truncated_dict = {}
                for k, v in output.items():
                    if isinstance(v, str):
                        truncated_dict[k] = truncate_observation(v)
                    else:
                        truncated_dict[k] = v
                item["output"] = truncated_dict

        sanitized_observations.append(item)

    return {
        "observations": sanitized_observations,
        "current_step": "evaluate",
    }
