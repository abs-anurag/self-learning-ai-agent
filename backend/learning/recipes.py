"""
Trusted recipe management and promotion.

Source of truth: BLUEPRINT.md §10, §11, §18.
Stores promoted strategies in the `task_recipes` table with pgvector embeddings.
Maintains atomic usage and success_after_reuse counters.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.db.models import RecipeStatus, TaskRecipe
from backend.memory.embeddings import generate_embedding

logger = get_logger(__name__)


async def promote_recipe_to_trusted(
    session: Optional[AsyncSession],
    state: AgentState,
    candidate: dict[str, Any],
) -> Optional[TaskRecipe]:
    """
    Insert a promoted recipe into task_recipes table with pgvector embedding.
    """
    if session is None:
        logger.debug("No DB session provided; promotion skipped.")
        return None

    try:
        user_id = uuid.UUID(state["user_id"])
        problem_pattern = candidate["problem_pattern"]
        task_type = candidate["task_type"]
        recommended_strategy = candidate["recommended_strategy"]
        successful_steps = candidate["successful_steps"]
        tools_used = candidate["tools_used"]

        # Generate 384-d vector embedding
        embedding = generate_embedding(f"{problem_pattern} {recommended_strategy}")

        recipe = TaskRecipe(
            id=uuid.uuid4(),
            user_id=user_id,
            task_type=task_type,
            problem_pattern=problem_pattern,
            recommended_strategy=recommended_strategy,
            successful_steps=successful_steps,
            tools_used=tools_used,
            embedding=embedding,
            status=RecipeStatus.TRUSTED.value,
            usage_count=0,
            success_after_reuse=0,
        )
        session.add(recipe)
        await session.flush()
        logger.info("Successfully promoted new trusted recipe %s for user %s", recipe.id, user_id)
        return recipe
    except Exception as exc:
        logger.error("Failed to promote recipe to task_recipes: %s", exc)
        return None


async def record_reuse_success(
    session: Optional[AsyncSession],
    recipe_id: str,
) -> None:
    """
    Increment success_after_reuse counter for a recipe atomically.
    Source: BLUEPRINT.md §11.
    """
    if session is None or not recipe_id:
        return

    try:
        r_uuid = uuid.UUID(recipe_id)
        stmt = (
            update(TaskRecipe)
            .where(TaskRecipe.id == r_uuid)
            .values(success_after_reuse=TaskRecipe.success_after_reuse + 1)
        )
        await session.execute(stmt)
        await session.flush()
        logger.info("Incremented success_after_reuse for recipe %s", recipe_id)
    except Exception as exc:
        logger.warning("Failed to record reuse success for recipe %s: %s", recipe_id, exc)
