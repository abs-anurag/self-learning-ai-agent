"""
Evaluate node: computes composite evaluation, increments iteration_count, and records metrics.

Source of truth: BLUEPRINT.md §6, §8, §11, §12, §14, §17.

Rules:
- Exactly one evaluation row per completed iteration (UNIQUE(run_id, iteration_count)).
- iteration_count increments by 1 inside evaluate node return dictionary.
- Canonical task_success definition:
    deterministic_pass AND tool_success AND (judge_score >= 6.0) AND final_answer_present
- Telemetry privacy (§17): judge_reasoning is private; NEVER emitted in telemetry.
"""

from __future__ import annotations

import uuid
from typing import Any

from backend.agent.state import AgentState
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import Evaluation
from backend.events.schema import EventType

logger = get_logger(__name__)


async def evaluate(state: AgentState) -> dict[str, Any]:
    """
    Computes composite evaluation, increments iteration_count, and emits evaluation_completed.
    Source: BLUEPRINT.md §8 line 333, §12.
    """
    from backend.agent.runtime import get_current_runtime, get_llm_provider

    runtime = get_current_runtime()
    provider = runtime.llm_provider if runtime else get_llm_provider()

    # Increment iteration_count by 1 for this completed cycle (BLUEPRINT.md §8 lines 266-271)
    current_iter = state.get("iteration_count", 0)
    new_iteration_count = current_iter + 1
    max_iterations = state.get("max_iterations", settings.MAX_ITERATIONS)

    # The current iteration is the completed cycle represented by this row.
    tool_calls = state.get("tool_calls", [])
    tool_call_count = len(tool_calls) if current_iter == 0 else max(1, len(tool_calls) - current_iter)
    tool_success = (
        all(c.get("status") == "succeeded" for c in tool_calls[-tool_call_count:])
        if tool_calls
        else True
    )

    # 2. Check deterministic pass (no terminal security flags or fatal reasons)
    existing_terminal = state.get("termination_reason")
    deterministic_pass = existing_terminal is None and tool_success

    # 3. Call LLM provider judge for rubric evaluation (§12, §15)
    try:
        judge_res = await provider.judge(state)
    except TimeoutError:
        return {
            "evaluation": {
                "task_success": False,
                "deterministic_pass": False,
                "tool_success": False,
                "judge_score": 0.0,
                "iteration_count": new_iteration_count,
                "tool_call_count": tool_call_count,
            },
            "iteration_count": new_iteration_count,
            "termination_reason": "timeout",
            "error": "Language model request timed out.",
            "current_step": "evaluate",
        }
    except Exception:
        return {
            "evaluation": {
                "task_success": False,
                "deterministic_pass": False,
                "tool_success": False,
                "judge_score": 0.0,
                "iteration_count": new_iteration_count,
                "tool_call_count": tool_call_count,
            },
            "iteration_count": new_iteration_count,
            "termination_reason": "llm_failure",
            "error": "Language model provider returned an error.",
            "current_step": "evaluate",
        }

    judge_score = float(judge_res.get("judge_score", 5.0))
    if "deterministic_pass" in judge_res:
        deterministic_pass = deterministic_pass and bool(judge_res["deterministic_pass"])
    if "tool_success" in judge_res:
        tool_success = tool_success and bool(judge_res["tool_success"])

    # 4. A failed observation is not a final answer.
    observations = state.get("observations", [])
    final_answer_present = bool(state.get("final_response")) or any(
        item.get("status") == "succeeded" and bool(item.get("output"))
        for item in observations
    )

    # 5. Canonical task_success calculation (§12 line 543)
    task_success = (
        deterministic_pass
        and tool_success
        and judge_score >= settings.TASK_SUCCESS_THRESHOLD
        and final_answer_present
    )
    evaluation_dict: dict[str, Any] = {
        "task_success": task_success,
        "deterministic_pass": deterministic_pass,
        "tool_success": tool_success,
        "judge_score": max(0.0, min(10.0, judge_score)),
        "iteration_count": new_iteration_count,
        "tool_call_count": tool_call_count,
    }
    task_success = bool(evaluation_dict["task_success"])

    # 6. Check termination reason on iteration exhaustion
    termination_reason = existing_terminal
    if not task_success and new_iteration_count >= max_iterations and not termination_reason:
        termination_reason = "max_iterations"

    if runtime and runtime.persistence_enabled:
        try:
            async with runtime.session_factory() as session:
                session.add(
                    Evaluation(
                        run_id=uuid.UUID(str(state["run_id"])),
                        user_id=uuid.UUID(str(state["user_id"])),
                        iteration_count=new_iteration_count,
                        task_success=task_success,
                        deterministic_pass=bool(evaluation_dict["deterministic_pass"]),
                        tool_success=bool(evaluation_dict["tool_success"]),
                        judge_score=evaluation_dict["judge_score"],
                        tool_call_count=tool_call_count,
                        payload={"generalizable": bool(judge_res.get("generalizable", False))},
                    )
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Evaluation persistence failed: %s", type(exc).__name__)

    # 7. Emit evaluation_completed event (telemetry stripped of judge_reasoning per §12, §17)
    if runtime and runtime.event_service:
        try:
            safe_meta = {
                "task_success": task_success,
                "deterministic_pass": deterministic_pass,
                "tool_success": tool_success,
                "judge_score": judge_score,
                "iteration_count": new_iteration_count,
                "tool_call_count": tool_call_count,
            }
            await runtime.emit_event(
                task_id=state.get("task_id", ""),
                run_id=state.get("run_id", ""),
                user_id=state.get("user_id", ""),
                event_type=EventType.EVALUATION_COMPLETED,
                status="running" if task_success or new_iteration_count < max_iterations else "failed",
                metadata=safe_meta,
            )
        except Exception as exc:
            logger.warning("Failed to emit evaluation_completed event: %s", exc)

    logger.info(
        "Node 'evaluate' completed: iteration=%d/%d, task_success=%s, judge_score=%.1f",
        new_iteration_count,
        max_iterations,
        task_success,
        judge_score,
    )

    update: dict[str, Any] = {
        "evaluation": evaluation_dict,
        "iteration_count": new_iteration_count,
        "current_step": "evaluate",
    }
    if termination_reason:
        update["termination_reason"] = termination_reason

    return update
