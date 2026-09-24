from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    AgentEvent,
    Evaluation,
    Task,
    TaskRecipe,
    TaskRun,
)


async def get_metrics(db_session: AsyncSession, user_id: UUID) -> dict[str, Any]:
    """
    Compute metrics for a given user.

    Args:
        db_session: Async SQLAlchemy session.
        user_id: UUID of the user.

    Returns:
        Dictionary with metric keys and values.
    """
    # Total tasks created by the user
    total_tasks_stmt = select(func.count(Task.id)).where(Task.user_id == user_id)
    total_tasks_result = await db_session.execute(total_tasks_stmt)
    total_tasks = total_tasks_result.scalar() or 0

    # Successful tasks (status = 'succeeded')
    successful_tasks_stmt = select(func.count(Task.id)).where(
        and_(Task.user_id == user_id, Task.status == "succeeded")
    )
    successful_tasks_result = await db_session.execute(successful_tasks_stmt)
    successful_tasks = successful_tasks_result.scalar() or 0

    # Failed tasks (status = 'failed')
    failed_tasks_stmt = select(func.count(Task.id)).where(
        and_(Task.user_id == user_id, Task.status == "failed")
    )
    failed_tasks_result = await db_session.execute(failed_tasks_stmt)
    failed_tasks = failed_tasks_result.scalar() or 0

    # Success rate
    success_rate = (
        round(successful_tasks / total_tasks, 2) if total_tasks > 0 else 0.0
    )

    # Average iterations across all completed runs (succeeded or failed)
    avg_iterations_stmt = select(func.avg(TaskRun.iteration_count)).where(
        and_(
            TaskRun.user_id == user_id,
            TaskRun.status.in_(["succeeded", "failed"]),
        )
    )
    avg_iterations_result = await db_session.execute(avg_iterations_stmt)
    avg_iterations = avg_iterations_result.scalar()
    average_iterations = round(avg_iterations, 2) if avg_iterations is not None else 0.0

    # Average total tool calls per run
    # First, sum tool_call_count per run, then average across runs
    tool_calls_per_run_grouped_stmt = select(
        func.avg(func.sum(Evaluation.tool_call_count))
    ).where(
        Evaluation.run_id.in_(
            select(TaskRun.id).where(TaskRun.user_id == user_id)
        )
    ).group_by(Evaluation.run_id)
    avg_tool_calls_result = await db_session.execute(tool_calls_per_run_grouped_stmt)
    avg_tool_calls = avg_tool_calls_result.scalar()
    average_tool_calls = round(avg_tool_calls, 2) if avg_tool_calls is not None else 0.0

    # Recipes promoted (count of task_recipes owned by the user)
    recipes_promoted_stmt = select(func.count(TaskRecipe.id)).where(
        TaskRecipe.user_id == user_id
    )
    recipes_promoted_result = await db_session.execute(recipes_promoted_stmt)
    recipes_promoted = recipes_promoted_result.scalar() or 0

    # Recipe retrieval count: runs where at least one trusted recipe was retrieved (hits >= 1)
    # We look for AgentEvent of type 'memory_retrieved' with metadata_->>'hits' >= 1
    recipe_retrieved_exists = exists().where(
        and_(
            AgentEvent.run_id == TaskRun.id,
            AgentEvent.event_type == "memory_retrieved",
            AgentEvent.metadata_.get("hits").as_integer() >= 1,
        )
    )
    recipe_retrieval_count_stmt = select(func.count(TaskRun.id)).where(
        and_(
            TaskRun.user_id == user_id,
            recipe_retrieved_exists,
        )
    )
    recipe_retrieval_count_result = await db_session.execute(
        recipe_retrieval_count_stmt
    )
    recipe_retrieval_count = recipe_retrieval_count_result.scalar() or 0

    # Successful reuses: runs where at least one trusted recipe was retrieved and run succeeded
    successful_reuses_stmt = select(func.count(TaskRun.id)).where(
        and_(
            TaskRun.user_id == user_id,
            TaskRun.status == "succeeded",
            recipe_retrieved_exists,
        )
    )
    successful_reuses_result = await db_session.execute(successful_reuses_stmt)
    successful_reuses = successful_reuses_result.scalar() or 0

    # Average judge score across all evaluations for the user
    avg_judge_score_stmt = select(func.avg(Evaluation.judge_score)).where(
        Evaluation.user_id == user_id
    )
    avg_judge_score_result = await db_session.execute(avg_judge_score_stmt)
    avg_judge_score = avg_judge_score_result.scalar()
    average_judge_score = round(avg_judge_score, 2) if avg_judge_score is not None else 0.0

    # Improvement rate
    # Historical baseline per task_type: avg iterations_to_solve for successful runs
    # without recipe retrieval (same user and task_type)
    baseline_without_recipe_stmt = (
        select(
            TaskRun.task_type,
            func.avg(TaskRun.iteration_count).label("baseline"),
        )
        .where(
            and_(
                TaskRun.user_id == user_id,
                TaskRun.status == "succeeded",
                ~exists().where(
                    and_(
                        AgentEvent.run_id == TaskRun.id,
                        AgentEvent.event_type == "memory_retrieved",
                        AgentEvent.metadata_.get("hits").as_integer() >= 1,
                    )
                ),
            )
        )
        .group_by(TaskRun.task_type)
    )
    baseline_result = await db_session.execute(baseline_without_recipe_stmt)
    baselines = {
        row.task_type: float(row.baseline) for row in baseline_result.fetchall()
    }

    # Eligible reused runs: successful runs with recipe retrieval
    eligible_reused_stmt = select(
        TaskRun.task_type,
        TaskRun.iteration_count,
    ).where(
        and_(
            TaskRun.user_id == user_id,
            TaskRun.status == "succeeded",
            exists().where(
                and_(
                    AgentEvent.run_id == TaskRun.id,
                    AgentEvent.event_type == "memory_retrieved",
                    AgentEvent.metadata_.get("hits").as_integer() >= 1,
                )
            ),
        )
    )
    eligible_reused_result = await db_session.execute(eligible_reused_stmt)
    eligible_reused_runs = eligible_reused_result.fetchall()

    improved_count = 0
    total_eligible = len(eligible_reused_runs)
    for run in eligible_reused_runs:
        task_type = run.task_type
        iteration_count = run.iteration_count
        if task_type in baselines:
            if iteration_count < baselines[task_type]:
                improved_count += 1

    improvement_rate = (
        round(improved_count / total_eligible, 2) if total_eligible > 0 else 0.0
    )

    return {
        "total_tasks": total_tasks,
        "successful_tasks": successful_tasks,
        "failed_tasks": failed_tasks,
        "success_rate": success_rate,
        "average_iterations": average_iterations,
        "average_tool_calls": average_tool_calls,
        "recipes_promoted": recipes_promoted,
        "recipe_retrieval_count": recipe_retrieval_count,
        "successful_reuses": successful_reuses,
        "average_judge_score": average_judge_score,
        "improvement_rate": improvement_rate,
    }
