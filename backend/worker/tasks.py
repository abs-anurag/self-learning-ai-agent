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


async def _mark_run_status(
    session_factory: Any,
    run_id: uuid.UUID,
    status: TaskStatus,
) -> None:
    """Mark a run as running in PostgreSQL using the provided session factory."""
    from sqlalchemy import select, update

    async with session_factory() as session:
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
    session_factory: Any,
    run_id: uuid.UUID,
    termination_reason: str,
) -> None:
    """
    Mark a run as failed in PostgreSQL using the provided session factory.

    STATE-SAFE: Will NOT overwrite an already terminal 'succeeded' status.
    This prevents post-success cleanup exceptions from corrupting a
    legitimately successful run.
    """
    from sqlalchemy import select, update

    async with session_factory() as session:
        try:
            # CRITICAL: Only update if status is NOT already 'succeeded'.
            # This prevents the historical bug where checkpointer/cleanup
            # exceptions after successful completion would overwrite the
            # committed 'succeeded' status with 'failed'.
            run_stmt = (
                update(TaskRun)
                .where(TaskRun.id == run_id)
                .where(TaskRun.status != TaskStatus.SUCCEEDED.value)
                .values(
                    status=TaskStatus.FAILED.value,
                    termination_reason=termination_reason,
                )
            )
            result = await session.execute(run_stmt)
            rows_affected = result.rowcount

            if rows_affected == 0:
                # The run was already in a terminal 'succeeded' state.
                # Do NOT overwrite it. Log and return.
                logger.warning(
                    f"[_mark_run_failed] Skipping status overwrite for run {run_id}: "
                    f"run is already in terminal 'succeeded' state. "
                    f"Attempted termination_reason={termination_reason}"
                )
                await session.commit()
                return

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


async def _lookup_metadata(
    session_factory: Any,
    run_uuid: uuid.UUID,
) -> dict[str, Any]:
    """Look up task/run metadata from PostgreSQL."""
    from sqlalchemy import select

    async with session_factory() as session:
        run_result = await session.execute(
            select(TaskRun).where(TaskRun.id == run_uuid)
        )
        run_record = run_result.scalar_one_or_none()
        if run_record is None:
            raise RuntimeError(f"TaskRun {run_uuid} not found in database")

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
    from backend.db.session import create_engine_instance, dispose_engine
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    run_uuid = uuid.UUID(str(run_id))

    logger.info(f"[run_agent_task] Starting Celery task for run {run_id}")

    # Run all async operations in a single event loop with a per-invocation engine
    # Per BLUEPRINT.md §8: fresh async engine per Celery task invocation
    async def _run_all() -> dict[str, Any]:
        # Create per-invocation engine and session factory
        engine = create_engine_instance()
        session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        try:
            # Look up task/run metadata from PostgreSQL if not provided
            local_task_id = task_id
            local_user_id = user_id
            local_goal = goal
            local_task_type = task_type

            if local_task_id is None or local_user_id is None or local_goal is None:
                metadata = await _lookup_metadata(session_factory, run_uuid)
                local_task_id = local_task_id or metadata["task_id"]
                local_user_id = local_user_id or metadata["user_id"]
                local_goal = local_goal or metadata["goal"]
                local_task_type = local_task_type or metadata.get("task_type", "")

            # Mark run as running before invoking the agent
            await _mark_run_status(session_factory, run_uuid, TaskStatus.RUNNING)

            # Create runtime with per-invocation session factory and execute
            runtime = AgentRuntime(session_factory=session_factory)
            try:
                final_state = await runtime.run(
                    run_id=run_uuid,
                    task_id=local_task_id,
                    user_id=local_user_id,
                    goal=local_goal,
                    task_type=local_task_type,
                    max_iterations=max_iterations,
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
                # Mark run as failed (state-safe: won't overwrite 'succeeded')
                try:
                    await _mark_run_failed(session_factory, run_uuid, "agent_execution_error")
                except Exception as mark_exc:
                    logger.error(
                        f"[run_agent_task] Failed to mark run {run_id} as failed: {mark_exc}"
                    )
                return {"status": "failed", "error": str(exc)}
            finally:
                try:
                    await runtime.close()
                except Exception:
                    pass
        finally:
            # Dispose main engine - catch and log exceptions to avoid
            # propagating exceptions that would mark Celery task as failed
            # after a successful run
            try:
                await dispose_engine(engine)
            except Exception as exc:
                logger.warning(
                    f"[run_agent_task] Failed to dispose main engine for run {run_id}: {exc}"
                )

    # Single asyncio.run() for the entire task - one event loop
    return asyncio.run(_run_all())


__all__ = [
    "run_agent_task",
    "_mark_run_status",
    "_mark_run_failed",
    "_lookup_metadata",
]