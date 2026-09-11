"""
Plan node: formulates initial action plan, incorporating retrieved recipe context.

Source of truth: BLUEPRINT.md §6, §8, §10, §14, §15.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.prompts import build_planning_prompt
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


async def plan(state: AgentState) -> dict[str, Any]:
    """
    Formulates initial action plan based on goal and any retrieved recipe context.
    Source: BLUEPRINT.md §8 line 330, §14, §15.
    """
    from backend.agent.runtime import get_current_runtime, get_llm_provider

    runtime = get_current_runtime()
    provider = runtime.llm_provider if runtime else get_llm_provider()

    # Emit planning_started telemetry event per BLUEPRINT.md §14
    if runtime and runtime.event_service:
        try:
            await runtime.emit_event(
                task_id=state.get("task_id", ""),
                run_id=state.get("run_id", ""),
                user_id=state.get("user_id", ""),
                event_type=EventType.PLANNING_STARTED,
                metadata={
                    "step": "plan",
                    "task_type": state.get("task_type", ""),
                    "has_retrieved_recipes": bool(state.get("retrieved_recipes")),
                },
            )
        except Exception as exc:
            logger.warning("Failed to emit planning_started event: %s", exc)

    # Call LLM provider (FixtureProvider in demo, AnthropicProvider in live)
    try:
        response = await provider.plan(state)
    except TimeoutError:
        return {"termination_reason": "timeout", "error": "Language model request timed out.", "current_step": "plan"}
    except Exception:
        return {"termination_reason": "llm_failure", "error": "Language model provider returned an error.", "current_step": "plan"}

    plan_steps: list[str] = []
    if isinstance(response, dict) and "plan" in response:
        plan_steps = response["plan"] if isinstance(response["plan"], list) else [str(response["plan"])]
    elif isinstance(response, list):
        plan_steps = [str(s) for s in response]
    else:
        plan_steps = ["Analyze task requirements", "Execute relevant calculation or tool", "Deliver result"]

    logger.info(
        "Node 'plan' completed: %d steps for run_id=%s",
        len(plan_steps),
        state.get("run_id"),
    )

    return {
        "plan": plan_steps,
        "current_step": "plan",
    }
