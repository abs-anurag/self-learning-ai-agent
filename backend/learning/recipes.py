"""
Recipe CRUD operations and counter management.

Source of truth: BLUEPRINT.md section10, section11, section18.

This module provides:
- TaskRecipe CRUD operations
- Recipe counter updates (usage_count, success_after_reuse)
- Recipe storage with validated embeddings
- Duplicate detection via cosine similarity
- Recipe versioning and status management
- Security: ensures recipes belong to correct user

Design rules:
- All functions use SQLAlchemy 2.0 async session patterns
- Proper type hints for all parameters and return values
- usage_count increments when recipe is retrieved for use
- success_after_reuse increments when a later task succeeds after reuse
- Security: user_id checked on all retrieval operations
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.db.models import RecipeStatus, TaskRecipe


async def create_trusted_recipe(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    recipe_data: dict,
    embedding: list[float],
) -> TaskRecipe:
    """
    Create a new trusted recipe with validated embedding.

    Source: BLUEPRINT.md section10, section11.

    Args:
        db_session: Async database session
        user_id: UUID of the user creating the recipe
        recipe_data: Dictionary containing recipe fields:
            - source_task_id: UUID of the source task
            - task_type: str (math, research, file, code, mixed)
            - problem_pattern: str
            - context: str
            - recommended_strategy: str
            - successful_steps: dict/list (JSONB)
            - failed_steps: dict/list (JSONB)
            - tools_used: dict/list (JSONB)
            - lesson: str
            - evidence: str
            - evaluation_score: Decimal (3,1)
            - deterministic_pass: bool
            - generalizable: bool
            - confidence: Decimal (3,2) [optional, defaults to 1.0]
            - version: int [optional, defaults to 1]
        embedding: List of 384 floats from sentence-transformers MiniLM-L6-v2

    Returns:
        TaskRecipe: The created recipe instance

    Raises:
        ValueError: If embedding dimension is not 384
        IntegrityError: If required fields are missing or invalid
    """
    # Validate embedding dimensions
    if len(embedding) != 384:
        raise ValueError(f"Embedding must be 384 dimensions, got {len(embedding)}")

    # Create the recipe instance
    recipe = TaskRecipe(
        source_task_id=recipe_data["source_task_id"],
        user_id=user_id,
        status=RecipeStatus.TRUSTED.value,
        task_type=recipe_data["task_type"],
        problem_pattern=recipe_data["problem_pattern"],
        context=recipe_data["context"],
        recommended_strategy=recipe_data["recommended_strategy"],
        successful_steps=recipe_data["successful_steps"],
        failed_steps=recipe_data["failed_steps"],
        tools_used=recipe_data["tools_used"],
        lesson=recipe_data["lesson"],
        evidence=recipe_data["evidence"],
        evaluation_score=recipe_data["evaluation_score"],
        deterministic_pass=recipe_data["deterministic_pass"],
        generalizable=recipe_data["generalizable"],
        confidence=recipe_data.get("confidence", 1.0),
        version=recipe_data.get("version", 1),
        usage_count=0,
        success_after_reuse=0,
        embedding=embedding,
    )

    db_session.add(recipe)
    await db_session.flush()
    await db_session.refresh(recipe)

    return recipe


async def find_similar_recipes(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    task_type: str,
    embedding: list[float],
    threshold: float,
) -> list[TaskRecipe]:
    """
    Find similar trusted recipes for duplicate detection.

    Source: BLUEPRINT.md section10, section11.
    Uses pgvector cosine similarity search with HNSW index.

    Args:
        db_session: Async database session
        user_id: UUID of the user (recipes are user-scoped)
        task_type: Task type to filter by (math, research, file, code, mixed)
        embedding: Query embedding (384 dimensions)
        threshold: Minimum cosine similarity (0.0-1.0)
                   Typical values:
                   - RECIPE_DUPLICATE_THRESHOLD (0.90) for duplicate detection
                   - RECIPE_SIMILARITY_THRESHOLD (0.80) for recipe retrieval

    Returns:
        List of TaskRecipe instances sorted by similarity (highest first)

    Raises:
        ValueError: If embedding dimension is not 384
    """
    # Validate embedding dimensions
    if len(embedding) != 384:
        raise ValueError(f"Embedding must be 384 dimensions, got {len(embedding)}")

    # Query using pgvector cosine similarity
    # cosine_distance returns 0-2 where 0 is identical
    # Convert to similarity: 1 - (distance / 2)
    stmt = (
        select(TaskRecipe)
        .where(
            TaskRecipe.user_id == user_id,
            TaskRecipe.task_type == task_type,
            TaskRecipe.status == RecipeStatus.TRUSTED.value,
        )
        .filter(
            TaskRecipe.embedding.cosine_distance(embedding) <= (1 - threshold)
        )
        .order_by(TaskRecipe.embedding.cosine_distance(embedding))
    )

    result = await db_session.execute(stmt)
    recipes = result.scalars().all()

    return list(recipes)


async def increment_recipe_usage(
    db_session: AsyncSession,
    recipe_id: uuid.UUID,
) -> None:
    """
    Increment usage_count when recipe is retrieved for actual use.

    Source: BLUEPRINT.md section10.

    This should be called when:
    - Recipe is retrieved and injected into agent context
    - Recipe is actually used in a task execution

    This should NOT be called when:
    - Just checking for duplicates
    - Recipe is only retrieved for display purposes

    Args:
        db_session: Async database session
        recipe_id: UUID of the recipe to update

    Raises:
        ValueError: If recipe_id does not exist
    """
    stmt = (
        update(TaskRecipe)
        .where(TaskRecipe.id == recipe_id)
        .values(usage_count=TaskRecipe.usage_count + 1)
    )

    result = await db_session.execute(stmt)

    if result.rowcount == 0:
        raise ValueError(f"Recipe {recipe_id} not found")

    await db_session.flush()


async def increment_recipe_success(
    db_session: AsyncSession,
    recipe_id: uuid.UUID,
) -> None:
    """
    Increment success_after_reuse when a later task succeeds after recipe reuse.

    Source: BLUEPRINT.md section10.

    This should be called when:
    - A task that used this recipe reaches 'succeeded' status
    - The evaluation shows task_success=True

    This should NOT be called when:
    - Recipe is just retrieved (use increment_recipe_usage instead)
    - Task fails or is still running

    Args:
        db_session: Async database session
        recipe_id: UUID of the recipe to update

    Raises:
        ValueError: If recipe_id does not exist
    """
    stmt = (
        update(TaskRecipe)
        .where(TaskRecipe.id == recipe_id)
        .values(success_after_reuse=TaskRecipe.success_after_reuse + 1)
    )

    result = await db_session.execute(stmt)

    if result.rowcount == 0:
        raise ValueError(f"Recipe {recipe_id} not found")

    await db_session.flush()


async def get_recipe_by_id(
    db_session: AsyncSession,
    recipe_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Optional[TaskRecipe]:
    """
    Retrieve a single recipe by ID with user ownership check.

    Source: BLUEPRINT.md section10, section17 (security).

    Args:
        db_session: Async database session
        recipe_id: UUID of the recipe to retrieve
        user_id: UUID of the user (security check)

    Returns:
        TaskRecipe instance if found and belongs to user, None otherwise

    Security:
        Ensures recipes can only be accessed by their owner.
        Returns None if recipe exists but belongs to different user.
    """
    stmt = select(TaskRecipe).where(
        TaskRecipe.id == recipe_id,
        TaskRecipe.user_id == user_id,
    )

    result = await db_session.execute(stmt)
    recipe = result.scalar_one_or_none()

    return recipe
