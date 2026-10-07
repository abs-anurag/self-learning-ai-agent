"""
Learning node (maybe_learn) for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §10, §11, §14.
Evaluates promotion; triggers quality gate; stores recipe in pgvector.
Emits learning_candidate_created and learning_saved events.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType
from backend.learning.candidate import extract_candidate_recipe, record_recipe_candidate
from backend.learning.quality_gate import evaluate_quality_gate
from backend.learning.recipes import promote_recipe_to_trusted, record_reuse_success

logger = get_logger(__name__)


async def learn_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: maybe_learn.
    Extracts strategy candidate and evaluates promotion via quality gate.
    Emits learning telemetry events.
    Guaranteed not to block task finalization.
    """
    logger.info("BEFORE maybe_learn: entering maybe_learn node for run %s", state.get("run_id"))
    runtime = get_current_runtime()
    candidate = extract_candidate_recipe(state)

    decision = "skip"
    reason = "No candidate extracted."
    candidate_recorded = False
    promoted_meta: Optional[dict[str, Any]] = None

    if runtime.session_factory is not None:
        try:
            async def _persist_learning() -> tuple[str, bool, Optional[dict[str, Any]]]:
                nonlocal decision, reason
                p_meta = None
                c_recorded = False

                async with runtime.session_factory() as active_session:
                    try:
                        gate_decision, gate_reason = await evaluate_quality_gate(state, candidate, active_session)
                        decision = gate_decision
                        reason = gate_reason

                        if candidate is not None:
                            recorded = await record_recipe_candidate(active_session, state, candidate)
                            if recorded is not None:
                                c_recorded = True

                        if decision == "promoted" and candidate is not None:
                            promoted = await promote_recipe_to_trusted(active_session, state, candidate)
                            if promoted is not None:
                                p_meta = {
                                    "recipe_id": str(promoted.id),
                                    "task_type": promoted.task_type,
                                    "problem_pattern": promoted.problem_pattern,
                                }

                        # Check if a previously retrieved recipe was reused successfully
                        retrieved_recipes = state.get("retrieved_recipes", [])
                        if retrieved_recipes and state.get("evaluation", {}).get("task_success", False):
                            for rec in retrieved_recipes:
                                rec_id = rec.get("recipe_id")
                                if rec_id:
                                    await record_reuse_success(active_session, rec_id)

                        await active_session.commit()
                        return decision, c_recorded, p_meta
                    except Exception as inner_exc:
                        await active_session.rollback()
                        raise inner_exc

            # Timeout protection: learning must never hang task execution (max 10s)
            decision, candidate_recorded, promoted_meta = await asyncio.wait_for(
                _persist_learning(), timeout=10.0
            )

        except asyncio.TimeoutError:
            logger.error(
                "Learning persistence timed out in maybe_learn for run %s; continuing to respond.",
                state.get("run_id"),
            )
            decision = "skip"
        except Exception as exc:
            logger.error(
                "DB error in maybe_learn node for run %s: %s; continuing to respond.",
                state.get("run_id"),
                exc,
            )
            decision = "skip"
    else:
        # Offline or test evaluation
        if candidate is not None:
            try:
                decision, reason = await evaluate_quality_gate(state, candidate, None)
            except Exception as exc:
                logger.error("Quality gate evaluation failed in maybe_learn: %s", exc)
                decision = "skip"

    # Emit learning events strictly AFTER DB transaction is committed and closed,
    # preventing distributed deadlock between row locks in PostgreSQL.
    if candidate_recorded and candidate is not None:
        try:
            await runtime.emit_event(
                task_id=uuid.UUID(state["task_id"]),
                run_id=uuid.UUID(state["run_id"]),
                user_id=uuid.UUID(state["user_id"]),
                event_type=EventType.LEARNING_CANDIDATE_CREATED,
                status="running",
                metadata={
                    "task_type": candidate["task_type"],
                    "problem_pattern": candidate["problem_pattern"],
                },
            )
        except Exception as exc:
            logger.warning("Failed to emit learning_candidate_created event: %s", exc)

    if promoted_meta is not None:
        try:
            await runtime.emit_event(
                task_id=uuid.UUID(state["task_id"]),
                run_id=uuid.UUID(state["run_id"]),
                user_id=uuid.UUID(state["user_id"]),
                event_type=EventType.LEARNING_SAVED,
                status="running",
                metadata=promoted_meta,
            )
        except Exception as exc:
            logger.warning("Failed to emit learning_saved event: %s", exc)

    logger.info("AFTER maybe_learn: exiting maybe_learn node for run %s with decision=%s", state.get("run_id"), decision)

    return {
        "candidate_recipe": candidate,
        "learning_decision": decision,
        "current_step": "respond",
    }
