"""
Response node for LangGraph agent.

Source of truth: BLUEPRINT.md §8.

This node formats the final_response, sets final status, emits terminal event.

Design rules:
- Sets final_response from evaluation results or last observation
- Sets status to succeeded or failed based on task_success
- Emits task_completed or task_failed event
- Returns final state update
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime, get_runtime, get_db_session
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)


async def respond_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: format final response and set terminal status.

    Source: BLUEPRINT.md §8.

    Args:
        state: Current AgentState with evaluation, observations, final_response.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission (also in metadata.runtime)

    Returns:
        dict: State update with final_response, status, termination_reason.

    Notes:
        - Sets status to "succeeded" if task_success, else "failed"
        - Sets termination_reason appropriately
        - Emits task_completed or task_failed event
        - Formats final response for user
    """
    task_id = state.get("task_id", "")
    run_id = state.get("run_id", "")
    logger.info(f"[respond_node] Starting response for task {task_id}, run {run_id}")

    runtime: AgentRuntime | None = get_runtime(config)
    db_session = get_db_session(config)

    evaluation = state.get("evaluation", {})
    task_success = evaluation.get("task_success", False)
    termination_reason = state.get("termination_reason")
    observations = state.get("observations", [])
    final_response = state.get("final_response", "")

    # Determine final status
    if task_success:
        status = "succeeded"
        if not termination_reason:
            termination_reason = "completed_successfully"
    else:
        status = "failed"
        if not termination_reason:
            termination_reason = "max_iterations" if state.get("iteration_count", 0) >= state.get("max_iterations", 3) else "evaluation_failed"

    # Build final response if not already set
    if not final_response or not final_response.strip():
        final_response = _build_final_response(state, task_success)

    logger.info(f"[respond_node] Final status: {status}, termination_reason: {termination_reason}")

    # Emit terminal event
    if runtime:
        try:
            event_type = "task_completed" if status == "succeeded" else "task_failed"
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type=event_type,
                status=status,
                metadata={
                    "task_success": task_success,
                    "termination_reason": termination_reason,
                    "iteration_count": state.get("iteration_count", 0),
                    "final_response": final_response,
                    "final_response_length": len(final_response),
                },
                session=db_session,
            )
            logger.debug(f"[respond_node] Emitted {event_type} event")
        except Exception as e:
            logger.warning(f"[respond_node] Failed to emit terminal event: {e}")

    return {
        "final_response": final_response,
        "status": status,
        "termination_reason": termination_reason,
    }


def _build_final_response(state: AgentState, task_success: bool) -> str:
    """Build final response from state."""
    # Try to use existing final_response first
    existing = state.get("final_response", "")
    if existing and existing.strip():
        return existing

    # Try to extract from last observation
    observations = state.get("observations", [])
    if observations:
        last_obs = observations[-1]
        content = last_obs.get("content", "")
        if content and content.strip():
            if task_success:
                return f"Task completed successfully. Result: {content}"
            else:
                return f"Task could not be completed. Last result: {content}"

    # Fallback based on task success
    goal = state.get("goal", "")
    if task_success:
        return f"Successfully completed the task: {goal}"
    else:
        evaluation = state.get("evaluation", {})
        judge_score = evaluation.get("judge_score", 0)
        return f"Unable to complete the task: {goal}. Evaluation score: {judge_score}/10"


__all__ = ["respond_node"]
