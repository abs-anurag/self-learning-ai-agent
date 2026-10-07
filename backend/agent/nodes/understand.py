"""
Understand node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §14.
Normalizes goal into understood_task and determines task_type.
Emits task_started event via Event Service.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from backend.agent.runtime import get_current_runtime
from backend.agent.state import VALID_TASK_TYPES, AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def understand_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: understand.
    Normalizes goal and classifies task_type.
    Emits task_started telemetry event.
    """
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    understand_res = await llm.understand(state)
    understood_task = understand_res.get("understood_task", state.get("goal", ""))
    task_type = understand_res.get("task_type", "research")

    # Ensure task_type is within valid vocabulary
    if task_type not in VALID_TASK_TYPES:
        task_type = "research"

    # Emit task_started event
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=uuid.UUID(state["user_id"]),
            event_type=EventType.TASK_STARTED,
            status="running",
            metadata={
                "goal": state["goal"],
                "understood_task": understood_task,
                "task_type": task_type,
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit task_started event: %s", exc)

    return {
        "understood_task": understood_task,
        "task_type": task_type,
        "current_step": "retrieve_memory",
    }
