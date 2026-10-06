"""
Execution node for LangGraph agent.

Source of truth: BLUEPRINT.md §8, §9, §13.

This node executes the current step using available tools.
Dispatches to tool implementations based on the step description.

Design rules:
- Reads current_step from state
- Dispatches to appropriate tool via _dispatch_tool
- Updates tool_calls with result/error
- Returns updated tool_calls and potentially final_response
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.runtime import AgentRuntime, get_runtime
from backend.agent.state import AgentState
from backend.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Initialize tool registry
tool_registry = ToolRegistry()


async def execute_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: execute the current step using available tools.

    Source: BLUEPRINT.md §8, §9, §13.

    Args:
        state: Current AgentState with plan, current_step, tool_calls, task_id, run_id, user_id.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission

    Returns:
        dict: State update with tool_calls and optionally final_response.
    """
    logger.info(f"[execute_node] Starting execution for task {state['task_id']}, run {state['run_id']}, step: {state.get('current_step', 'unknown')}")

    runtime: AgentRuntime | None = get_runtime(config)
    current_step = state.get("current_step", "")
    tool_calls = state.get("tool_calls", [])

    if not current_step:
        logger.warning("[execute_node] No current_step in state")
        return {"tool_calls": tool_calls}

    # Emit tool_started event per BLUEPRINT.md §14
    if runtime:
        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="tool_started",
                status="running",
                metadata={"step": current_step[:200]},
            )
            logger.debug("[execute_node] Emitted tool_started event")
        except Exception as e:
            logger.warning(f"[execute_node] Failed to emit tool_started event: {e}")

    # Dispatch to appropriate tool
    tool_result = await _dispatch_tool(current_step, state, runtime)

    # Append tool call to history
    new_tool_call = {
        "tool": tool_result.get("tool", "unknown"),
        "status": tool_result.get("status", "failed"),
        "result": tool_result.get("result"),
        "error": tool_result.get("error"),
        "error_code": tool_result.get("error_code"),
        "execution_time_ms": tool_result.get("execution_time_ms", 0),
    }
    updated_tool_calls = tool_calls + [new_tool_call]

    # Check if this step produced a final answer
    final_response = tool_result.get("final_response")
    if final_response:
        logger.info(f"[execute_node] Final response produced for task {state['task_id']}")
        result = {"tool_calls": updated_tool_calls, "final_response": final_response}
    else:
        result = {"tool_calls": updated_tool_calls}

    # Emit event
    if runtime:
        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="tool_completed",
                status="running",
                metadata={
                    "tool": new_tool_call["tool"],
                    "status": new_tool_call["status"],
                    "execution_time_ms": new_tool_call["execution_time_ms"],
                },
            )
            logger.debug("[execute_node] Emitted tool_completed event")
        except Exception as e:
            logger.warning(f"[execute_node] Failed to emit tool_completed event: {e}")

    return result


async def _dispatch_tool(step: str, state: AgentState, runtime: AgentRuntime | None) -> dict[str, Any]:
    """
    Dispatch step to appropriate tool implementation.

    CRITICAL: Must never use "internal" as a tool name. If a tool is not found
    in the registry, fall back to a registered tool based on task type.

    Args:
        step: Current step description
        state: Current AgentState
        runtime: AgentRuntime for LLM provider and event emission

    Returns:
        dict: Tool execution result with tool, status, result, error, error_code, execution_time_ms, optional final_response
    """
    import time
    start_time = time.time()

    try:
        # Use LLM provider to decide which tool to use and with what arguments
        tool_name = None
        tool_args = {}

        if runtime and hasattr(runtime.llm_provider, "act"):
            tool_decision = await runtime.llm_provider.act(state)
            tool_name = tool_decision.get("tool")
            tool_args = tool_decision.get("args", {})

        # CRITICAL: Never use "internal" - it's not a registered tool
        if not tool_name or tool_name == "internal":
            # Fall back based on task type
            task_type = state.get("task_type", "")
            if task_type == "math":
                tool_name = "calculator"
                # Try to extract expression from goal
                goal = state.get("goal", "")
                if not tool_args.get("expression"):
                    tool_args = {"expression": goal}
            elif task_type == "research":
                tool_name = "web_search"
                if not tool_args.get("query"):
                    tool_args = {"query": state.get("goal", "")}
            elif task_type == "file":
                tool_name = "file_reader"
            else:
                tool_name = "calculator"
                if not tool_args.get("expression"):
                    tool_args = {"expression": state.get("goal", "")}

        # Execute tool via registry
        tool = tool_registry.get(tool_name)
        if not tool:
            # Tool not in registry - try common registered tools
            available = tool_registry.list_tools()
            logger.warning(
                f"[_dispatch_tool] Tool '{tool_name}' not found. Available: {available}"
            )
            # Try calculator as last resort (it's always registered)
            if "calculator" in available:
                tool_name = "calculator"
                tool = tool_registry.get("calculator")
            elif available:
                tool_name = available[0]
                tool = tool_registry.get(tool_name)

        if tool:
            result = await tool.execute(state=state, **tool_args)
        else:
            result = {"error": f"No tools available", "error_code": "TOOL_NOT_FOUND"}

        execution_time_ms = int((time.time() - start_time) * 1000)

        if "error" in result:
            return {
                "tool": tool_name,
                "status": "failed",
                "result": None,
                "error": result.get("error"),
                "error_code": result.get("error_code", "TOOL_EXCEPTION"),
                "execution_time_ms": execution_time_ms,
            }

        # Build final response from calculator result
        tool_result_value = result.get("result")
        final_response = None
        if tool_result_value is not None and tool_name == "calculator":
            goal = state.get("goal", "")
            final_response = f"The result of the calculation is: {tool_result_value}\n\n{goal} = {tool_result_value}"

        # Check if tool indicates final response
        if not final_response:
            final_response = result.get("final_response")

        if final_response:
            return {
                "tool": tool_name,
                "status": "success",
                "result": result,
                "error": None,
                "error_code": None,
                "execution_time_ms": execution_time_ms,
                "final_response": final_response,
            }

        return {
            "tool": tool_name,
            "status": "success",
            "result": result,
            "error": None,
            "error_code": None,
            "execution_time_ms": execution_time_ms,
        }

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[_dispatch_tool] Tool execution failed: {e}", exc_info=True)
        return {
            "tool": "unknown",
            "status": "failed",
            "result": None,
            "error": str(e),
            "error_code": "TOOL_EXCEPTION",
            "execution_time_ms": execution_time_ms,
        }


__all__ = ["execute_node"]