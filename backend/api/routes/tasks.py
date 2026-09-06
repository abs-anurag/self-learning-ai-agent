"""
Task management and execution result endpoints.

Source of truth: BLUEPRINT.md §1, §14, §15, §17, §18.

Endpoints:
- POST /tasks: Submit a goal, create task + run in pending status, enqueue Celery job, return 201.
- GET /tasks: Paginated task summaries belonging strictly to the authenticated user.
- GET /tasks/{id}: Task details and run history with ownership enforcement.
- GET /tasks/{id}/result: 409 Conflict if pending/running; 200 OK with evaluation if succeeded/failed.
"""

from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import (
    PaginationParams,
    get_current_user,
    get_db,
    rate_limit_task_creation,
)
from backend.api.schemas import (
    APIException,
    EvaluationSummary,
    RunSummaryItem,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskResultResponse,
    TaskSummaryItem,
)
from backend.core.logging import get_logger
from backend.db.models import (
    AgentEvent,
    Evaluation,
    Experience,
    Task,
    TaskRun,
    TaskStatus,
    User,
)

logger = get_logger(__name__)

router = APIRouter(tags=["Tasks"])


@router.post(
    "/tasks",
    response_model=TaskCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_task_creation)],
)
async def create_task(
    payload: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TaskCreateResponse:
    """
    POST /tasks
    Submit a task goal. Creates a task and initial run in 'pending' status,
    commits the database transaction, and dispatches a Celery execution job.
    Source: BLUEPRINT.md §1, §15, §17.
    """
    task_id = uuid.uuid4()
    run_id = uuid.uuid4()

    # Create task record owned by authenticated user (client user_id ignored)
    new_task = Task(
        id=task_id,
        user_id=current_user.id,
        goal=payload.goal,
        status=TaskStatus.PENDING.value,
    )

    # Create task_run record in pending status
    new_run = TaskRun(
        id=run_id,
        task_id=task_id,
        user_id=current_user.id,
        status=TaskStatus.PENDING.value,
        iteration_count=0,
        sequence_counter=0,
    )

    session.add(new_task)
    session.add(new_run)
    await session.flush()
    await session.commit()

    logger.info(
        "Created task %s and run %s for user %s with status pending",
        task_id,
        run_id,
        current_user.id,
    )

    # Dispatch Celery background task per BLUEPRINT.md §1, §15
    try:
        from backend.worker.tasks import run_agent_task
    except (ImportError, AttributeError):
        logger.info(
            "Celery task dispatch pending Phase 4 worker implementation: run_id=%s",
            run_id,
        )
    else:
        # Worker exists – let any broker/runtime exception bubble up
        run_agent_task.delay(str(run_id))
        logger.info("Enqueued Celery job for run %s", run_id)

    return TaskCreateResponse(
        task_id=task_id,
        run_id=run_id,
        status=TaskStatus.PENDING.value,
    )


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    pagination: PaginationParams = Depends(),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TaskListResponse:
    """
    GET /tasks
    Returns paginated tasks belonging strictly to the authenticated caller.
    Source: BLUEPRINT.md §15.
    """
    # Count total tasks for authenticated user
    count_stmt = select(func.count(Task.id)).where(Task.user_id == current_user.id)
    total_result = await session.execute(count_stmt)
    total = total_result.scalar() or 0

    # Fetch paginated items
    items_stmt = (
        select(Task)
        .where(Task.user_id == current_user.id)
        .order_by(Task.created_at.desc())
        .offset(pagination.offset)
        .limit(pagination.limit)
    )
    items_result = await session.execute(items_stmt)
    tasks = items_result.scalars().all()

    items = [
        TaskSummaryItem(
            task_id=t.id,
            goal=t.goal,
            status=t.status.value if hasattr(t.status, "value") else str(t.status),
            created_at=t.created_at or datetime.now(timezone.utc),
            updated_at=t.updated_at or t.created_at or datetime.now(timezone.utc),
        )
        for t in tasks
    ]

    return TaskListResponse(
        items=items,
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get("/tasks/{id}", response_model=TaskDetailResponse)
async def get_task(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TaskDetailResponse:
    """
    GET /tasks/{id}
    Returns task aggregate and associated run history.
    Enforces strict user ownership: returns 404 if non-existent, 403 if unowned.
    Source: BLUEPRINT.md §15.
    """
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

    # Fetch runs for this task
    runs_stmt = (
        select(TaskRun)
        .where(TaskRun.task_id == id)
        .order_by(TaskRun.created_at.asc())
    )
    runs_result = await session.execute(runs_stmt)
    runs_records = runs_result.scalars().all()

    runs = [
        RunSummaryItem(
            run_id=r.id,
            status=r.status.value if hasattr(r.status, "value") else str(r.status),
            termination_reason=r.termination_reason,
            iteration_count=r.iteration_count or 0,
            created_at=r.created_at,
        )
        for r in runs_records
    ]

    return TaskDetailResponse(
        task_id=task.id,
        goal=task.goal,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        created_at=task.created_at or datetime.now(timezone.utc),
        updated_at=task.updated_at or task.created_at or datetime.now(timezone.utc),
        runs=runs,
    )


@router.get("/tasks/{id}/result", response_model=TaskResultResponse)
async def get_task_result(
    id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> TaskResultResponse:
    """
    GET /tasks/{id}/result
    Returns terminal execution response and evaluation metrics.
    If task is pending or running, returns HTTP 409 (TASK_NOT_COMPLETE).
    Source: BLUEPRINT.md §15.
    """
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

    task_status_str = task.status.value if hasattr(task.status, "value") else str(task.status)

    # Non-terminal state returns HTTP 409 Conflict
    if task_status_str in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value, "pending", "running"):
        raise APIException.task_not_complete(
            "The task has not reached a terminal state."
        )

    # Find the active/latest run for this task
    run_stmt = (
        select(TaskRun)
        .where(TaskRun.task_id == id)
        .order_by(TaskRun.created_at.desc())
        .limit(1)
    )
    run_result = await session.execute(run_stmt)
    run = run_result.scalars().first()

    run_id = run.id if run else id

    # Retrieve evaluation metrics if available
    evaluation_summary: Optional[EvaluationSummary] = None
    if run is not None:
        eval_stmt = (
            select(Evaluation)
            .where(Evaluation.run_id == run.id)
            .order_by(Evaluation.iteration_count.desc())
            .limit(1)
        )
        eval_result = await session.execute(eval_stmt)
        eval_record = eval_result.scalars().first()

        if eval_record is not None:
            # Raw judge_reasoning is strictly excluded from EvaluationSummary
            evaluation_summary = EvaluationSummary(
                task_success=eval_record.task_success,
                deterministic_pass=eval_record.deterministic_pass,
                tool_success=eval_record.tool_success,
                judge_score=float(eval_record.judge_score),
                iteration_count=eval_record.iteration_count,
                tool_call_count=eval_record.tool_call_count,
            )

    # Retrieve final response text from Experience or AgentEvent
    final_response: Optional[str] = None
    if run is not None:
        exp_stmt = (
            select(Experience)
            .where(Experience.run_id == run.id)
            .order_by(Experience.created_at.desc())
            .limit(1)
        )
        exp_result = await session.execute(exp_stmt)
        exp_record = exp_result.scalars().first()
        if exp_record and exp_record.outcome_summary:
            final_response = exp_record.outcome_summary
        else:
            evt_stmt = (
                select(AgentEvent)
                .where(
                    AgentEvent.run_id == run.id,
                    AgentEvent.event_type.in_(["task_completed", "task_failed"]),
                )
                .order_by(AgentEvent.sequence.desc())
                .limit(1)
            )
            evt_result = await session.execute(evt_stmt)
            evt_record = evt_result.scalars().first()
            if evt_record and evt_record.metadata_:
                final_response = (
                    evt_record.metadata_.get("final_response")
                    or evt_record.metadata_.get("outcome_summary")
                    or evt_record.metadata_.get("message")
                )

    return TaskResultResponse(
        task_id=task.id,
        run_id=run_id,
        status=task_status_str,
        final_response=final_response,
        evaluation=evaluation_summary,
    )
