"""
Evaluation scorer and evaluation persistence.

Source of truth: BLUEPRINT.md §12, §18.
Stores exactly one evaluation row per completed iteration cycle:
CONSTRAINT uq_run_iteration UNIQUE (run_id, iteration_count).
judge_reasoning is saved in evaluations.payload solely for audits (never exposed in APIs/telemetry).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.state import AgentState
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import Evaluation
from backend.evaluation.metrics import (
    compute_deterministic_pass,
    compute_task_success,
    compute_tool_success,
)

logger = get_logger(__name__)


async def score_and_record_evaluation(
    state: AgentState,
    session: Optional[AsyncSession],
    llm_judge_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Score the current execution iteration and record in PostgreSQL.

    Args:
        state: Current AgentState.
        session: Active SQLAlchemy session (if available).
        llm_judge_result: Result dict from LLMProvider.judge(state).

    Returns:
        Structured evaluation dictionary.
    """
    iteration_count = state.get("iteration_count", 0) + 1  # 1-indexed completed iteration
    tool_calls = state.get("tool_calls", [])
    observations = state.get("observations", [])
    error = state.get("error")

    # 1. Deterministic Pass
    deterministic_pass = compute_deterministic_pass(tool_calls, observations, error)

    # 2. Tool Success
    tool_success = compute_tool_success(tool_calls, observations)

    # 3. Judge Score & Reasoning
    judge_score = float(llm_judge_result.get("judge_score", 8.0))
    judge_reasoning = llm_judge_result.get(
        "judge_reasoning",
        "Deterministic heuristic evaluation pass."
    )

    # 4. Final Answer Present
    final_response = state.get("final_response", "") or ""
    # If final_response is not yet set in state, check if plan was executed or observations are present
    has_substantive_output = bool(
        final_response.strip()
        or (observations and any(obs.get("success") for obs in observations))
        or (not tool_calls and state.get("understood_task"))
    )

    # 5. Task Success
    task_success = compute_task_success(
        deterministic_pass=deterministic_pass,
        tool_success=tool_success,
        judge_score=judge_score,
        final_answer_present=has_substantive_output,
    )

    eval_dict = {
        "iteration_count": iteration_count,
        "task_success": task_success,
        "deterministic_pass": deterministic_pass,
        "tool_success": tool_success,
        "judge_score": round(judge_score, 1),
        "judge_reasoning": judge_reasoning,
        "tool_call_count": len(tool_calls),
    }

    # 6. Persist to evaluations table if session is active
    if session is not None:
        try:
            run_id = uuid.UUID(state["run_id"])
            user_id = uuid.UUID(state["user_id"])

            # Check if evaluation for this (run_id, iteration_count) already exists to prevent uq_run_iteration
            stmt = select(Evaluation).where(
                Evaluation.run_id == run_id,
                Evaluation.iteration_count == iteration_count,
            )
            res = await session.execute(stmt)
            existing_eval = res.scalar_one_or_none()

            if existing_eval is not None:
                existing_eval.task_success = task_success
                existing_eval.deterministic_pass = deterministic_pass
                existing_eval.tool_success = tool_success
                existing_eval.judge_score = Decimal(str(round(judge_score, 1)))
                existing_eval.tool_call_count = len(tool_calls)
                existing_eval.payload = {"judge_reasoning": judge_reasoning}
                await session.flush()
                logger.info(
                    "Updated existing evaluation for run %s, iteration %d: task_success=%s, score=%.1f",
                    run_id,
                    iteration_count,
                    task_success,
                    judge_score,
                )
            else:
                eval_record = Evaluation(
                    id=uuid.uuid4(),
                    run_id=run_id,
                    user_id=user_id,
                    iteration_count=iteration_count,
                    task_success=task_success,
                    deterministic_pass=deterministic_pass,
                    tool_success=tool_success,
                    judge_score=Decimal(str(round(judge_score, 1))),
                    tool_call_count=len(tool_calls),
                    payload={"judge_reasoning": judge_reasoning},
                )
                session.add(eval_record)
                await session.flush()
                logger.info(
                    "Persisted evaluation for run %s, iteration %d: task_success=%s, score=%.1f",
                    run_id,
                    iteration_count,
                    task_success,
                    judge_score,
                )
        except Exception as exc:
            await session.rollback()
            logger.error("Failed to record evaluation in database: %s", exc)

    return eval_dict
