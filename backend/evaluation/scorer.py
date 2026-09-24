"""
Composite evaluation scorer for the Self-Learning AI Agent.

Source of truth: BLUEPRINT.md §12.

This module implements the evaluation logic that:
1. Computes canonical task_success from component scores
2. Calls LLM judge for quality scoring
3. Persists Evaluation row to database
4. Emits evaluation_completed event
5. Increments iteration_count

Design rules:
- Canonical task_success: deterministic_pass AND tool_success AND judge_score >= 6.0 AND final_answer_present
- Two-tier thresholds: task success at 6.0, recipe promotion at 8.5
- judge_reasoning stored in payload (private), never in telemetry
- iteration_count incremented inside evaluate node
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState
from backend.core.config import Settings, settings
from backend.db.models import Evaluation

logger = logging.getLogger(__name__)


def compute_tool_success(state: AgentState) -> bool:
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return True
    for call in tool_calls:
        if isinstance(call, dict):
            if call.get("error") or call.get("status") == "failed":
                return False
            error_code = call.get("error_code", "")
            if error_code in {"TOOL_TIMEOUT", "TOOL_VALIDATION_FAILURE", "TOOL_POLICY_FAILURE", "TOOL_EXCEPTION"}:
                return False
    return True


def check_final_answer_present(state: AgentState) -> bool:
    final_response = state.get("final_response", "")
    if final_response and final_response.strip():
        return True
    observations = state.get("observations", [])
    if observations:
        last_obs = observations[-1]
        if isinstance(last_obs, dict):
            content = last_obs.get("content", "") or last_obs.get("output", "")
            if content and content.strip():
                return True
    return False


async def evaluate_node(state: AgentState, config: dict) -> dict[str, Any]:
    logger.info(f"[evaluate_node] Starting evaluation for task {state['task_id']}, run {state['run_id']}, iteration {state['iteration_count'] + 1}")

    db_session: AsyncSession | None = config.get("db_session")
    runtime: AgentRuntime | None = config.get("runtime")
    cfg_settings: Settings = config.get("settings", settings)

    if not db_session:
        logger.error("[evaluate_node] No db_session in config")
        return _error_evaluation_state(state, "Missing db_session")
    if not runtime:
        logger.error("[evaluate_node] No runtime in config")
        return _error_evaluation_state(state, "Missing runtime")

    try:
        deterministic_pass = state.get("deterministic_pass", True)
        tool_success = compute_tool_success(state)

        judge_result = await runtime.llm_provider.judge(state)
        judge_score = float(judge_result.get("judge_score", 0.0))
        judge_reasoning = judge_result.get("judge_reasoning", "")
        generalizable = judge_result.get("generalizable", False)
        judge_score = max(0.0, min(10.0, judge_score))

        final_answer_present = check_final_answer_present(state)

        task_success = (
            deterministic_pass
            and tool_success
            and judge_score >= cfg_settings.TASK_SUCCESS_THRESHOLD
            and final_answer_present
        )

        iteration_count = state["iteration_count"] + 1
        tool_call_count = len(state.get("tool_calls", []))

        evaluation_data = {
            "task_success": task_success,
            "deterministic_pass": deterministic_pass,
            "tool_success": tool_success,
            "judge_score": judge_score,
            "judge_reasoning": judge_reasoning,
            "final_answer_present": final_answer_present,
            "iteration_count": iteration_count,
            "tool_call_count": tool_call_count,
            "generalizable": generalizable,
        }

        logger.info(f"[evaluate_node] Evaluation complete: task_success={task_success}, judge_score={judge_score}, deterministic_pass={deterministic_pass}, tool_success={tool_success}, final_answer_present={final_answer_present}, iteration_count={iteration_count}")

        try:
            evaluation_row = Evaluation(
                run_id=state["run_id"],
                user_id=state["user_id"],
                iteration_count=iteration_count,
                task_success=task_success,
                deterministic_pass=deterministic_pass,
                tool_success=tool_success,
                judge_score=Decimal(str(judge_score)),
                tool_call_count=tool_call_count,
                payload={"judge_reasoning": judge_reasoning} if judge_reasoning else {},
            )
            db_session.add(evaluation_row)
            await db_session.flush()
            logger.debug(f"[evaluate_node] Persisted evaluation row for iteration {iteration_count}")
        except Exception as e:
            logger.error(f"[evaluate_node] Failed to persist evaluation: {e}")
            await db_session.rollback()

        try:
            event_metadata = {
                "task_success": task_success,
                "deterministic_pass": deterministic_pass,
                "tool_success": tool_success,
                "judge_score": judge_score,
                "iteration_count": iteration_count,
                "tool_call_count": tool_call_count,
            }
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="evaluation_completed",
                status="running",
                metadata=event_metadata,
                session=db_session,
            )
            logger.debug("[evaluate_node] Emitted evaluation_completed event")
        except Exception as e:
            logger.warning(f"[evaluate_node] Failed to emit evaluation_completed event: {e}")

        return {"evaluation": evaluation_data, "iteration_count": iteration_count}

    except Exception as e:
        logger.error(f"[evaluate_node] Unexpected error during evaluation: {e}", exc_info=True)
        return _error_evaluation_state(state, str(e))


def _error_evaluation_state(state: AgentState, error_msg: str) -> dict[str, Any]:
    iteration_count = state["iteration_count"] + 1
    return {
        "evaluation": {
            "task_success": False,
            "deterministic_pass": False,
            "tool_success": False,
            "judge_score": 0.0,
            "judge_reasoning": f"Evaluation error: {error_msg}",
            "final_answer_present": False,
            "iteration_count": iteration_count,
            "tool_call_count": len(state.get("tool_calls", [])),
            "generalizable": False,
        },
        "iteration_count": iteration_count,
        "error": error_msg,
    }


__all__ = ["evaluate_node", "compute_tool_success", "check_final_answer_present"]
