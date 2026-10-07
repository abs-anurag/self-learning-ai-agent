"""
Recipe retriever for semantic memory lookup.

Source of truth: BLUEPRINT.md §10, §18.
Retrieves trusted recipes matching current user, task type, and similarity threshold.
Updates usage_count atomically using SQL increment (§11).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger
from backend.db.models import RecipeStatus, TaskRecipe
from backend.memory.embeddings import cosine_similarity, generate_embedding

logger = get_logger(__name__)


async def retrieve_trusted_recipes(
    session: Optional[AsyncSession],
    *,
    user_id: uuid.UUID,
    task_type: str,
    goal: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """
    Retrieve trusted recipes for the given user, task_type, and goal.

    Constraints:
    1. recipe.status == 'trusted'
    2. recipe.user_id == authenticated_user_id (cross-user strictly prohibited)
    3. recipe.task_type == current_task_type
    4. cosine_similarity >= RECIPE_SIMILARITY_THRESHOLD (default: 0.80)
    5. Atomic increment of usage_count for each retrieved recipe.
    """
    if session is None:
        logger.debug("No DB session provided for recipe retrieval; returning empty.")
        return []

    try:
        # Query recipes for this user and task_type
        stmt = (
            select(TaskRecipe)
            .where(
                TaskRecipe.user_id == user_id,
                TaskRecipe.status == RecipeStatus.TRUSTED.value,
                TaskRecipe.task_type == task_type,
            )
        )
        result = await session.execute(stmt)
        candidates = result.scalars().all()

        if not candidates:
            return []

        task_embedding = generate_embedding(goal)
        matched_recipes: list[tuple[float, TaskRecipe]] = []

        threshold = settings.RECIPE_SIMILARITY_THRESHOLD

        for recipe in candidates:
            if recipe.embedding is None:
                continue

            # Convert embedding to list of floats if needed
            emb = list(recipe.embedding) if hasattr(recipe.embedding, "__iter__") else []
            sim = cosine_similarity(task_embedding, emb)

            if sim >= threshold:
                matched_recipes.append((sim, recipe))

        # Sort by similarity descending
        matched_recipes.sort(key=lambda x: x[0], reverse=True)
        top_matches = matched_recipes[:limit]

        retrieved: list[dict[str, Any]] = []
        for sim, recipe in top_matches:
            # Atomic increment of usage_count per BLUEPRINT.md §11
            inc_stmt = (
                update(TaskRecipe)
                .where(TaskRecipe.id == recipe.id)
                .values(usage_count=TaskRecipe.usage_count + 1)
            )
            await session.execute(inc_stmt)

            retrieved.append({
                "recipe_id": str(recipe.id),
                "task_type": recipe.task_type,
                "problem_pattern": recipe.problem_pattern,
                "recommended_strategy": recipe.recommended_strategy,
                "successful_steps": recipe.successful_steps,
                "tools_used": recipe.tools_used,
                "similarity": round(sim, 4),
            })

        if retrieved:
            await session.commit()
            logger.info("Retrieved %d trusted recipe(s) for user %s", len(retrieved), user_id)

        return retrieved

    except Exception as exc:
        logger.warning("Recipe retrieval encountered error: %s", exc)
        return []
