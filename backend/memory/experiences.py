"""
Episodic experience persistence for audit and provenance.

Source of truth: BLUEPRINT.md §10, §18.
Stores raw execution records in the `experiences` table.
Not retrieved for future strategy (audit only).
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.db.models import Experience

logger = get_logger(__name__)


async def record_experience(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    task_type: str,
    tools_used: list[str],
    outcome_summary: str,
) -> Experience:
    """
    Persist an episodic experience row to the database.

    Args:
        session: Active SQLAlchemy async session.
        task_id: Associated task UUID.
        run_id: Associated run UUID.
        user_id: Owner user UUID.
        task_type: Categorized task type (math, research, file, code, mixed).
        tools_used: List of tool names invoked.
        outcome_summary: Final response or execution summary.

    Returns:
        The newly created Experience model.
    """
    experience = Experience(
        id=uuid.uuid4(),
        task_id=task_id,
        run_id=run_id,
        user_id=user_id,
        task_type=task_type or "research",
        tools_used=tools_used or [],
        outcome_summary=outcome_summary or "",
    )
    session.add(experience)
    await session.flush()
    logger.info("Recorded experience for task %s, run %s", task_id, run_id)
    return experience
