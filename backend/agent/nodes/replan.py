"""
Replan node: constructs revised plan addressing the diagnosed failure.

Source of truth: BLUEPRINT.md §6, §8 line 335.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.prompts import build_replan_prompt
from backend.agent.state import AgentState
from backend.core.logging import get_logger

logger = get_logger(__name__)


async def replan(state: AgentState) -> dict[str, Any]:
    """
    Constructs an updated plan incorporating the diagnosis from reflection.
    Source: BLUEPRINT.md §8 line 335.
    """
    from backend.agent.runtime import get_current_runtime, get_llm_provider

    runtime = get_current_runtime()
    provider = runtime.llm_provider if runtime else get_llm_provider()

    reflection = state.get("reflection", "")
    goal = state.get("goal", "")

    # Check provider plan or replan response
    response = await provider.plan(state)

    revised_steps: list[str] = []
    if isinstance(response, dict) and "plan" in response:
        revised_steps = response["plan"] if isinstance(response["plan"], list) else [str(response["plan"])]
    elif isinstance(response, list):
        revised_steps = [str(s) for s in response]
    else:
        revised_steps = [
            f"Apply correction: {reflection[:80]}",
            "Execute corrected tool computation",
            "Format and verify result",
        ]

    logger.info(
        "Node 'replan' completed: %d steps for run_id=%s",
        len(revised_steps),
        state.get("run_id"),
    )

    return {
        "plan": revised_steps,
        "current_step": "replan",
    }
