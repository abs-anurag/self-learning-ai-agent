"""
Recipe candidate extraction and persistence layer.

Source of truth: BLUEPRINT.md §3, §7, §10, §11, §18.

Design rules:
- Candidate recipes are unproven candidate strategies stored in `recipe_candidates`.
- Never vector indexed; ineligible for strategy retrieval (§10, §11).
- Trivial successes (§11):
  If the run is trivial (e.g. no tools used or trivial greeting), learning_decision = skip.
  No candidate is stored, and no learning event is emitted.
- Non-trivial successes (§11):
  Candidate is extracted and inserted with status = 'candidate'.
"""

from __future__ import annotations

from decimal import Decimal
import uuid
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logging import get_logger
from backend.db.models import CandidateStatus, RecipeCandidate

logger = get_logger(__name__)


def is_trivial_run(
    *,
    goal: str,
    tool_calls: list[Any],
    evaluation: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Determine if a successful run is trivial.
    Source: BLUEPRINT.md §7, §11.

    A run is trivial if no tools were invoked to solve it,
    or if explicit evaluation flags declare it trivial.
    Trivial runs persist experiences only; no candidate recipe is created.
    """
    eval_dict = evaluation or {}
    if eval_dict.get("is_trivial") is True:
        return True

    tool_count = eval_dict.get("tool_call_count", len(tool_calls))
    if tool_count == 0:
        return True

    # Check for empty or single-word non-problem statements
    tokens = goal.strip().split()
    if len(tokens) <= 2 and tool_count == 0:
        return True

    return False


async def create_recipe_candidate(
    session: AsyncSession,
    *,
    source_task_id: Union[uuid.UUID, str],
    run_id: Union[uuid.UUID, str],
    user_id: Union[uuid.UUID, str],
    task_type: str,
    problem_pattern: str,
    context: str,
    recommended_strategy: str,
    successful_steps: list[Any],
    failed_steps: Optional[list[Any]] = None,
    tools_used: Optional[list[Any]] = None,
    lesson: str,
    evidence: str,
    evaluation_score: Union[float, Decimal],
    deterministic_pass: bool,
    generalizable: bool,
    status: str = CandidateStatus.CANDIDATE.value,
    candidate_id: Optional[Union[uuid.UUID, str]] = None,
) -> RecipeCandidate:
    """
    Persist an unproven candidate strategy to recipe_candidates.
    Source: BLUEPRINT.md §11, §18.
    """
    task_uuid = uuid.UUID(str(source_task_id))
    run_uuid = uuid.UUID(str(run_id))
    user_uuid = uuid.UUID(str(user_id))
    cand_uuid = uuid.UUID(str(candidate_id)) if candidate_id else uuid.uuid4()

    dec_score = (
        Decimal(str(evaluation_score))
        if isinstance(evaluation_score, (float, int))
        else evaluation_score
    )

    candidate = RecipeCandidate(
        id=cand_uuid,
        source_task_id=task_uuid,
        run_id=run_uuid,
        user_id=user_uuid,
        task_type=task_type,
        problem_pattern=problem_pattern,
        context=context,
        recommended_strategy=recommended_strategy,
        successful_steps=successful_steps,
        failed_steps=failed_steps or [],
        tools_used=tools_used or [],
        lesson=lesson,
        evidence=evidence,
        evaluation_score=dec_score,
        deterministic_pass=deterministic_pass,
        generalizable=generalizable,
        status=status,
    )

    session.add(candidate)
    await session.flush()
    logger.info(
        "Persisted recipe candidate %s for run %s (status=%s, score=%s)",
        candidate.id,
        run_uuid,
        status,
        dec_score,
    )
    return candidate


async def reject_candidate(
    session: AsyncSession,
    candidate_id: Union[uuid.UUID, str],
) -> None:
    """
    Update status of recipe candidate to 'rejected'.
    Source: BLUEPRINT.md §11.
    """
    cand_uuid = uuid.UUID(str(candidate_id))
    await session.execute(
        update(RecipeCandidate)
        .where(RecipeCandidate.id == cand_uuid)
        .values(status=CandidateStatus.REJECTED.value)
    )
    await session.flush()
    logger.info("Marked recipe candidate %s as rejected", cand_uuid)


async def get_candidate_by_id(
    session: AsyncSession,
    candidate_id: Union[uuid.UUID, str],
) -> Optional[RecipeCandidate]:
    """Retrieve recipe candidate by primary key."""
    cand_uuid = uuid.UUID(str(candidate_id))
    result = await session.execute(
        select(RecipeCandidate).where(RecipeCandidate.id == cand_uuid)
    )
    return result.scalar_one_or_none()


async def get_candidates_for_run(
    session: AsyncSession,
    run_id: Union[uuid.UUID, str],
) -> list[RecipeCandidate]:
    """Retrieve all recipe candidates created during a run."""
    run_uuid = uuid.UUID(str(run_id))
    result = await session.execute(
        select(RecipeCandidate)
        .where(RecipeCandidate.run_id == run_uuid)
        .order_by(RecipeCandidate.created_at.asc())
    )
    return list(result.scalars().all())
