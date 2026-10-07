"""
Recipe candidate extraction from successful agent runs.

Source of truth: BLUEPRINT.md §10, §11, §18.
When a non-trivial execution succeeds, extracts candidate strategy
and persists to recipe_candidates table with status='candidate'.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.db.models import CandidateStatus, RecipeCandidate

logger = get_logger(__name__)


def extract_candidate_recipe(state: AgentState) -> Optional[dict[str, Any]]:
    """
    Extract a candidate recipe dictionary from state.
    Returns None if execution was trivial or failed.
    """
    eval_info = state.get("evaluation", {})
    if not eval_info.get("task_success", False):
        return None

    goal = state.get("goal", "").strip()
    if len(goal) < 5:
        # Trivial task - do not extract candidate
        return None

    task_type = state.get("task_type") or "research"
    plan = state.get("plan", [])
    tool_calls = state.get("tool_calls", [])
    tools_used = list(dict.fromkeys(
        tc.get("tool") for tc in tool_calls if isinstance(tc, dict) and tc.get("tool")
    ))

    # Formulate problem pattern and recommended strategy
    problem_pattern = state.get("understood_task") or goal
    if len(problem_pattern) > 200:
        problem_pattern = problem_pattern[:200]

    if plan:
        recommended_strategy = "; ".join(plan[:3])
    else:
        recommended_strategy = f"Direct resolution strategy for {task_type} task."

    candidate = {
        "task_type": task_type,
        "problem_pattern": problem_pattern,
        "recommended_strategy": recommended_strategy,
        "successful_steps": plan,
        "tools_used": tools_used,
        "status": CandidateStatus.CANDIDATE.value,
    }
    return candidate


async def record_recipe_candidate(
    session: Optional[AsyncSession],
    state: AgentState,
    candidate: dict[str, Any],
) -> Optional[RecipeCandidate]:
    """Persist candidate recipe to recipe_candidates table."""
    if session is None:
        return None

    try:
        run_id = uuid.UUID(state["run_id"])
        user_id = uuid.UUID(state["user_id"])

        record = RecipeCandidate(
            id=uuid.uuid4(),
            run_id=run_id,
            user_id=user_id,
            task_type=candidate["task_type"],
            problem_pattern=candidate["problem_pattern"],
            recommended_strategy=candidate["recommended_strategy"],
            successful_steps=candidate["successful_steps"],
            tools_used=candidate["tools_used"],
            status=candidate.get("status", CandidateStatus.CANDIDATE.value),
        )
        session.add(record)
        await session.flush()
        logger.info("Persisted recipe candidate for run %s", run_id)
        return record
    except Exception as exc:
        logger.error("Failed to persist recipe candidate: %s", exc)
        return None
