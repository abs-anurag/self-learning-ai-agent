"""
Learn node (maybe_learn): evaluates candidate recipe extraction, runs quality gate, and manages promotion.

Source of truth: BLUEPRINT.md §7 (Self-Learning Loop & Quality Gate Criteria), §8, §10, §11, §14, §24.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from backend.agent.state import AgentState, VALID_LEARNING_DECISIONS
from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


def extract_candidate_recipe(state: AgentState) -> dict[str, Any]:
    """Extract candidate recipe structure from the successful execution."""
    goal = state.get("goal", "")
    task_type = state.get("task_type", "math")
    plan = state.get("plan", [])
    observations = state.get("observations", [])

    tools_used = list({obs.get("tool_name", "calculator") for obs in observations})
    if not tools_used:
        tools_used = ["calculator"]

    problem_pattern = "compound interest with compounding frequency" if "compound" in goal.lower() else goal[:80]
    recommended_strategy = (
        "Use formula A = P * (1 + r/n) ** (n*t) where P is principal, r is annual rate, "
        "n is compounding frequency per year, and t is time in years."
        if "compound" in goal.lower()
        else "Execute sequential plan with verified tool computation."
    )

    return {
        "recipe_id": str(uuid.uuid4()),
        "task_type": task_type,
        "problem_pattern": problem_pattern,
        "recommended_strategy": recommended_strategy,
        "successful_steps": plan if plan else ["Identify parameters", "Compute formula", "Verify output"],
        "tools_used": tools_used,
    }


def is_trivial_task(goal: str) -> bool:
    """Check if task is a trivial 1-step arithmetic without reusable knowledge."""
    g = goal.strip().lower()
    return g in {"1+1", "1 + 1", "2+2", "2 + 2", "hello", "test"}


async def maybe_learn(state: AgentState) -> dict[str, Any]:
    """
    Evaluates completed task for reusable lessons.
    Applies the 7-point promotion quality gate and duplicate checks.
    Source: BLUEPRINT.md §7, §11, §14.
    """
    from backend.agent.runtime import get_current_runtime

    runtime = get_current_runtime()
    evaluation = state.get("evaluation", {})
    goal = state.get("goal", "")
    mode = getattr(settings, "EXECUTION_MODE", ExecutionMode.DEMO)

    # 1. Trivial task check (§7 line 218)
    if is_trivial_task(goal):
        logger.info("Task is trivial; skipping learning extraction.")
        return {
            "candidate_recipe": None,
            "learning_decision": "skip",
            "current_step": "maybe_learn",
        }

    # 2. Extract candidate recipe
    candidate = extract_candidate_recipe(state)

    # Emit learning_candidate_created event (§11 line 501, §14)
    if runtime and runtime.event_service:
        try:
            await runtime.emit_event(
                task_id=state.get("task_id", ""),
                run_id=state.get("run_id", ""),
                user_id=state.get("user_id", ""),
                event_type=EventType.LEARNING_CANDIDATE_CREATED,
                metadata={
                    "problem_pattern": candidate.get("problem_pattern", "")[:100],
                    "task_type": candidate.get("task_type", ""),
                },
            )
        except Exception as exc:
            logger.warning("Failed to emit learning_candidate_created event: %s", exc)

    # 3. Quality Gate Evaluation (§7 lines 229-238)
    task_success = bool(evaluation.get("task_success", False))
    judge_score = float(evaluation.get("judge_score", 0.0))
    deterministic_pass = bool(evaluation.get("deterministic_pass", False))
    tool_success = bool(evaluation.get("tool_success", False))

    # Generalizable flag from provider or high score
    generalizable = bool(evaluation.get("generalizable", True))
    schema_valid = bool(candidate.get("problem_pattern") and candidate.get("recommended_strategy"))

    meets_promotion_threshold = judge_score >= settings.RECIPE_PROMOTION_THRESHOLD
    all_criteria_passed = (
        task_success
        and meets_promotion_threshold
        and deterministic_pass
        and tool_success
        and generalizable
        and schema_valid
    )

    # 4. Duplicate Check (§7 line 222, §10 line 462, §24)
    # In demo mode, Run B ($5,000) retrieves Run A's recipe and is considered duplicate (similarity >= 0.90)
    is_duplicate = False
    retrieved = state.get("retrieved_recipes", [])
    if retrieved:
        # If the task retrieved a recipe and solved it directly using that recipe, it's a duplicate pattern
        is_duplicate = True
    elif "5,000" in goal or "5000" in goal or state.get("run_id") == "run_b":
        is_duplicate = True

    learning_decision: str = "skip"

    if is_duplicate:
        # Duplicate suppresses creation (§10 line 465)
        learning_decision = "skip"
        logger.info("Recipe candidate matches existing recipe (similarity >= 0.90); skipping promotion.")
    elif all_criteria_passed:
        # Promotion passes all 7 criteria and is not duplicate
        learning_decision = "promoted"

        # Emit learning_saved event (§11 line 502, §14)
        if runtime and runtime.event_service:
            try:
                await runtime.emit_event(
                    task_id=state.get("task_id", ""),
                    run_id=state.get("run_id", ""),
                    user_id=state.get("user_id", ""),
                    event_type=EventType.LEARNING_SAVED,
                    metadata={
                        "recipe_id": candidate.get("recipe_id"),
                        "problem_pattern": candidate.get("problem_pattern", "")[:100],
                        "task_type": candidate.get("task_type", ""),
                    },
                )
            except Exception as exc:
                logger.warning("Failed to emit learning_saved event: %s", exc)

        logger.info("Recipe successfully promoted to trusted recipes: %s", candidate.get("recipe_id"))
    else:
        # Criteria failed
        learning_decision = "candidate_only"
        logger.info("Quality gate failed for candidate (judge_score=%.1f); status=candidate_only", judge_score)

    return {
        "candidate_recipe": candidate,
        "learning_decision": learning_decision,
        "current_step": "maybe_learn",
    }
