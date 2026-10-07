"""
Retrieve memory node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §10, §14.
Queries task_recipes for current user; emits memory_retrieved telemetry.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType
from backend.memory.retriever import retrieve_trusted_recipes

logger = get_logger(__name__)


async def retrieve_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: retrieve_memory.
    Retrieves trusted recipes from semantic memory for the authenticated user.
    Emits memory_retrieved event.
    """
    runtime = get_current_runtime()
    user_id = uuid.UUID(state["user_id"])
    task_type = state.get("task_type", "research")
    goal = state.get("goal", "")

    retrieved: list[dict[str, Any]] = []

    # If session factory is configured, retrieve from database
    if runtime.session_factory is not None:
        try:
            async with runtime.session_factory() as session:
                retrieved = await retrieve_trusted_recipes(
                    session=session,
                    user_id=user_id,
                    task_type=task_type,
                    goal=goal,
                )
        except Exception as exc:
            logger.warning("Error retrieving recipes from db: %s", exc)
            retrieved = []

    # Emit memory_retrieved event
    try:
        await runtime.emit_event(
            task_id=uuid.UUID(state["task_id"]),
            run_id=uuid.UUID(state["run_id"]),
            user_id=user_id,
            event_type=EventType.MEMORY_RETRIEVED,
            status="running",
            metadata={
                "recipe_count": len(retrieved),
                "task_type": task_type,
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit memory_retrieved event: %s", exc)

    return {
        "retrieved_recipes": retrieved,
        "current_step": "plan",
    }
