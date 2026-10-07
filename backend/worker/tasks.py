"""
Celery background worker tasks for METIS agent execution.

Source of truth: BLUEPRINT.md §8 Checkpointer Lifecycle, §14, §16.
Manages per-invocation database engine and AsyncPostgresSaver lifecycle.
Executes LangGraph StateGraph to terminal completion.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.agent.graph import create_agent_graph
from backend.agent.runtime import AgentRuntime, set_current_runtime
from backend.agent.state import create_initial_state
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import Task, TaskRun, TaskStatus
from backend.db.session import create_engine_instance, dispose_engine
from backend.events.schema import EventType
from backend.worker.celery_app import celery_app

logger = get_logger(__name__)


async def _execute_agent_run(run_id_str: str) -> None:
    """
    Asynchronous executor for an agent run instance.
    Implements per-invocation checkpointer and engine lifecycle.
    """
    run_id = uuid.UUID(run_id_str)
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    saver = None
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        saver = AsyncPostgresSaver(engine)
        if hasattr(saver, "setup"):
            await saver.setup()
    except Exception as exc:
        logger.warning("Checkpointer setup skipped: %s", exc)
        saver = None

    runtime = AgentRuntime(session_factory=session_factory)
    set_current_runtime(runtime)

    try:
        # 1. Fetch task and run records
        async with session_factory() as session:
            stmt = select(TaskRun).where(TaskRun.id == run_id)
            res = await session.execute(stmt)
            run = res.scalar_one_or_none()
            if run is None:
                logger.error("TaskRun %s not found in database.", run_id)
                return

            task_stmt = select(Task).where(Task.id == run.task_id)
            task_res = await session.execute(task_stmt)
            task = task_res.scalar_one_or_none()
            if task is None:
                logger.error("Task %s for run %s not found in database.", run.task_id, run_id)
                return

            task_id = task.id
            user_id = run.user_id
            goal = task.goal

            # 2. Status transition: pending -> running in single transaction per BLUEPRINT §15
            run.status = TaskStatus.RUNNING.value
            task.status = TaskStatus.RUNNING.value
            await session.commit()
            logger.info("Transitioned task %s and run %s to running.", task_id, run_id)

        # 3. Create initial state
        initial_state = create_initial_state(
            task_id=str(task_id),
            run_id=str(run_id),
            user_id=str(user_id),
            goal=goal,
        )

        # 4. Compile LangGraph and invoke
        app = create_agent_graph(checkpointer=saver)
        thread_config = AgentRuntime.get_thread_config(run_id)

        logger.info("Invoking LangGraph execution for run %s...", run_id)
        final_state = await app.ainvoke(initial_state, config=thread_config)
        logger.info(
            "LangGraph execution finished for run %s with status: %s",
            run_id,
            final_state.get("status"),
        )

    except Exception as exc:
        logger.exception("Fatal unhandled error executing run %s: %s", run_id, exc)
        # Mark run and task as failed
        try:
            async with session_factory() as session:
                await session.execute(
                    update(TaskRun)
                    .where(TaskRun.id == run_id)
                    .values(
                        status=TaskStatus.FAILED.value,
                        termination_reason="worker_crash",
                    )
                )
                stmt = select(TaskRun).where(TaskRun.id == run_id)
                r_res = await session.execute(stmt)
                r = r_res.scalar_one_or_none()
                if r:
                    await session.execute(
                        update(Task)
                        .where(Task.id == r.task_id)
                        .values(status=TaskStatus.FAILED.value)
                    )
                await session.commit()

            # Emit terminal failure event
            if r:
                await runtime.emit_event(
                    task_id=r.task_id,
                    run_id=run_id,
                    user_id=r.user_id,
                    event_type=EventType.TASK_FAILED,
                    status=TaskStatus.FAILED.value,
                    metadata={"error": "Worker process encountered an unexpected failure."},
                )
        except Exception as recovery_exc:
            logger.critical("Failed to record worker crash recovery: %s", recovery_exc)

    finally:
        # Cleanly dispose the per-invocation database engine
        await dispose_engine(engine)
        logger.info("Disposed execution engine for run %s.", run_id)


@celery_app.task(name="backend.worker.tasks.run_agent_task", bind=True)
def run_agent_task(self: Any, run_id: str) -> None:
    """
    Celery background worker entrypoint for agent execution.
    Invoked via run_agent_task.delay(str(run_id)).
    """
    logger.info("Celery worker received run_agent_task for run_id: %s", run_id)
    asyncio.run(_execute_agent_run(run_id))
