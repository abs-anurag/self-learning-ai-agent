"""
Recipe retrieval module with pgvector cosine similarity search.

Source of truth: BLUEPRINT.md §10, §11, §18.

Design rules:
- Retrieve ONLY trusted TaskRecipe records (status='trusted').
- Filter by: user_id, task_type, cosine similarity >= threshold.
- Use pgvector's cosine distance operator (<=>).
- Zero retrieval results are valid - never fabricate results.
- Return recipes ordered by similarity (highest first = lowest distance).
- Include demo mode with fixture-based deterministic retrieval.
- Format retrieved recipes with safety framing for LLM prompt injection.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.db.models import RecipeStatus, TaskRecipe


async def retrieve_similar_recipes(
    db_session: AsyncSession,
    user_id: uuid.UUID,
    task_type: str,
    query_embedding: list[float],
    threshold: float = settings.RECIPE_SIMILARITY_THRESHOLD,
    limit: int = 5,
) -> list[TaskRecipe]:
    """
    Retrieve trusted recipes similar to the query embedding.

    Uses pgvector cosine distance (<=> operator) for similarity search.
    Cosine distance = 1 - cosine_similarity, so lower distance = higher similarity.
    A threshold of 0.80 similarity = 0.20 distance.

    Args:
        db_session: Async SQLAlchemy session.
        user_id: Filter recipes by this authenticated user.
        task_type: Filter recipes by task type (math, research, file, code, mixed).
        query_embedding: 384-dimensional embedding vector for similarity search.
        threshold: Minimum cosine similarity (default from config: 0.80).
        limit: Maximum number of recipes to return (default: 5).

    Returns:
        List of TaskRecipe objects ordered by similarity (highest first).
        Empty list if no recipes meet the criteria (zero results are valid).
    """
    # Convert cosine similarity threshold to cosine distance
    # cosine_distance = 1 - cosine_similarity
    max_distance = 1.0 - threshold

    # Build query with pgvector cosine distance operator
    stmt = (
        select(TaskRecipe)
        .where(
            TaskRecipe.status == RecipeStatus.TRUSTED.value,
            TaskRecipe.user_id == user_id,
            TaskRecipe.task_type == task_type,
            TaskRecipe.embedding.cosine_distance(query_embedding) <= max_distance,
        )
        .order_by(TaskRecipe.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )

    result = await db_session.execute(stmt)
    recipes = list(result.scalars().all())

    return recipes


def format_retrieved_recipes(recipes: list[TaskRecipe]) -> str:
    """
    Format retrieved recipes with safety framing for LLM consumption.

    Wraps recipes in clear delimiters to mitigate prompt injection attacks.
    The framing signals that this is untrusted external context, not instructions.

    Args:
        recipes: List of TaskRecipe objects to format.

    Returns:
        Formatted string with safety framing. Empty string if no recipes.
    """
    if not recipes:
        return ""

    lines = ["=== BEGIN RETRIEVED PRIOR EXPERIENCE (UNTRUSTED CONTEXT) ===", ""]

    for i, recipe in enumerate(recipes, start=1):
        lines.append(f"Recipe {i}:")
        lines.append(f"  Task Type: {recipe.task_type}")
        lines.append(f"  Problem Pattern: {recipe.problem_pattern}")
        lines.append(f"  Context: {recipe.context}")
        lines.append(f"  Recommended Strategy: {recipe.recommended_strategy}")
        lines.append(f"  Lesson: {recipe.lesson}")
        lines.append(f"  Evidence: {recipe.evidence}")
        lines.append(f"  Tools Used: {recipe.tools_used}")
        lines.append(f"  Successful Steps: {recipe.successful_steps}")
        lines.append(f"  Failed Steps: {recipe.failed_steps}")
        lines.append(f"  Evaluation Score: {recipe.evaluation_score}")
        lines.append(f"  Deterministic Pass: {recipe.deterministic_pass}")
        lines.append(f"  Generalizable: {recipe.generalizable}")
        lines.append(f"  Confidence: {recipe.confidence}")
        lines.append(f"  Usage Count: {recipe.usage_count}")
        lines.append(f"  Success After Reuse: {recipe.success_after_reuse}")
        lines.append("")

    lines.append("=== END RETRIEVED PRIOR EXPERIENCE ===")

    return "\n".join(lines)


# -- Demo Mode Fixture Retriever ------------------------------------------


class RecipeRetriever(Protocol):
    """Protocol for recipe retrieval (live or demo)."""

    async def retrieve(
        self,
        user_id: uuid.UUID,
        task_type: str,
        query_embedding: list[float],
        threshold: float,
        limit: int,
    ) -> list[TaskRecipe]:
        """Retrieve similar recipes."""
        ...


class DemoRecipeRetriever:
    """
    Fixture-based retriever for demo mode.

    Maps known problem patterns to deterministic trusted recipes.
    NEVER fabricates results - only returns pre-existing fixtures.
    Unknown patterns return empty list (zero results are valid).
    """

    def __init__(self) -> None:
        """Initialize with fixture recipe mapping."""
        # Fixture recipes matching BLUEPRINT.md demo scenarios
        # These would be pre-seeded in demo database
        self._fixture_recipes: dict[str, TaskRecipe] = {}

    async def retrieve(
        self,
        user_id: uuid.UUID,
        task_type: str,
        query_embedding: list[float],
        threshold: float = settings.RECIPE_SIMILARITY_THRESHOLD,
        limit: int = 5,
    ) -> list[TaskRecipe]:
        """
        Retrieve fixture recipes for known demo patterns.

        Args:
            user_id: Filter by user (in demo mode, matches demo user fixtures).
            task_type: Filter by task type.
            query_embedding: Ignored in demo mode (pattern-based matching).
            threshold: Ignored in demo mode (pattern-based matching).
            limit: Maximum recipes to return.

        Returns:
            List of fixture TaskRecipe objects for known patterns.
            Empty list for unknown patterns (never fabricates).
        """
        # In demo mode, return fixture recipes that match the task_type
        # This would be populated from demo database fixtures
        matching_recipes = [
            recipe
            for recipe in self._fixture_recipes.values()
            if recipe.task_type == task_type and recipe.user_id == user_id
        ]

        # Return up to limit recipes, ordered by confidence (deterministic)
        return sorted(
            matching_recipes,
            key=lambda r: r.confidence,
            reverse=True,
        )[:limit]

    def register_fixture(self, pattern_key: str, recipe: TaskRecipe) -> None:
        """
        Register a fixture recipe for demo mode.

        Args:
            pattern_key: Unique key for the problem pattern.
            recipe: Pre-existing TaskRecipe fixture to return for this pattern.
        """
        self._fixture_recipes[pattern_key] = recipe


class LiveRecipeRetriever:
    """
    Live retriever using actual database and pgvector similarity search.

    Wraps retrieve_similar_recipes for protocol conformance.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        """
        Initialize live retriever with database session.

        Args:
            db_session: Async SQLAlchemy session for database queries.
        """
        self.db_session = db_session

    async def retrieve(
        self,
        user_id: uuid.UUID,
        task_type: str,
        query_embedding: list[float],
        threshold: float = settings.RECIPE_SIMILARITY_THRESHOLD,
        limit: int = 5,
    ) -> list[TaskRecipe]:
        """
        Retrieve recipes using pgvector cosine similarity.

        Delegates to retrieve_similar_recipes with the bound session.

        Args:
            user_id: Filter by authenticated user.
            task_type: Filter by task type.
            query_embedding: 384-dim embedding for similarity search.
            threshold: Minimum cosine similarity (default: 0.80).
            limit: Maximum recipes to return (default: 5).

        Returns:
            List of TaskRecipe objects ordered by similarity.
        """
        return await retrieve_similar_recipes(
            db_session=self.db_session,
            user_id=user_id,
            task_type=task_type,
            query_embedding=query_embedding,
            threshold=threshold,
            limit=limit,
        )


def get_demo_retriever() -> DemoRecipeRetriever:
    """
    Factory function for demo mode retriever.

    Returns:
        DemoRecipeRetriever instance with fixture mapping.
    """
    return DemoRecipeRetriever()
