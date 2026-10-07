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
from backend.db.session import (
    create_engine_instance,
    dispose_engine,
    get_psycopg_postgres_url,
)
from backend.events.schema import EventType
from backend.worker.celery_app import celery_app

logger = get_logger(__name__)


async def _execute_agent_run(run_id_str: str, llm_provider: Optional[Any] = None) -> str:
    """
    Asynchronous executor for an agent run instance.
    Implements per-invocation checkpointer and engine lifecycle.
    Returns outcome status ("completed", "discarded_stale", "discarded_orphaned", "discarded_terminal", "failed").
    """
    try:
        run_id = uuid.UUID(run_id_str)
    except (ValueError, TypeError) as exc:
        logger.info("Discarding malformed Celery task: invalid run_id '%s': %s", run_id_str, exc)
        return "discarded_stale"

    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    saver_cm = None
    saver = None

    try:
        # 1. Fetch task and run records; discard stale/nonexistent messages cleanly
        async with session_factory() as session:
            stmt = select(TaskRun).where(TaskRun.id == run_id)
            res = await session.execute(stmt)
            run = res.scalar_one_or_none()
            if run is None:
                logger.info("Discarding stale Celery task: TaskRun %s not found in database.", run_id)
                return "discarded_stale"

            task_stmt = select(Task).where(Task.id == run.task_id)
            task_res = await session.execute(task_stmt)
            task = task_res.scalar_one_or_none()
            if task is None:
                logger.info(
                    "Discarding orphaned Celery task: Task %s for run %s not found in database.",
                    run.task_id,
                    run_id,
                )
                return "discarded_orphaned"

            if run.status in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value):
                logger.info(
                    "Discarding redundant Celery task: TaskRun %s is already terminal ('%s').",
                    run_id,
                    run.status,
                )
                return "discarded_terminal"

            task_id = task.id
            user_id = run.user_id
            goal = task.goal

            # 2. Status transition: pending -> running in single transaction per BLUEPRINT §15
            run.status = TaskStatus.RUNNING.value
            task.status = TaskStatus.RUNNING.value
            await session.commit()
            logger.info("Transitioned task %s and run %s to running.", task_id, run_id)

        # 3. Setup checkpointer for active run using standard psycopg connection string
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            conn_str = get_psycopg_postgres_url()
            saver_cm = AsyncPostgresSaver.from_conn_string(conn_str)
            saver = await saver_cm.__aenter__()
            if hasattr(saver, "setup"):
                await saver.setup()
            logger.info("Initialized AsyncPostgresSaver checkpointer for run %s.", run_id)
        except Exception as exc:
            logger.warning("Checkpointer setup skipped: %s", exc)
            if saver_cm is not None:
                try:
                    await saver_cm.__aexit__(None, None, None)
                except Exception:
                    pass
                saver_cm = None
            saver = None

        runtime = AgentRuntime(llm_provider=llm_provider, session_factory=session_factory)
        set_current_runtime(runtime)

        # 4. Create initial state
        initial_state = create_initial_state(
            task_id=str(task_id),
            run_id=str(run_id),
            user_id=str(user_id),
            goal=goal,
        )

        # 5. Compile LangGraph and invoke
        app = create_agent_graph(checkpointer=saver)
        thread_config = AgentRuntime.get_thread_config(run_id)

        logger.info("BEFORE graph invocation returns: invoking LangGraph for run %s...", run_id)
        final_state = await app.ainvoke(initial_state, config=thread_config)
        logger.info(
            "AFTER graph invocation returns: LangGraph finished for run %s with status: %s",
            run_id,
            final_state.get("status"),
        )

        # 5. Final task status reconciliation - ensure never left running in DB
        desired_status = final_state.get("status")
        if desired_status not in (TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value):
            desired_status = (
                TaskStatus.SUCCEEDED.value
                if final_state.get("evaluation", {}).get("task_success", False)
                else TaskStatus.FAILED.value
            )

        logger.info("BEFORE task status = %s: reconciling DB for run %s", desired_status, run_id)
        async with session_factory() as session:
            try:
                term_reason = final_state.get("termination_reason") or (
                    "success" if desired_status == TaskStatus.SUCCEEDED.value else "unknown"
                )
                run_upd = (
                    update(TaskRun)
                    .where(TaskRun.id == run_id)
                    .values(
                        status=desired_status,
                        termination_reason=term_reason,
                    )
                )
                await session.execute(run_upd)
                task_upd = (
                    update(Task)
                    .where(Task.id == task_id)
                    .values(status=desired_status)
                )
                await session.execute(task_upd)
                await session.commit()
                logger.info("AFTER task status = %s: reconciled DB for run %s", desired_status, run_id)
            except Exception as final_db_exc:
                await session.rollback()
                logger.error("Failed in task finalization DB update for run %s: %s", run_id, final_db_exc)

        return "completed"

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

        return "failed"

    finally:
        if saver_cm is not None:
            try:
                await saver_cm.__aexit__(None, None, None)
                logger.info("Closed checkpointer connection for run %s.", run_id)
            except Exception as close_exc:
                logger.warning("Failed to close checkpointer connection: %s", close_exc)
        # Cleanly dispose the per-invocation database engine
        await dispose_engine(engine)
        logger.info("Disposed execution engine for run %s.", run_id)


@celery_app.task(name="backend.worker.tasks.run_agent_task", bind=True)
def run_agent_task(self: Any, run_id: str) -> dict[str, Any]:
    """
    Celery background worker entrypoint for agent execution.
    Invoked via run_agent_task.delay(str(run_id)).
    """
    logger.info("Celery worker received run_agent_task for run_id: %s", run_id)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            outcome = pool.submit(asyncio.run, _execute_agent_run(run_id)).result()
    else:
        outcome = asyncio.run(_execute_agent_run(run_id))

    if outcome in ("discarded_stale", "discarded_orphaned", "discarded_terminal"):
        return {"status": "discarded", "reason": outcome, "run_id": run_id}
    return {"status": outcome, "run_id": run_id}
