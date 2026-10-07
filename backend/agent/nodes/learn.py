"""
Learning node (maybe_learn) for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §10, §11, §14.
Evaluates promotion; triggers quality gate; stores recipe in pgvector.
Emits learning_candidate_created and learning_saved events.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

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
    """
    runtime = get_current_runtime()
    candidate = extract_candidate_recipe(state)

    decision = "skip"
    reason = "No candidate extracted."

    session = None
    if runtime.session_factory is not None:
        try:
            async with runtime.session_factory() as active_session:
                decision, reason = await evaluate_quality_gate(state, candidate, active_session)

                if candidate is not None:
                    # Record candidate for audit/provenance
                    await record_recipe_candidate(active_session, state, candidate)

                    # Emit learning_candidate_created event
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

                if decision == "promoted" and candidate is not None:
                    promoted = await promote_recipe_to_trusted(active_session, state, candidate)
                    if promoted:
                        # Emit learning_saved event
                        try:
                            await runtime.emit_event(
                                task_id=uuid.UUID(state["task_id"]),
                                run_id=uuid.UUID(state["run_id"]),
                                user_id=uuid.UUID(state["user_id"]),
                                event_type=EventType.LEARNING_SAVED,
                                status="running",
                                metadata={
                                    "recipe_id": str(promoted.id),
                                    "task_type": promoted.task_type,
                                    "problem_pattern": promoted.problem_pattern,
                                },
                            )
                        except Exception as exc:
                            logger.warning("Failed to emit learning_saved event: %s", exc)

                # Check if a previously retrieved recipe was reused successfully
                retrieved_recipes = state.get("retrieved_recipes", [])
                if retrieved_recipes and state.get("evaluation", {}).get("task_success", False):
                    for rec in retrieved_recipes:
                        rec_id = rec.get("recipe_id")
                        if rec_id:
                            await record_reuse_success(active_session, rec_id)

                await active_session.commit()
        except Exception as exc:
            logger.error("DB error in maybe_learn node: %s", exc)
            decision = "skip"
    else:
        # Offline or test evaluation
        if candidate is not None:
            decision, reason = await evaluate_quality_gate(state, candidate, None)

    return {
        "candidate_recipe": candidate,
        "learning_decision": decision,
        "current_step": "respond",
    }
