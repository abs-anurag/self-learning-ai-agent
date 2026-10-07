"""
Execute node for METIS agent graph.

Source of truth: BLUEPRINT.md §8, §12, §13, §14.
Dispatches tool calls to ToolRegistry; handles timeouts, policy violations, and errors.
Emits tool_started and tool_completed telemetry events.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from backend.agent.runtime import get_current_runtime
from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType
from backend.tools.registry import default_tool_registry

logger = get_logger(__name__)


async def execute_node(state: AgentState) -> dict[str, Any]:
    """
    LangGraph node: execute.
    Determines next action and executes requested tool if needed.
    Emits tool_started and tool_completed events.
    """
    runtime = get_current_runtime()
    llm = runtime.llm_provider

    step_decision = await llm.decide_step_action(state)
    call_tool = step_decision.get("call_tool", False)
    tool_name = step_decision.get("tool_name")
    parameters = step_decision.get("parameters", {})

    tool_calls = list(state.get("tool_calls", []))
    observations = list(state.get("observations", []))
    termination_reason = state.get("termination_reason")
    error = state.get("error")

    if call_tool and tool_name:
        tool_call_id = str(uuid.uuid4())
        tool_call_record = {
            "id": tool_call_id,
            "tool": tool_name,
            "parameters": parameters,
        }
        tool_calls.append(tool_call_record)

        # Emit tool_started event
        try:
            await runtime.emit_event(
                task_id=uuid.UUID(state["task_id"]),
                run_id=uuid.UUID(state["run_id"]),
                user_id=uuid.UUID(state["user_id"]),
                event_type=EventType.TOOL_STARTED,
                status="running",
                metadata={
                    "tool_name": tool_name,
                    "parameters": parameters,
                },
            )
        except Exception as exc:
            logger.warning("Failed to emit tool_started event: %s", exc)

        # Execute tool via ToolRegistry
        result = await default_tool_registry.execute_tool(tool_name, parameters)

        # Check for error classifications
        is_success = result.get("success", False)
        error_code = result.get("error_code")
        event_status = "running" if is_success else "failed"

        obs_record = {
            "tool": tool_name,
            "success": is_success,
            "output": result.get("output", result),
        }
        if not is_success:
            obs_record["error_code"] = error_code
            obs_record["error"] = result.get("error")

            # Check terminal vs retriable failure per BLUEPRINT.md §8
            if error_code in ("TOOL_POLICY_FAILURE", "TOOL_EXCEPTION"):
                termination_reason = error_code.lower()
                error = result.get("error")

        observations.append(obs_record)

        # Emit tool_completed event per BLUEPRINT.md §8 Tool Error Event Contract
        try:
            event_meta = {"tool_name": tool_name}
            if not is_success and error_code:
                event_meta["error_code"] = error_code
            else:
                event_meta["status"] = "success"

            await runtime.emit_event(
                task_id=uuid.UUID(state["task_id"]),
                run_id=uuid.UUID(state["run_id"]),
                user_id=uuid.UUID(state["user_id"]),
                event_type=EventType.TOOL_COMPLETED,
                status=event_status,
                metadata=event_meta,
            )
        except Exception as exc:
            logger.warning("Failed to emit tool_completed event: %s", exc)

    return {
        "tool_calls": tool_calls,
        "observations": observations,
        "termination_reason": termination_reason,
        "error": error,
        "current_step": "observe",
    }
