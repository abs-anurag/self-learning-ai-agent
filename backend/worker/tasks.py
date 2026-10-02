"""
Celery worker task: run_agent_task.

Source of truth: BLUEPRINT.md §1, §8, §15.

This is the single entry point invoked by the Celery worker process.
It creates an AgentRuntime, invokes AgentRuntime.run(), and handles
errors and cleanup.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from backend.core.logging import get_logger
from backend.db.models import Task, TaskRun, TaskStatus
from backend.worker.celery_app import app

logger = get_logger(__name__)


@app.task
def run_agent_task(
    run_id: str,
    *,
    task_id: Optional[str] = None,
    user_id: Optional[str] = None,
    goal: Optional[str] = None,
    task_type: str = "",
    max_iterations: Optional[int] = None,
) -> dict[str, Any]:
    """
    Celery task entry point: execute the agent graph for a task run.

    Source: BLUEPRINT.md §1, §8, §15.

    Args:
        run_id: Task run identifier (UUID string).
        task_id: Optional task identifier. If not provided, looked up from DB.
        user_id: Optional user identifier. If not provided, looked up from DB.
        goal: Optional task goal. If not provided, looked up from DB.
        task_type: Optional task type override.
        max_iterations: Optional iteration limit override.

    Returns:
        dict: Execution result with status, termination_reason, and final_response.
    """
    import asyncio

    from backend.agent.runtime import AgentRuntime
    from backend.db.session import async_session_factory, session_scope

    run_uuid = uuid.UUID(str(run_id))

    logger.info(f"[run_agent_task] Starting Celery task for run {run_id}")

    # Look up task/run metadata from PostgreSQL if not provided
    if task_id is None or user_id is None or goal is None:
        async def _lookup() -> dict[str, Any]:
            async with session_scope(async_session_factory) as session:
                from sqlalchemy import select

                run_result = await session.execute(
                    select(TaskRun).where(TaskRun.id == run_uuid)
                )
                run_record = run_result.scalar_one_or_none()
                if run_record is None:
                    raise RuntimeError(f"TaskRun {run_id} not found in database")

                task_result = await session.execute(
                    select(Task).where(Task.id == run_record.task_id)
                )
                task_record = task_result.scalar_one_or_none()

                return {
                    "task_id": str(run_record.task_id),
                    "user_id": str(run_record.user_id),
                    "goal": task_record.goal if task_record else "",
                    # task_type is determined by the understand node during execution;
                    # Task model does not have task_type column (stored in Experience/Recipe)
                    "task_type": "",
                }

        try:
            metadata = asyncio.run(_lookup())
        except Exception as exc:
            logger.error(f"[run_agent_task] Failed to lookup task metadata: {exc}", exc_info=True)
            # Mark run as failed
            asyncio.run(_mark_run_failed(run_uuid, "metadata_lookup_error"))
            return {"status": "failed", "error": str(exc)}

        task_id = task_id or metadata["task_id"]
        user_id = user_id or metadata["user_id"]
        goal = goal or metadata["goal"]
        task_type = task_type or metadata.get("task_type", "")

    # Mark run as running before invoking the agent
    try:
        asyncio.run(_mark_run_status(run_uuid, TaskStatus.RUNNING))
    except Exception as exc:
        logger.error(f"[run_agent_task] Failed to mark run as running: {exc}", exc_info=True)

    # Create runtime and execute
    runtime = AgentRuntime()
    try:
        final_state = asyncio.run(
            runtime.run(
                run_id=run_uuid,
                task_id=task_id,
                user_id=user_id,
                goal=goal,
                task_type=task_type,
                max_iterations=max_iterations,
            )
        )

        status = final_state.get("status", "failed")
        termination_reason = final_state.get("termination_reason") or "unknown"
        final_response = final_state.get("final_response", "")

        logger.info(
            f"[run_agent_task] Completed run {run_id}: status={status}, "
            f"termination_reason={termination_reason}"
        )

        return {
            "status": status,
            "termination_reason": termination_reason,
            "final_response": final_response,
            "iteration_count": final_state.get("iteration_count", 0),
        }
    except Exception as exc:
        logger.error(f"[run_agent_task] Agent execution failed for run {run_id}: {exc}", exc_info=True)
        try:
            asyncio.run(_mark_run_failed(run_uuid, "agent_execution_error"))
        except Exception:
            logger.warning(f"[run_agent_task] Failed to mark run as failed after error for {run_id}")
        return {"status": "failed", "error": str(exc)}
    finally:
        try:
            asyncio.run(runtime.close())
        except Exception:
            pass


async def _mark_run_status(run_id: uuid.UUID, status: TaskStatus) -> None:
    """Mark a run as running in PostgreSQL."""
    from sqlalchemy import select, update
    from backend.db.models import Task, TaskRun

    async with async_session_factory() as session:
        try:
            run_stmt = (
                update(TaskRun)
                .where(TaskRun.id == run_id)
                .values(status=status.value)
            )
            await session.execute(run_stmt)

            task_id_result = await session.execute(
                select(TaskRun.task_id).where(TaskRun.id == run_id)
            )
            task_id_row = task_id_result.scalar_one_or_none()
            if task_id_row is not None:
                task_stmt = (
                    update(Task)
                    .where(Task.id == task_id_row)
                    .values(status=status.value)
                )
                await session.execute(task_stmt)

            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _mark_run_failed(
    run_id: uuid.UUID,
    termination_reason: str,
) -> None:
    """Mark a run as failed in PostgreSQL."""
    from sqlalchemy import select, update
    from backend.db.models import Task, TaskRun

    async with async_session_factory() as session:
        try:
            run_stmt = (
                update(TaskRun)
                .where(TaskRun.id == run_id)
                .values(
                    status=TaskStatus.FAILED.value,
                    termination_reason=termination_reason,
                )
            )
            await session.execute(run_stmt)

            task_id_result = await session.execute(
                select(TaskRun.task_id).where(TaskRun.id == run_id)
            )
            task_id_row = task_id_result.scalar_one_or_none()
            if task_id_row is not None:
                task_stmt = (
                    update(Task)
                    .where(Task.id == task_id_row)
                    .values(status=TaskStatus.FAILED.value)
                )
                await session.execute(task_stmt)

            await session.commit()
        except Exception:
            await session.rollback()
            raise


__all__ = ["run_agent_task"]