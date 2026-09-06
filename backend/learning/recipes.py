"""
Trusted recipes persistence, promotion, deduplication, and atomic reuse tracking.

Source of truth: BLUEPRINT.md §1, §3, §7, §10, §11, §18.

Design rules:
- `task_recipes` is the single authoritative layer for trusted recipes.
- Only promoted recipes with `status = 'trusted'` and 384-d pgvector embedding.
- Concurrency-Safe Recipe Counters (§11):
  - Increment when retrieved: handled by `increment_recipe_usage` in `backend/memory/retriever.py`.
  - Increment when task succeeds after reuse:
    UPDATE task_recipes SET success_after_reuse = success_after_reuse + 1 WHERE id = :recipe_id;
  - If a task fails after reuse, `usage_count` remains incremented but `success_after_reuse` is NOT updated.
  - Counters are never read into Python, incremented, and written back.
- Duplicate Suppression (§10, §11):
  Before inserting a newly promoted recipe, checks existing trusted recipes owned by the user
  with the same task_type. If cosine_similarity >= RECIPE_DUPLICATE_THRESHOLD (0.90), suppresses creation.
"""

from __future__ import annotations

from decimal import Decimal
import uuid
from typing import Any, List, Optional, Tuple, Union

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import RecipeCandidate, RecipeStatus, TaskRecipe
from backend.memory.embeddings import cosine_similarity, generate_embedding

logger = get_logger(__name__)


async def find_duplicate_recipe(
    session: AsyncSession,
    *,
    user_id: Union[uuid.UUID, str],
    task_type: str,
    candidate_embedding: list[float],
    threshold: Optional[float] = None,
) -> Optional[Tuple[TaskRecipe, float]]:
    """
    Check if an existing trusted recipe for the user and task_type exceeds the duplicate threshold.
    Source: BLUEPRINT.md §10, §11.
    """
    user_uuid = uuid.UUID(str(user_id))
    dup_threshold = (
        threshold
        if threshold is not None
        else settings.RECIPE_DUPLICATE_THRESHOLD
    )

    stmt = select(TaskRecipe).where(
        TaskRecipe.user_id == user_uuid,
        TaskRecipe.task_type == task_type,
        TaskRecipe.status == RecipeStatus.TRUSTED.value,
    )
    result = await session.execute(stmt)
    existing_recipes = list(result.scalars().all())

    for recipe in existing_recipes:
        sim = cosine_similarity(recipe.embedding, candidate_embedding)
        if sim >= dup_threshold:
            logger.info(
                "Found duplicate recipe %s with similarity %.4f >= threshold %.2f",
                recipe.id,
                sim,
                dup_threshold,
            )
            return (recipe, sim)

    return None


async def promote_candidate(
    session: AsyncSession,
    *,
    candidate: RecipeCandidate,
    embedding: Optional[list[float]] = None,
    recipe_id: Optional[Union[uuid.UUID, str]] = None,
) -> TaskRecipe:
    """
    Promote a validated recipe candidate into task_recipes with status 'trusted'.
    Source: BLUEPRINT.md §7, §11, §18.
    """
    rec_uuid = uuid.UUID(str(recipe_id)) if recipe_id else uuid.uuid4()

    # Generate 384-d embedding from problem_pattern + recommended_strategy if not provided
    if embedding is None:
        text_to_embed = f"{candidate.problem_pattern} {candidate.recommended_strategy}"
        vector = generate_embedding(text_to_embed)
    else:
        vector = embedding

    recipe = TaskRecipe(
        id=rec_uuid,
        source_task_id=candidate.source_task_id,
        user_id=candidate.user_id,
        status=RecipeStatus.TRUSTED.value,
        task_type=candidate.task_type,
        problem_pattern=candidate.problem_pattern,
        context=candidate.context,
        recommended_strategy=candidate.recommended_strategy,
        successful_steps=candidate.successful_steps,
        failed_steps=candidate.failed_steps,
        tools_used=candidate.tools_used,
        lesson=candidate.lesson,
        evidence=candidate.evidence,
        evaluation_score=candidate.evaluation_score,
        deterministic_pass=candidate.deterministic_pass,
        generalizable=candidate.generalizable,
        confidence=Decimal("1.0"),
        version=1,
        usage_count=0,
        success_after_reuse=0,
        embedding=vector,
    )

    session.add(recipe)
    await session.flush()
    logger.info(
        "Promoted candidate %s to trusted recipe %s (user=%s, task_type=%s)",
        candidate.id,
        recipe.id,
        recipe.user_id,
        recipe.task_type,
    )
    return recipe


async def record_recipe_reuse_success(
    session: AsyncSession,
    recipe_id: Union[uuid.UUID, str],
) -> None:
    """
    Concurrency-safe atomic increment of success_after_reuse in PostgreSQL.
    Source: BLUEPRINT.md §11 Concurrency-Safe Recipe Counters.
    """
    rec_uuid = uuid.UUID(str(recipe_id))
    await session.execute(
        update(TaskRecipe)
        .where(TaskRecipe.id == rec_uuid)
        .values(success_after_reuse=TaskRecipe.success_after_reuse + 1)
    )
    await session.flush()
    logger.info("Atomically incremented success_after_reuse for recipe %s", rec_uuid)


async def get_trusted_recipes_for_user(
    session: AsyncSession,
    user_id: Union[uuid.UUID, str],
    task_type: Optional[str] = None,
) -> list[TaskRecipe]:
    """Retrieve all trusted recipes owned by a user, optionally filtered by task_type."""
    user_uuid = uuid.UUID(str(user_id))
    query = select(TaskRecipe).where(
        TaskRecipe.user_id == user_uuid,
        TaskRecipe.status == RecipeStatus.TRUSTED.value,
    )
    if task_type:
        query = query.where(TaskRecipe.task_type == task_type)

    query = query.order_by(TaskRecipe.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_recipe_by_id(
    session: AsyncSession,
    recipe_id: Union[uuid.UUID, str],
) -> Optional[TaskRecipe]:
    """Retrieve trusted recipe by primary key."""
    rec_uuid = uuid.UUID(str(recipe_id))
    result = await session.execute(
        select(TaskRecipe).where(TaskRecipe.id == rec_uuid)
    )
    return result.scalar_one_or_none()
