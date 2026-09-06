"""
Episodic experiences persistence layer.

Source of truth: BLUEPRINT.md §3, §10, §18.

Design rules:
- Strictly persists episodic experiences to the `experiences` table.
- Purpose: Audit and provenance only.
- Strict isolation rule (§10):
  Episodic experiences are NEVER retrieved for future strategy alteration.
  Only trusted semantic recipes (`task_recipes`) are retrieved.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.db.models import Experience

logger = get_logger(__name__)


async def create_experience(
    session: AsyncSession,
    *,
    task_id: Union[uuid.UUID, str],
    run_id: Union[uuid.UUID, str],
    user_id: Union[uuid.UUID, str],
    task_type: str,
    outcome_summary: str,
    tools_used: Optional[list[Any]] = None,
    experience_id: Optional[Union[uuid.UUID, str]] = None,
) -> Experience:
    """
    Persist an episodic experience for provenance and audit.

    Does NOT vector index or make eligible for strategy retrieval (§10).
    """
    task_uuid = uuid.UUID(str(task_id))
    run_uuid = uuid.UUID(str(run_id))
    user_uuid = uuid.UUID(str(user_id))
    exp_uuid = uuid.UUID(str(experience_id)) if experience_id else uuid.uuid4()

    exp = Experience(
        id=exp_uuid,
        task_id=task_uuid,
        run_id=run_uuid,
        user_id=user_uuid,
        task_type=task_type,
        tools_used=tools_used or [],
        outcome_summary=outcome_summary,
    )

    session.add(exp)
    await session.flush()
    logger.info(
        "Persisted episodic experience %s for run %s (task_type=%s)",
        exp.id,
        run_uuid,
        task_type,
    )
    return exp


async def get_experience_by_id(
    session: AsyncSession,
    experience_id: Union[uuid.UUID, str],
) -> Optional[Experience]:
    """Retrieve an episodic experience by primary key."""
    exp_uuid = uuid.UUID(str(experience_id))
    result = await session.execute(
        select(Experience).where(Experience.id == exp_uuid)
    )
    return result.scalar_one_or_none()


async def get_experiences_for_run(
    session: AsyncSession,
    run_id: Union[uuid.UUID, str],
) -> list[Experience]:
    """Retrieve all episodic experiences recorded for a specific run."""
    run_uuid = uuid.UUID(str(run_id))
    result = await session.execute(
        select(Experience)
        .where(Experience.run_id == run_uuid)
        .order_by(Experience.created_at.asc())
    )
    return list(result.scalars().all())


async def get_experiences_for_task(
    session: AsyncSession,
    task_id: Union[uuid.UUID, str],
) -> list[Experience]:
    """Retrieve all episodic experiences recorded for a specific task."""
    task_uuid = uuid.UUID(str(task_id))
    result = await session.execute(
        select(Experience)
        .where(Experience.task_id == task_uuid)
        .order_by(Experience.created_at.asc())
    )
    return list(result.scalars().all())


async def get_experiences_for_user(
    session: AsyncSession,
    user_id: Union[uuid.UUID, str],
    *,
    limit: int = 50,
) -> list[Experience]:
    """Retrieve episodic experiences for audit/reporting for a specific user."""
    user_uuid = uuid.UUID(str(user_id))
    result = await session.execute(
        select(Experience)
        .where(Experience.user_id == user_uuid)
        .order_by(Experience.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
