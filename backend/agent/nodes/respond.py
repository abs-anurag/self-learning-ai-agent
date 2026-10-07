"""
Respond node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §10, §14, §15, §18.
Formats final_response, sets final status, persists episodic experience,
updates task and task_run rows atomically, and emits terminal telemetry.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from sqlalchemy import update

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.db.models import Task, TaskRun, TaskStatus
from backend.events.schema import EventType
from backend.memory.experiences import record_experience

logger = get_logger(__name__)


async def respond_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: respond.
    Generates user-facing response, persists experience, transitions status,
    and emits task_completed or task_failed.
    """
    logger.info("BEFORE respond: entering respond_node for run %s", state.get("run_id"))
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    eval_info = state.get("evaluation", {})
    task_success = eval_info.get("task_success", False)

    if task_success:
        final_status = TaskStatus.SUCCEEDED.value
        termination_reason = state.get("termination_reason") or "success"
        terminal_event = EventType.TASK_COMPLETED
    else:
        final_status = TaskStatus.FAILED.value
        termination_reason = state.get("termination_reason") or "max_iterations"
        terminal_event = EventType.TASK_FAILED

    # LLM response generation protected by deterministic timeout and fallback
    final_response = ""
    try:
        resp_dict = await asyncio.wait_for(llm.respond(state), timeout=25.0)
        final_response = resp_dict.get("final_response", "")
    except asyncio.TimeoutError:
        logger.warning(
            "llm.respond timed out in respond_node for run %s; synthesizing fallback response.",
            state.get("run_id"),
        )
    except Exception as exc:
        logger.warning(
            "llm.respond failed in respond_node for run %s: %s; synthesizing fallback response.",
            state.get("run_id"),
            exc,
        )

    if not final_response:
        if task_success:
            final_response = "Task execution completed successfully."
        elif termination_reason == "repeated_failure":
            final_response = "Task stopped: identical failure occurred repeatedly."
        elif termination_reason == "max_iterations":
            final_response = "Task stopped: maximum allowable iterations (3) reached."
        else:
            final_response = f"Task stopped due to {termination_reason or 'unresolved issue'}."

    task_id_uuid = uuid.UUID(state["task_id"])
    run_id_uuid = uuid.UUID(state["run_id"])
    user_id_uuid = uuid.UUID(state["user_id"])

    # Extract invoked tools for experience record
    tools_used = list(dict.fromkeys(
        tc.get("tool") for tc in state.get("tool_calls", []) if isinstance(tc, dict) and tc.get("tool")
    ))

    # Persist Experience and update DB task & task_run status
    if runtime.session_factory is not None:
        try:
            logger.info("BEFORE task status = %s in respond_node for run %s", final_status, run_id_uuid)
            async with runtime.session_factory() as active_session:
                try:
                    # 1. Record episodic experience per BLUEPRINT.md §10
                    await record_experience(
                        session=active_session,
                        task_id=task_id_uuid,
                        run_id=run_id_uuid,
                        user_id=user_id_uuid,
                        task_type=state.get("task_type", "research"),
                        tools_used=tools_used,
                        outcome_summary=final_response,
                    )

                    # 2. Update task_runs status and termination_reason
                    run_update = (
                        update(TaskRun)
                        .where(TaskRun.id == run_id_uuid)
                        .values(
                            status=final_status,
                            termination_reason=termination_reason,
                            iteration_count=state.get("iteration_count", 0),
                        )
                    )
                    await active_session.execute(run_update)

                    # 3. Update tasks status
                    task_update = (
                        update(Task)
                        .where(Task.id == task_id_uuid)
                        .values(status=final_status)
                    )
                    await active_session.execute(task_update)

                    await active_session.commit()
                    logger.info("AFTER task status = %s: updated task %s and run %s", final_status, task_id_uuid, run_id_uuid)
                except Exception as inner_exc:
                    await active_session.rollback()
                    raise inner_exc
        except Exception as exc:
            logger.error("DB error in respond_node: %s", exc)

    # Emit terminal event (task_completed or task_failed) per BLUEPRINT.md §14
    try:
        await runtime.emit_event(
            task_id=task_id_uuid,
            run_id=run_id_uuid,
            user_id=user_id_uuid,
            event_type=terminal_event,
            status=final_status,
            metadata={
                "final_response": final_response,
                "outcome_summary": final_response,
                "termination_reason": termination_reason,
                "iteration_count": state.get("iteration_count", 0),
            },
        )
    except Exception as exc:
        logger.warning("Failed to emit terminal event: %s", exc)

    logger.info("AFTER respond: finished respond_node for run %s with status %s", run_id_uuid, final_status)

    return {
        "final_response": final_response,
        "status": final_status,
        "termination_reason": termination_reason,
        "current_step": "respond",
    }
