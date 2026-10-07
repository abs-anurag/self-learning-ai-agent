"""
Respond node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §10, §14, §15, §18.
Formats final_response, sets final status, persists episodic experience,
updates task and task_run rows atomically, and emits terminal telemetry.
"""

from __future__ import annotations

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
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    resp_dict = await llm.respond(state)
    final_response = resp_dict.get("final_response", "")

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
            async with runtime.session_factory() as active_session:
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
                logger.info("Updated task %s and run %s to %s", task_id_uuid, run_id_uuid, final_status)
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

    return {
        "final_response": final_response,
        "status": final_status,
        "termination_reason": termination_reason,
        "current_step": "respond",
    }
