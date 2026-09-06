"""
Metrics aggregation endpoint for user-level performance and learning analytics.

Source of truth: BLUEPRINT.md §15.

Endpoint:
- GET /metrics: Returns 11 aggregate metrics calculated via SQL queries for the authenticated user.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_current_user, get_db
from backend.api.schemas import MetricsResponse
from backend.core.logging import get_logger
from backend.db.models import (
    AgentEvent,
    Evaluation,
    Task,
    TaskRecipe,
    TaskRun,
    TaskStatus,
    User,
)

logger = get_logger(__name__)

router = APIRouter(tags=["Metrics"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_user_metrics(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> MetricsResponse:
    """
    GET /metrics
    Computes real-time user-level performance and learning metrics.
    All calculations are strictly isolated to the authenticated user.
    Source: BLUEPRINT.md §15.
    """
    user_id = current_user.id

    # 1. total_tasks
    total_stmt = select(func.count(Task.id)).where(Task.user_id == user_id)
    total_tasks = (await session.execute(total_stmt)).scalar() or 0

    # 2. successful_tasks
    succ_stmt = select(func.count(Task.id)).where(
        Task.user_id == user_id,
        Task.status == TaskStatus.SUCCEEDED.value,
    )
    successful_tasks = (await session.execute(succ_stmt)).scalar() or 0

    # 3. failed_tasks
    fail_stmt = select(func.count(Task.id)).where(
        Task.user_id == user_id,
        Task.status == TaskStatus.FAILED.value,
    )
    failed_tasks = (await session.execute(fail_stmt)).scalar() or 0

    # 4. success_rate: successful_tasks / total_tasks (or 0.0)
    success_rate = (
        round(successful_tasks / total_tasks, 4)
        if total_tasks > 0
        else 0.0
    )

    # 5. average_iterations: Average iteration_count across completed runs
    avg_iter_stmt = select(func.avg(TaskRun.iteration_count)).where(
        TaskRun.user_id == user_id,
        TaskRun.status.in_([TaskStatus.SUCCEEDED.value, TaskStatus.FAILED.value]),
    )
    raw_avg_iter = (await session.execute(avg_iter_stmt)).scalar()
    average_iterations = round(float(raw_avg_iter), 2) if raw_avg_iter is not None else 0.0

    # 6. average_tool_calls: Average tool calls across evaluations
    avg_tool_stmt = select(func.avg(Evaluation.tool_call_count)).where(
        Evaluation.user_id == user_id
    )
    raw_avg_tool = (await session.execute(avg_tool_stmt)).scalar()
    average_tool_calls = round(float(raw_avg_tool), 2) if raw_avg_tool is not None else 0.0

    # 7. recipes_promoted: Count of rows in task_recipes owned by user
    recipes_stmt = select(func.count(TaskRecipe.id)).where(TaskRecipe.user_id == user_id)
    recipes_promoted = (await session.execute(recipes_stmt)).scalar() or 0

    # 8. recipe_retrieval_count & successful_reuses:
    # Query memory_retrieved events with hits >= 1
    events_stmt = select(AgentEvent.run_id, AgentEvent.metadata_).where(
        AgentEvent.user_id == user_id,
        AgentEvent.event_type == "memory_retrieved",
    )
    events_result = await session.execute(events_stmt)
    reused_run_ids: Set[Any] = set()

    for row in events_result.all():
        run_uuid, metadata = row[0], row[1]
        if metadata and isinstance(metadata, dict):
            hits = metadata.get("hits", 0)
            if isinstance(hits, (int, float)) and hits >= 1:
                reused_run_ids.add(run_uuid)

    recipe_retrieval_count = len(reused_run_ids)

    successful_reuses = 0
    if reused_run_ids:
        succ_reuse_stmt = select(func.count(TaskRun.id)).where(
            TaskRun.id.in_(list(reused_run_ids)),
            TaskRun.status == TaskStatus.SUCCEEDED.value,
        )
        successful_reuses = (await session.execute(succ_reuse_stmt)).scalar() or 0

    # 9. average_judge_score: Average judge_score across evaluation rows
    avg_score_stmt = select(func.avg(Evaluation.judge_score)).where(
        Evaluation.user_id == user_id
    )
    raw_avg_score = (await session.execute(avg_score_stmt)).scalar()
    average_judge_score = round(float(raw_avg_score), 2) if raw_avg_score is not None else 0.0

    # 10. improvement_rate per BLUEPRINT.md §15:
    # Baseline for tasks = average iterations_to_solve among successful runs that did NOT retrieve a recipe.
    # Reused runs are improved if iterations_to_solve < baseline.
    improvement_rate = 0.0
    runs_query = select(TaskRun.id, TaskRun.iteration_count).where(
        TaskRun.user_id == user_id,
        TaskRun.status == TaskStatus.SUCCEEDED.value,
    )
    all_succ_runs = (await session.execute(runs_query)).all()

    baseline_runs = [r[1] for r in all_succ_runs if r[0] not in reused_run_ids and r[1] > 0]
    reused_succ_runs = [r[1] for r in all_succ_runs if r[0] in reused_run_ids and r[1] > 0]

    if baseline_runs and reused_succ_runs:
        historical_baseline = sum(baseline_runs) / len(baseline_runs)
        improved_count = sum(1 for iters in reused_succ_runs if iters < historical_baseline)
        improvement_rate = round(float(improved_count / len(reused_succ_runs)), 2)

    return MetricsResponse(
        total_tasks=total_tasks,
        successful_tasks=successful_tasks,
        failed_tasks=failed_tasks,
        success_rate=success_rate,
        average_iterations=average_iterations,
        average_tool_calls=average_tool_calls,
        recipes_promoted=recipes_promoted,
        recipe_retrieval_count=recipe_retrieval_count,
        successful_reuses=successful_reuses,
        average_judge_score=average_judge_score,
        improvement_rate=improvement_rate,
    )
