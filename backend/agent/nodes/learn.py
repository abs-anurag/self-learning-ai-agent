"""
Learning node for LangGraph agent.

Source of truth: BLUEPRINT.md sections 8, 12, 13.

This node handles the learning logic after a successful task execution.

FLOW:
1. Check if the task succeeded (we are in the success branch, so evaluation.task_success is True).
2. If there are retrieved_recipes in the state, increment the success_after_reuse counter for each retrieved recipe.
3. Determine if the success is trivial or non-trivial by attempting to extract a candidate recipe using extract_candidate_recipe.
4. If trivial (no candidate extracted):
   - Set learning_decision = "skip"
   - Emit no learning events
5. If non-trivial (candidate extracted):
   - Emit learning_candidate_created event
   - Run the quality gate (evaluate_for_promotion) on the candidate
   - Based on the quality gate decision:
        * "promoted":
            - Create a trusted recipe using create_trusted_recipe with the embedding from the quality gate
            - Emit learning_saved event
            - Set learning_decision = "promoted"
        * "candidate_only":
            - Update the candidate's status to "rejected"
            - Set learning_decision = "candidate_only"
        * "skip" (duplicate):
            - Set learning_decision = "skip"
            - Leave the candidate as is (status remains "candidate")
6. Update the state with the learning_decision.
7. Return the state update.

Design rules:
- Errors logged but don't halt execution unless necessary
- Uses db_session from config for database operations
- Uses settings from config
- Emits learning events via the runtime
- Follows same patterns as understand.py and retrieve.py
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from backend.agent.runtime import AgentRuntime, get_db_session, get_runtime
from backend.agent.state import AgentState
from backend.core.config import settings
from backend.learning.candidate import extract_candidate_recipe
from backend.learning.quality_gate import evaluate_for_promotion
from backend.learning.recipes import create_trusted_recipe, increment_recipe_success
from backend.db.models import RecipeStatus, RecipeCandidate

logger = logging.getLogger(__name__)


async def learn_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: handle learning logic after successful task execution.

    Source: BLUEPRINT.md sections 8, 12, 13.

    Args:
        state: Current AgentState with evaluation task_success=True.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission
            - db_session: AsyncSession for database operations
            - settings: Application settings (optional, uses global if not provided)

    Returns:
        dict: State update with learning_decision.

    Notes:
        - Only called after successful evaluation (task_success = True)
        - Increments success_after_reuse for retrieved recipes
        - Extracts candidate recipe and runs quality gate
        - Emits learning events as appropriate
        - Errors logged but don't halt execution
    """
    logger.info(f"[learn_node] Starting learning for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = get_runtime(config) or config.get("runtime")
    db_session = get_db_session(config) or config.get("db_session")
    config_settings = config.get("settings", settings)

    # Verify we are in success branch (should be true by routing)
    evaluation = state.get("evaluation", {})
    if not evaluation.get("task_success", False):
        logger.warning("[learn_node] Task did not succeed, skipping learning")
        return {"learning_decision": "skip"}

    # Initialize return values
    learning_decision = "skip"

    try:
        # Step 1: Increment success_after_reuse for each retrieved recipe
        retrieved_recipes = state.get("retrieved_recipes", [])
        if retrieved_recipes and db_session:
            for recipe_dict in retrieved_recipes:
                recipe_id_raw = recipe_dict.get("id")
                if not recipe_id_raw:
                    continue
                try:
                    recipe_id = uuid.UUID(str(recipe_id_raw))
                except (ValueError, AttributeError, TypeError):
                    logger.warning(f"[learn_node] Skipping invalid recipe_id: {recipe_id_raw}")
                    continue
                try:
                    await increment_recipe_success(
                        db_session=db_session,
                        recipe_id=recipe_id,
                    )
                    logger.debug(f"[learn_node] Incremented success_after_reuse for recipe {recipe_id}")
                except Exception as e:
                    logger.warning(f"[learn_node] Failed to increment success_after_reuse for recipe {recipe_id}: {e}")

            # Commit usage count updates
            try:
                await db_session.commit()
            except Exception as e:
                logger.warning(f"[learn_node] Failed to commit success_after_reuse updates: {e}")
                # Non-fatal - learning can continue

        # Step 2: Extract candidate recipe
        candidate = None
        try:
            # Prepare task_data for extract_candidate_recipe
            task_data = {
                "source_task_id": state.get("task_id"),
                "run_id": state.get("run_id"),
                "user_id": state.get("user_id"),
                "task_type": state.get("task_type"),
                "problem_pattern": state.get("understood_task", ""),  # Using understood_task as problem_pattern
                "context": state.get("goal", ""),  # Using goal as context
                "recommended_strategy": state.get("plan", []),  # Using plan as recommended_strategy
                "successful_steps": state.get("observations", []),  # Using observations as successful_steps
                "failed_steps": [],  # Would need to track failed steps separately
                "tools_used": [call.get("tool_name", "") for call in state.get("tool_calls", []) if call.get("tool_name")],
                "lesson": state.get("reflection", ""),  # Using reflection as lesson
                "evidence": str(state.get("evaluation", {})),  # Using evaluation as evidence
                "evaluation_score": state.get("evaluation", {}).get("score", 0.0),
                "deterministic_pass": state.get("evaluation", {}).get("deterministic_pass", False),
                "generalizable": state.get("evaluation", {}).get("generalizable", False),
                "tool_success": state.get("evaluation", {}).get("tool_success", False),
                "judge_score": state.get("evaluation", {}).get("score", 0.0),
                "final_answer_present": bool(state.get("final_response")),
            }

            # Convert string IDs to UUID objects if needed
            if isinstance(task_data["source_task_id"], str):
                task_data["source_task_id"] = uuid.UUID(task_data["source_task_id"])
            if isinstance(task_data["run_id"], str):
                task_data["run_id"] = uuid.UUID(task_data["run_id"])
            if isinstance(task_data["user_id"], str):
                task_data["user_id"] = uuid.UUID(task_data["user_id"])

            task_run_id = state["run_id"]
            if isinstance(task_run_id, str):
                task_run_id = uuid.UUID(task_run_id)

            candidate = await extract_candidate_recipe(
                db_session=db_session,
                task_run_id=task_run_id,
                task_data=task_data,
                settings=config_settings,
            )
        except Exception as e:
            logger.error(f"[learn_node] Error extracting candidate recipe: {e}", exc_info=True)

        if candidate is None:
            logger.info("[learn_node] No candidate extracted - trivial success")
            learning_decision = "skip"
            return {"learning_decision": learning_decision}

        # Step 3: Non-trivial success - emit learning_candidate_created event
        logger.info("[learn_node] Non-trivial success - extracting candidate")
        if runtime:
            try:
                await runtime.emit_event(
                    task_id=state["task_id"],
                    run_id=state["run_id"],
                    user_id=state["user_id"],
                    event_type="learning_candidate_created",
                    status="running",
                    metadata={
                        "candidate_id": str(getattr(candidate, 'id', "")),
                    },
                )
                logger.debug("[learn_node] Emitted learning_candidate_created event")
            except Exception as e:
                logger.warning(f"[learn_node] Failed to emit learning_candidate_created event: {e}")

        # Step 4: Run quality gate
        quality_gate_decision = "skip"
        embedding = None
        try:
            if not db_session:
                logger.error("[learn_node] No db_session in config for quality gate")
                quality_gate_decision = "skip"
            else:
                # Prepare task_data for quality gate
                quality_gate_task_data = {
                    "canonical_task_success": evaluation.get("task_success", False),
                    "tool_success": evaluation.get("tool_success", False),
                }

                quality_gate_result = await evaluate_for_promotion(
                    db_session=db_session,
                    candidate=candidate,
                    task_data=quality_gate_task_data,
                    settings=config_settings,
                )
                # Assuming evaluate_for_promotion returns dict with decision and embedding
                quality_gate_decision = quality_gate_result.get("decision", "skip")
                embedding = quality_gate_result.get("embedding")
                logger.info(f"[learn_node] Quality gate decision: {quality_gate_decision}")
        except Exception as e:
            logger.error(f"[learn_node] Error during quality gate evaluation: {e}", exc_info=True)
            quality_gate_decision = "skip"

        # Step 5: Handle quality gate decision
        if quality_gate_decision == "promoted":
            logger.info("[learn_node] Quality gate promoted candidate")
            try:
                if db_session and embedding is not None:
                    # Extract user_id and recipe_data from candidate
                    user_id = getattr(candidate, 'user_id', None)
                    if isinstance(user_id, str):
                        user_id = uuid.UUID(user_id)

                    recipe_data = {
                        "source_task_id": getattr(candidate, 'source_task_id', None),
                        "task_type": getattr(candidate, 'task_type', None),
                        "problem_pattern": getattr(candidate, 'problem_pattern', None),
                        "context": getattr(candidate, 'context', None),
                        "recommended_strategy": getattr(candidate, 'recommended_strategy', None),
                        "successful_steps": getattr(candidate, 'successful_steps', None),
                        "failed_steps": getattr(candidate, 'failed_steps', None),
                        "tools_used": getattr(candidate, 'tools_used', None),
                        "lesson": getattr(candidate, 'lesson', None),
                        "evidence": getattr(candidate, 'evidence', None),
                        "evaluation_score": getattr(candidate, 'evaluation_score', 0.0),
                        "deterministic_pass": getattr(candidate, 'deterministic_pass', False),
                        "generalizable": getattr(candidate, 'generalizable', False),
                        "confidence": getattr(candidate, 'confidence', 1.0),
                        "version": getattr(candidate, 'version', 1),
                    }

                    # Convert UUID strings to UUID objects if needed
                    if isinstance(recipe_data["source_task_id"], str):
                        recipe_data["source_task_id"] = uuid.UUID(recipe_data["source_task_id"])

                    trusted_recipe = await create_trusted_recipe(
                        db_session=db_session,
                        user_id=user_id,
                        recipe_data=recipe_data,
                        embedding=embedding,
                    )
                    logger.info(f"[learn_node] Created trusted recipe {trusted_recipe.id}")

                    # Emit learning_saved event
                    if runtime:
                        try:
                            await runtime.emit_event(
                                task_id=state["task_id"],
                                run_id=state["run_id"],
                                user_id=state["user_id"],
                                event_type="learning_saved",
                                status="success",
                                metadata={
                                    "recipe_id": str(trusted_recipe.id),
                                },
                            )
                            logger.debug("[learn_node] Emitted learning_saved event")
                        except Exception as e:
                            logger.warning(f"[learn_node] Failed to emit learning_saved event: {e}")

                    learning_decision = "promoted"
                else:
                    logger.error("[learn_node] Missing db_session or embedding for promotion")
                    learning_decision = "candidate_only"  # Fallback
            except Exception as e:
                logger.error(f"[learn_node] Error creating trusted recipe: {e}", exc_info=True)
                learning_decision = "candidate_only"  # Fallback to candidate_only on error

        elif quality_gate_decision == "candidate_only":
            logger.info("[learn_node] Quality gate decided candidate_only")
            try:
                # Update candidate status to rejected
                if db_session:
                    from sqlalchemy import update

                    candidate_id = getattr(candidate, 'id', None)
                    if candidate_id:
                        stmt = (
                            update(RecipeCandidate)
                            .where(RecipeCandidate.id == candidate_id)
                            .values(status=RecipeStatus.REJECTED)
                        )
                        await db_session.execute(stmt)
                        await db_session.commit()
                        logger.info(f"[learn_node] Updated candidate {candidate_id} status to rejected")
                    else:
                        logger.warning("[learn_node] Could not update candidate status - missing identifier")
                else:
                    logger.warning("[learn_node] No db_session available to update candidate status")
            except Exception as e:
                logger.error(f"[learn_node] Error updating candidate status: {e}", exc_info=True)
                # Don't halt learning - continue with candidate_only decision
            learning_decision = "candidate_only"

        else:  # skip or any other decision
            logger.info("[learn_node] Quality gate decided skip (duplicate or low quality)")
            learning_decision = "skip"
            # Leave candidate as is (no status update)

    except Exception as e:
        logger.error(f"[learn_node] Unexpected error during learning: {e}", exc_info=True)
        learning_decision = "skip"

    logger.info(f"[learn_node] Learning complete with decision: {learning_decision}")
    return {"learning_decision": learning_decision}


__all__ = ["learn_node"]
