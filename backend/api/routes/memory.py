"""
Memory and trusted recipe inspection endpoints.

Source of truth: BLUEPRINT.md §10, §11, §15, §18.

Endpoint:
- GET /memory/recipes: Paginated trusted recipes owned strictly by the authenticated user.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import PaginationParams, get_current_user, get_db
from backend.api.schemas import RecipeItem, RecipeListResponse
from backend.core.logging import get_logger
from backend.db.models import RecipeStatus, TaskRecipe, User

logger = get_logger(__name__)

router = APIRouter(tags=["Memory"])


@router.get("/memory/recipes", response_model=RecipeListResponse)
async def list_trusted_recipes(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> RecipeListResponse:
    """
    GET /memory/recipes
    Returns paginated trusted recipes belonging strictly to the authenticated user.
    Untrusted or candidate recipes are never exposed by this endpoint.
    Source: BLUEPRINT.md §10, §15.
    """
    trusted_status = RecipeStatus.TRUSTED.value

    # Count total trusted recipes for this user
    count_stmt = select(func.count(TaskRecipe.id)).where(
        TaskRecipe.user_id == current_user.id,
        TaskRecipe.status == trusted_status,
    )
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Query paginated trusted recipes
    items_stmt = (
        select(TaskRecipe)
        .where(
            TaskRecipe.user_id == current_user.id,
            TaskRecipe.status == trusted_status,
        )
        .order_by(TaskRecipe.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    items_result = await session.execute(items_stmt)
    records = items_result.scalars().all()

    items = [
        RecipeItem(
            recipe_id=r.id,
            task_type=r.task_type,
            problem_pattern=r.problem_pattern,
            recommended_strategy=r.recommended_strategy,
            usage_count=r.usage_count or 0,
            success_after_reuse=r.success_after_reuse or 0,
            created_at=r.created_at,
        )
        for r in records
    ]

    return RecipeListResponse(
        items=items,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )
