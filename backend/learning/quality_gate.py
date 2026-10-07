"""
Quality gate evaluation for self-learning recipe promotion.

Source of truth: BLUEPRINT.md §10, §11, §12.
Promotion requirements:
1. deterministic_pass == True
2. tool_success == True
3. judge_score >= RECIPE_PROMOTION_THRESHOLD (8.5)
4. Non-duplicate: cosine_similarity < RECIPE_DUPLICATE_THRESHOLD (0.90)
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.state import AgentState
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import RecipeStatus, TaskRecipe
from backend.memory.embeddings import cosine_similarity, generate_embedding

logger = get_logger(__name__)


async def evaluate_quality_gate(
    state: AgentState,
    candidate: Optional[dict[str, Any]],
    session: Optional[AsyncSession] = None,
) -> tuple[str, str]:
    """
    Evaluate whether a candidate recipe qualifies for promotion to trusted memory.

    Returns:
        (decision, reason)
        where decision is one of: "promoted", "candidate_only", "skip"
    """
    if candidate is None:
        return "skip", "No candidate extracted or task was trivial/failed."

    eval_info = state.get("evaluation", {})
    if not eval_info.get("task_success", False):
        return "skip", "Task was not successful."

    if not eval_info.get("deterministic_pass", False):
        return "candidate_only", "Failed deterministic policy check."

    if not eval_info.get("tool_success", False):
        return "candidate_only", "Tool execution had errors or failures."

    judge_score = float(eval_info.get("judge_score", 0.0))
    if judge_score < settings.RECIPE_PROMOTION_THRESHOLD:
        return (
            "candidate_only",
            f"Judge score {judge_score:.1f} below promotion threshold ({settings.RECIPE_PROMOTION_THRESHOLD}).",
        )

    # Check for duplicate recipe owned by user with same task_type
    if session is not None:
        try:
            user_id = uuid.UUID(state["user_id"])
            task_type = candidate.get("task_type", "")
            cand_pattern = candidate.get("problem_pattern", "")
            cand_emb = generate_embedding(cand_pattern)

            stmt = (
                select(TaskRecipe)
                .where(
                    TaskRecipe.user_id == user_id,
                    TaskRecipe.status == RecipeStatus.TRUSTED.value,
                    TaskRecipe.task_type == task_type,
                )
            )
            result = await session.execute(stmt)
            existing_recipes = result.scalars().all()

            for existing in existing_recipes:
                if existing.embedding is not None:
                    sim = cosine_similarity(cand_emb, list(existing.embedding))
                    if sim >= settings.RECIPE_DUPLICATE_THRESHOLD:
                        logger.info(
                            "Recipe duplicate detected (similarity=%.3f >= %.3f). Suppressing duplicate.",
                            sim,
                            settings.RECIPE_DUPLICATE_THRESHOLD,
                        )
                        return "skip", f"Duplicate strategy detected (similarity {sim:.2f})."
        except Exception as exc:
            await session.rollback()
            logger.warning("Duplicate check failed: %s; proceeding with candidate_only", exc)
            return "candidate_only", f"Duplicate check error: {exc}"

    return "promoted", "Passed all quality gate criteria and high-bar score."
