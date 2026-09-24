"""
Execution node for LangGraph agent.

Source of truth: BLUEPRINT.md §8, §13.

This node dispatches tool calls to the ToolRegistry, handles timeouts and errors.
For MVP, we implement a basic executor that works with available tools.

Design rules:
- Reads current_step from state, determines which tool to call
- Calls tool with appropriate arguments
- Handles tool timeouts, validation failures, policy rejections
- Returns tool_calls list with results
- Emits tool_started and tool_completed events
- Errors don't halt execution (handled in evaluate)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.agent.runtime import AgentRuntime
from backend.agent.state import AgentState

logger = logging.getLogger(__name__)

# Tool timeout in seconds
TOOL_TIMEOUT = 30


async def execute_node(state: AgentState, config: dict) -> dict[str, Any]:
    """
    LangGraph node: execute the current step using appropriate tools.

    Source: BLUEPRINT.md §8, §13.

    Args:
        state: Current AgentState with plan, current_step, tool_calls.
        config: Configuration dict containing:
            - runtime: AgentRuntime for event emission
            - settings: Application settings

    Returns:
        dict: State update with tool_calls appended.

    Notes:
        - Dispatches to tools based on current_step
        - Emits tool_started and tool_completed events
        - Handles timeout, validation, policy errors
        - On error, records error in tool_calls and continues
    """
    logger.info(f"[execute_node] Starting execution for task {state['task_id']}, run {state['run_id']}")

    runtime: AgentRuntime | None = config.get("runtime")

    plan = state.get("plan", [])
    current_step = state.get("current_step", "")
    tool_calls = state.get("tool_calls", [])

    if not current_step and plan:
        current_step = plan[0]

    if not current_step:
        logger.warning("[execute_node] No current step to execute")
        return {"tool_calls": tool_calls}

    # For MVP/demo, we'll use a simple tool dispatcher
    # In production, this would use a proper ToolRegistry
    tool_result = await _dispatch_tool(current_step, state, runtime)

    # Build tool call record
    tool_call = {
        "tool": tool_result.get("tool", "unknown"),
        "arguments": tool_result.get("arguments", {}),
        "result": tool_result.get("result"),
        "error": tool_result.get("error"),
        "error_code": tool_result.get("error_code"),
        "status": tool_result.get("status", "completed"),
        "execution_time_ms": tool_result.get("execution_time_ms", 0),
    }

    # Update tool_calls
    updated_tool_calls = tool_calls + [tool_call]

    # Emit tool events
    if runtime:
        try:
            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="tool_started",
                status="running",
                metadata={"tool": tool_call["tool"], "step": current_step},
            )

            await runtime.emit_event(
                task_id=state["task_id"],
                run_id=state["run_id"],
                user_id=state["user_id"],
                event_type="tool_completed",
                status="completed" if not tool_call.get("error") else "failed",
                metadata={
                    "tool": tool_call["tool"],
                    "error_code": tool_call.get("error_code"),
                    "execution_time_ms": tool_call.get("execution_time_ms", 0),
                },
            )
        except Exception as e:
            logger.warning(f"[execute_node] Failed to emit tool events: {e}")

    return {"tool_calls": updated_tool_calls, "current_step": current_step}


async def _dispatch_tool(step: str, state: AgentState, runtime: AgentRuntime | None) -> dict[str, Any]:
    """
    Dispatch tool based on step description.
    For MVP, uses simple keyword matching.
    """
    start_time = time.time()
    step_lower = step.lower()

    # Determine tool from step
    if any(kw in step_lower for kw in ["calculate", "compute", "math", "arithmetic", "formula", "equation"]):
        tool_name = "calculator"
        # Extract expression from step
        expression = _extract_expression(step)
        result = await _call_calculator(expression)
    elif any(kw in step_lower for kw in ["search", "find", "look up", "research", "web"]):
        tool_name = "web_search"
        query = _extract_search_query(step)
        result = await _call_web_search(query)
    elif any(kw in step_lower for kw in ["read", "file", "path", "directory"]):
        tool_name = "file_reader"
        path = _extract_path(step)
        result = await _call_file_reader(path)
    else:
        # Default: calculator for math-like tasks
        tool_name = "calculator"
        expression = _extract_expression(step)
        result = await _call_calculator(expression)

    execution_time_ms = int((time.time() - start_time) * 1000)

    if result.get("error"):
        return {
            "tool": tool_name,
            "arguments": result.get("arguments", {}),
            "result": None,
            "error": result["error"],
            "error_code": result.get("error_code", "TOOL_EXCEPTION"),
            "status": "failed",
            "execution_time_ms": execution_time_ms,
        }

    return {
        "tool": tool_name,
        "arguments": result.get("arguments", {}),
        "result": result.get("result"),
        "error": None,
        "error_code": None,
        "status": "completed",
        "execution_time_ms": execution_time_ms,
    }


def _extract_expression(step: str) -> str:
    """Extract mathematical expression from step."""
    # Simple extraction - look for numbers and operators
    import re
    # Try to find a mathematical expression
    matches = re.findall(r'[\d\+\-\*\/\.\s\(\)\%]+', step)
    if matches:
        # Return the longest match that looks like an expression
        for match in sorted(matches, key=len, reverse=True):
            if any(op in match for op in ['+', '-', '*', '/', '%', '**']):
                return match.strip()
    return step


def _extract_search_query(step: str) -> str:
    """Extract search query from step."""
    # Remove common prefixes
    prefixes = ["search for", "find", "look up", "research", "web search"]
    step_lower = step.lower()
    for prefix in prefixes:
        if prefix in step_lower:
            idx = step_lower.index(prefix) + len(prefix)
            return step[idx:].strip()
    return step


def _extract_path(step: str) -> str:
    """Extract file path from step."""
    import re
    # Look for path-like patterns
    matches = re.findall(r'[\w\-\./\\]+', step)
    for match in matches:
        if '/' in match or '\\' in match or '.' in match:
            return match
    return "."


async def _call_calculator(expression: str) -> dict[str, Any]:
    """Call calculator tool."""
    try:
        # For now, use simple eval with safety (demo mode)
        # In production, this would call the actual calculator tool
        import simpleeval
        evaluator = simpleeval.SimpleEval()
        evaluator.functions = {}
        evaluator.names = {}
        result = evaluator.eval(expression)
        return {"result": str(result), "arguments": {"expression": expression}}
    except Exception as e:
        return {"error": str(e), "error_code": "TOOL_VALIDATION_FAILURE", "arguments": {"expression": expression}}


async def _call_web_search(query: str) -> dict[str, Any]:
    """Call web search tool."""
    # Placeholder for web search - returns empty result for demo
    return {"result": f"Search results for: {query} (demo mode - no actual search)", "arguments": {"query": query}}


async def _call_file_reader(path: str) -> dict[str, Any]:
    """Call file reader tool."""
    # Placeholder for file reader - returns empty result for demo
    return {"result": f"File content for: {path} (demo mode - no actual file read)", "arguments": {"path": path}}


__all__ = ["execute_node"]
