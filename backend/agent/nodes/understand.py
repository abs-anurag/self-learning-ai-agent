"""
Understanding node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node normalizes the goal into understood_task and determines task_type.
In demo mode, uses deterministic classification. In live mode, uses LLM.

Design rules:
- Sets understood_task (normalized goal) and task_type
- task_type must be one of: math, research, file, code, mixed
- Emits planning_started event after understanding
- Errors logged but don't halt execution
"""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState, VALID_TASK_TYPES
from backend.core.config import settings

logger = logging.getLogger(__name__)


# Keywords for deterministic task type classification (demo mode)
TASK_TYPE_KEYWORDS = {
    "math": ["calculate", "compute", "solve", "equation", "formula", "math", "arithmetic", "compound interest", "percentage", "statistics"],
    "code": ["code", "program", "script", "function", "debug", "implement", "refactor", "algorithm", "api", "database", "sql"],
    "file": ["read", "write", "file", "directory", "folder", "path", "list files", "create file", "delete file"],
    "research": ["research", "search", "find", "look up", "investigate", "analyze", "compare", "summary", "report"],
}


def classify_task_type(goal: str) -> str:
    """
    Classify task type based on goal keywords.
    Returns first matching type, defaults to 'mixed'.
    """
    goal_lower = goal.lower()
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        for keyword in keywords:
            if keyword in goal_lower:
                return task_type
    return "mixed"


def normalize_goal(goal: str) -> str:
    """
    Normalize goal text for consistent processing.
    """
    # Strip whitespace
    normalized = goal.strip()
    # Collapse multiple spaces
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


async def understand_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: normalize goal and determine task type.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with goal field.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission
            - settings: Application settings (optional)

    Returns:
        dict: State update with understood_task and task_type.

    Notes:
        - Emits planning_started event after understanding
        - In demo mode, uses deterministic classification
        - In live mode, could use LLM for more nuanced classification
    """
    logger.info(f"[understand_node] Starting understanding for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = config.get("runtime")

    goal = state.get("goal", "")
    if not goal or not goal.strip():
        logger.warning("[understand_node] Goal is empty")
        return {
            "understood_task": "",
            "task_type": "mixed",
        }

    try:
        # Normalize goal
        understood_task = normalize_goal(goal)

        # Classify task type
        # In demo mode, use deterministic classification
        # In live mode, could use LLM but deterministic is fine for MVP
        task_type = classify_task_type(goal)

        # Validate task_type
        if task_type not in VALID_TASK_TYPES:
            logger.warning(f"[understand_node] Invalid task_type '{task_type}', defaulting to 'mixed'")
            task_type = "mixed"

        logger.info(f"[understand_node] Understood task: {understood_task[:100]}..., task_type: {task_type}")

        # Emit planning_started event
        if runtime:
            try:
                await runtime.emit_event(
                    task_id=state["task_id"],
                    run_id=state["run_id"],
                    user_id=state["user_id"],
                    event_type="planning_started",
                    status="running",
                    metadata={
                        "task_type": task_type,
                        "goal_length": len(goal),
                    },
                )
                logger.debug("[understand_node] Emitted planning_started event")
            except Exception as e:
                logger.warning(f"[understand_node] Failed to emit planning_started event: {e}")

        return {
            "understood_task": understood_task,
            "task_type": task_type,
        }

    except Exception as e:
        logger.error(f"[understand_node] Unexpected error during understanding: {e}", exc_info=True)
        return {
            "understood_task": normalize_goal(goal),
            "task_type": "mixed",
        }


__all__ = ["understand_node", "classify_task_type", "normalize_goal"]
