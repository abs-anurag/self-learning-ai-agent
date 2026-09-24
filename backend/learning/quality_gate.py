"""
Recipe quality gate for promotion decision-making.

Source of truth: BLUEPRINT.md S10, S11 (quality criteria and thresholds).

The quality gate orchestrates promotion flow but delegates actual persistence.
It is DECISION-ONLY and does NOT:
- Write TaskRecipe records directly
- Emit events directly
- Perform unrelated persistence

PROMOTION FLOW:
1. Validate candidate
2. Build deterministic recipe embedding text (using embeddings.py)
3. Generate and validate 384-dimensional embedding
4. Query trusted recipes for same user and task_type (using recipes.py find_similar_recipes)
5. Check duplicate threshold (>= 0.90)
6. If duplicate: return decision "skip" with reason
7. If non-duplicate and all checks pass: return decision "promoted" with validated embedding
8. If any check fails: return decision "candidate_only" with reason

Design rules:
- All functions use SQLAlchemy 2.0 async session patterns
- Proper type hints for all parameters and return values
- Comprehensive docstrings
- Security: ensures candidates belong to correct user
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings
from backend.db.models import RecipeCandidate
from backend.learning.recipes import find_similar_recipes
from backend.memory.embeddings import build_recipe_embedding_text, generate_embedding


async def evaluate_for_promotion(
    db_session: AsyncSession,
    candidate: RecipeCandidate,
    task_data: dict[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """
    Evaluate a recipe candidate for promotion to trusted recipe.

    Source: BLUEPRINT.md S11 (quality gate criteria).

    This function orchestrates the promotion decision but does NOT persist
    anything. It returns a decision that the caller can act upon.

    Args:
        db_session: Async database session (for duplicate checking)
        candidate: RecipeCandidate instance to evaluate
        task_data: Additional task context:
            - canonical_task_success: bool (from candidate.py evaluation)
            - Any other contextual data needed for quality checks
        settings: Application settings (thresholds, etc.)

    Returns:
        dict with keys:
            - decision: "promoted" | "candidate_only" | "skip"
            - reason: str (explanation of the decision)
            - embedding: list[float] | None (384-dim, only if decision=="promoted")
            - duplicate_of: uuid.UUID | None (recipe_id if duplicate found)

    Quality Checks (ALL must pass for promotion):
        1. canonical_task_success (from task_data)
        2. evaluation_score >= 8.5 (RECIPE_PROMOTION_THRESHOLD)
        3. deterministic_pass
        4. tool_success (derived from task_data)
        5. generalizable (from candidate)
        6. required recipe fields present (problem_pattern, recommended_strategy,
           successful_steps, lesson)
        7. non-duplicate (cosine similarity < RECIPE_DUPLICATE_THRESHOLD 0.90)

    Notes:
        - Duplicate check uses RECIPE_DUPLICATE_THRESHOLD (0.90)
        - Promotion requires RECIPE_PROMOTION_THRESHOLD (8.5)
        - User-scoped: only checks duplicates against same user's recipes
        - Embedding is generated if all non-duplicate checks pass
    """
    # Run all quality criteria checks
    all_passed, failed_checks = check_all_quality_criteria(
        candidate, task_data, settings
    )

    # If any non-duplicate checks failed, return candidate_only
    if not all_passed:
        reason = f"Quality checks failed: {', '.join(failed_checks)}"
        return {
            "decision": "candidate_only",
            "reason": reason,
            "embedding": None,
            "duplicate_of": None,
        }

    # All quality checks passed, now generate embedding and check for duplicates
    try:
        # Build deterministic recipe embedding text
        recipe_dict = {
            "problem_pattern": candidate.problem_pattern,
            "context": candidate.context,
            "recommended_strategy": candidate.recommended_strategy,
            "successful_steps": candidate.successful_steps,
            "tools_used": candidate.tools_used,
            "lesson": candidate.lesson,
        }
        embedding_text = build_recipe_embedding_text(recipe_dict)

        # Generate 384-dimensional embedding
        embedding = generate_embedding(embedding_text)

        # Validate embedding dimensions
        if len(embedding) != 384:
            return {
                "decision": "candidate_only",
                "reason": f"Invalid embedding dimensions: {len(embedding)} (expected 384)",
                "embedding": None,
                "duplicate_of": None,
            }

    except Exception as e:
        # Embedding generation failed
        return {
            "decision": "candidate_only",
            "reason": f"Embedding generation failed: {str(e)}",
            "embedding": None,
            "duplicate_of": None,
        }

    # Query trusted recipes for duplicates
    try:
        similar_recipes = await find_similar_recipes(
            db_session=db_session,
            user_id=candidate.user_id,
            task_type=candidate.task_type,
            embedding=embedding,
            threshold=settings.RECIPE_DUPLICATE_THRESHOLD,
        )

        # If any recipe found with similarity >= 0.90, it's a duplicate
        if similar_recipes:
            duplicate_recipe = similar_recipes[0]  # Highest similarity first
            return {
                "decision": "skip",
                "reason": f"Duplicate of existing recipe (similarity >= {settings.RECIPE_DUPLICATE_THRESHOLD})",
                "embedding": None,
                "duplicate_of": duplicate_recipe.id,
            }

    except Exception as e:
        # Duplicate check failed - safer to not promote
        return {
            "decision": "candidate_only",
            "reason": f"Duplicate check failed: {str(e)}",
            "embedding": None,
            "duplicate_of": None,
        }

    # All checks passed, non-duplicate: promote with embedding
    return {
        "decision": "promoted",
        "reason": "All quality checks passed, non-duplicate recipe",
        "embedding": embedding,
        "duplicate_of": None,
    }


def check_all_quality_criteria(
    candidate: RecipeCandidate,
    task_data: dict[str, Any],
    settings: Settings,
) -> tuple[bool, list[str]]:
    """
    Check all quality criteria for recipe promotion (excluding duplicate check).

    Source: BLUEPRINT.md S11 (quality gate criteria).

    Args:
        candidate: RecipeCandidate instance to evaluate
        task_data: Additional task context:
            - canonical_task_success: bool (required)
            - tool_success: bool (optional, defaults to False if not present)
        settings: Application settings (for RECIPE_PROMOTION_THRESHOLD)

    Returns:
        Tuple of (all_passed: bool, failed_checks: list[str])
        - all_passed: True if all checks passed, False otherwise
        - failed_checks: List of human-readable failure reasons

    Quality Checks:
        1. canonical_task_success (from task_data)
        2. evaluation_score >= 8.5 (RECIPE_PROMOTION_THRESHOLD)
        3. deterministic_pass (from candidate)
        4. tool_success (from task_data, defaults to False)
        5. generalizable (from candidate)
        6. required recipe fields present (problem_pattern, recommended_strategy,
           successful_steps, lesson)

    Notes:
        - Does NOT check for duplicates (that requires DB query with embedding)
        - All checks must pass for promotion eligibility
        - Field presence checks ensure non-empty strings and non-empty JSONB
    """
    failed_checks = []

    # 1. canonical_task_success
    canonical_task_success = task_data.get("canonical_task_success", False)
    if not canonical_task_success:
        failed_checks.append("canonical_task_success=False")

    # 2. evaluation_score >= RECIPE_PROMOTION_THRESHOLD (8.5)
    evaluation_score = candidate.evaluation_score
    if evaluation_score < Decimal(str(settings.RECIPE_PROMOTION_THRESHOLD)):
        failed_checks.append(
            f"evaluation_score={evaluation_score} < {settings.RECIPE_PROMOTION_THRESHOLD}"
        )

    # 3. deterministic_pass
    if not candidate.deterministic_pass:
        failed_checks.append("deterministic_pass=False")

    # 4. tool_success (default to False if not present in task_data)
    tool_success = task_data.get("tool_success", False)
    if not tool_success:
        failed_checks.append("tool_success=False")

    # 5. generalizable
    if not candidate.generalizable:
        failed_checks.append("generalizable=False")

    # 6. Required recipe fields present
    required_fields = {
        "problem_pattern": candidate.problem_pattern,
        "recommended_strategy": candidate.recommended_strategy,
        "successful_steps": candidate.successful_steps,
        "lesson": candidate.lesson,
    }

    for field_name, field_value in required_fields.items():
        if isinstance(field_value, str):
            # String fields must be non-empty after stripping
            if not field_value or not field_value.strip():
                failed_checks.append(f"{field_name} is empty")
        elif isinstance(field_value, (list, dict)):
            # JSONB fields must be non-empty collections
            if not field_value:
                failed_checks.append(f"{field_name} is empty")
        elif field_value is None:
            failed_checks.append(f"{field_name} is None")

    # Return results
    all_passed = len(failed_checks) == 0
    return all_passed, failed_checks
