"""
User feedback submission endpoint.

Source of truth: BLUEPRINT.md §15, §18.

Endpoint:
- POST /tasks/{id}/feedback: Records user rating (1-5) and optional comment.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas import (
    APIException,
    FeedbackCreateRequest,
    FeedbackCreateResponse,
)
from backend.core.logging import get_logger
from backend.db.models import Feedback, Task, User

logger = get_logger(__name__)

router = APIRouter(tags=["Feedback"])


@router.post(
    "/tasks/{id}/feedback",
    response_model=FeedbackCreateResponse,
    status_code=status.HTTP_200_OK,
)
async def create_feedback(
    id: uuid.UUID,
    payload: FeedbackCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> FeedbackCreateResponse:
    """
    POST /tasks/{id}/feedback
    Records user feedback for a task.
    Enforces task existence, user ownership, and rating bounds (1-5).
    Source: BLUEPRINT.md §15.
    """
    # 1. Verify task exists and caller owns it
    stmt = select(Task).where(Task.id == id)
    result = await session.execute(stmt)
    task = result.scalar_one_or_none()

    if task is None:
        raise APIException.task_not_found(
            "The requested task was not found or is not owned by the caller."
        )

    if task.user_id != current_user.id:
        raise APIException.forbidden(
            "The authenticated user does not own this resource."
        )

    # 2. Insert feedback record
    feedback_id = uuid.uuid4()
    new_feedback = Feedback(
        id=feedback_id,
        task_id=id,
        user_id=current_user.id,
        rating=payload.rating,
        comment=payload.comment,
    )

    session.add(new_feedback)
    await session.flush()
    await session.commit()

    logger.info(
        "Recorded feedback %s for task %s from user %s (rating: %d)",
        feedback_id,
        id,
        current_user.id,
        payload.rating,
    )

    return FeedbackCreateResponse(
        feedback_id=feedback_id,
        status="recorded",
    )
