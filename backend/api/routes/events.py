"""
Event replay fallback endpoint.

Source of truth: BLUEPRINT.md §14, §15.

Endpoint:
- GET /tasks/{id}/events: Queries durable agent events from PostgreSQL in ascending sequence order.
"""

from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas import APIException
from backend.core.logging import get_logger
from backend.db.models import Task, TaskRun, User
from backend.events.schema import EventEnvelope
from backend.events.service import EventService

logger = get_logger(__name__)

router = APIRouter(tags=["Events"])


@router.get("/tasks/{id}/events", response_model=List[EventEnvelope])
async def get_task_events(
    id: uuid.UUID,
    after_sequence: int = Query(default=0, ge=0, description="Retrieve events with sequence > after_sequence"),
    limit: int = Query(default=500, ge=1, le=1000, description="Maximum events to return (max 1000)"),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> List[EventEnvelope]:
    """
    GET /tasks/{id}/events
    HTTP replay fallback endpoint.
    Returns durable agent events in ascending sequence order for the task's active run.
    Source: BLUEPRINT.md §14, §15.
    """
    # 1. Verify task existence and ownership
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

    # 2. Find active or latest run for this task
    run_stmt = (
        select(TaskRun)
        .where(TaskRun.task_id == id)
        .order_by(TaskRun.created_at.desc())
        .limit(1)
    )
    run_result = await session.execute(run_stmt)
    run = run_result.scalars().first()

    if run is None:
        return []

    # 3. Retrieve durable events via EventService
    event_service = EventService()
    if hasattr(event_service, "get_events_after"):
        events = await event_service.get_events_after(
            run.id,
            after_sequence=after_sequence,
            limit=limit,
            session=session,
        )
    else:
        events = await event_service.get_events_for_run(
            run.id,
            after_sequence=after_sequence,
            limit=limit,
            session=session,
        )

    return events
