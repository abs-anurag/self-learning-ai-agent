"""
Retrieve node: searches trusted recipes for the current user and task type.

Source of truth: BLUEPRINT.md §6, §8, §10, §14, §24.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from backend.agent.state import AgentState
from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)

# Standard Golden Demo recipe returned during Run B
GOLDEN_DEMO_RECIPE: dict[str, Any] = {
    "recipe_id": "r1-compound-interest",
    "task_type": "math",
    "problem_pattern": "compound interest with compounding frequency",
    "recommended_strategy": (
        "Use formula A = P * (1 + r/n) ** (n*t) where P is principal, "
        "r is annual rate, n is compounding frequency per year, and t is years."
    ),
    "successful_steps": [
        "Identify principal P, annual rate r, frequency n, and years t",
        "Evaluate compound amount A = P * (1 + r/n) ** (n*t) using calculator",
        "Present the final accumulated amount",
    ],
    "tools_used": ["calculator"],
}


async def retrieve_memory(state: AgentState) -> dict[str, Any]:
    """
    Queries task_recipes for current user; emits memory_retrieved event.
    Source: BLUEPRINT.md §8 line 329, §10, §14.
    """
    from backend.agent.runtime import get_current_runtime

    runtime = get_current_runtime()
    mode = getattr(settings, "EXECUTION_MODE", ExecutionMode.DEMO)
    goal = str(state.get("goal", "")).lower()

    retrieved: list[dict[str, Any]] = []

    if mode == ExecutionMode.DEMO or mode == "demo":
        # Deterministic fixture retriever for Golden Demo (BLUEPRINT.md §10, §24)
        # Run A (baseline $10,000) -> 0 hits
        # Run B (learned $5,000) -> 1 hit with Golden Demo recipe
        if "5,000" in goal or "5000" in goal or state.get("run_id") == "run_b":
            retrieved = [dict(GOLDEN_DEMO_RECIPE)]
        else:
            retrieved = []
    else:
        if runtime and runtime.persistence_enabled:
            from backend.memory.retriever import RecipeRetriever
            retrieved = await RecipeRetriever(runtime.session_factory).retrieve(
                user_id=str(state["user_id"]),
                task_type=str(state.get("task_type", "")),
                query=str(state.get("understood_task") or state.get("goal", "")),
            )

    # Emit telemetry event per BLUEPRINT.md §6 line 176, §14
    if runtime and runtime.event_service:
        try:
            await runtime.emit_event(
                task_id=state.get("task_id", ""),
                run_id=state.get("run_id", ""),
                user_id=state.get("user_id", ""),
                event_type=EventType.MEMORY_RETRIEVED,
                metadata={"hits": len(retrieved)},
            )
        except Exception as exc:
            logger.warning("Failed to emit memory_retrieved event: %s", exc)

    logger.info(
        "Node 'retrieve_memory' completed: hits=%d for run_id=%s",
        len(retrieved),
        state.get("run_id"),
    )

    return {
        "retrieved_recipes": retrieved,
        "current_step": "retrieve_memory",
    }
