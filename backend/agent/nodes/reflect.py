"""
Reflect node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §14.
Formulates structured diagnosis of failure for next plan iteration.
Emits reflection_completed telemetry event.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def reflect_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: reflect.
    Calls LLM provider to formulate reflection on execution failure.
    Emits reflection_completed event.
    """
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    reflect_res = await llm.reflect(state)
    reflection = reflect_res.get("reflection", "Strategy adjustment needed.")

    # Emit reflection_completed event
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=uuid.UUID(state["user_id"]),
            event_type=EventType.REFLECTION_COMPLETED,
            status="running",
            metadata={
                "iteration_count": state.get("iteration_count", 1),
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit reflection_completed event: %s", exc)

    return {
        "reflection": reflection,
        "current_step": "replan",
    }
