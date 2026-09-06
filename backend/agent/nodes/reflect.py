"""
Reflect node: formulates structured diagnosis of failure to guide the next iteration plan.

Source of truth: BLUEPRINT.md §6, §8 line 334, §14, §15, §17.
"""

from __future__ import annotations

from typing import Any, Dict

from backend.agent.prompts import build_reflection_prompt
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def reflect(state: AgentState) -> dict[str, Any]:
    """
    Analyzes execution failure and extracts actionable diagnosis.
    Source: BLUEPRINT.md §8 line 334, §14, §15.
    """
    from backend.agent.runtime import get_current_runtime, get_llm_provider

    runtime = get_current_runtime()
    provider = runtime.llm_provider if runtime else get_llm_provider()

    # Call LLM provider reflection
    response = await provider.reflect(state)

    reflection_text: str = ""
    if isinstance(response, dict) and "reflection" in response:
        reflection_text = str(response["reflection"])
    elif isinstance(response, str):
        reflection_text = response
    else:
        reflection_text = "Failure diagnosis: strategy adjustment required for missing parameters or formula."

    # Emit reflection_completed event (metadata stripped of raw CoT/essays per §17)
    if runtime and runtime.event_service:
        try:
            await runtime.emit_event(
                task_id=state.get("task_id", ""),
                run_id=state.get("run_id", ""),
                user_id=state.get("user_id", ""),
                event_type=EventType.REFLECTION_COMPLETED,
                metadata={
                    "iteration": state.get("iteration_count", 1),
                    "diagnosis_summary": reflection_text[:120],
                },
            )
        except Exception as exc:
            logger.warning("Failed to emit reflection_completed event: %s", exc)

    logger.info(
        "Node 'reflect' completed for run_id=%s: %s",
        state.get("run_id"),
        reflection_text[:60],
    )

    return {
        "reflection": reflection_text,
        "current_step": "reflect",
    }
