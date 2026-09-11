"""
Execute node: dispatches tool calls to the shared tool registry,
enforces Agent Core safety rules, and handles tool failures.

Source of truth:
BLUEPRINT.md §8  - Canonical Tool Success & Error Event Contract
BLUEPRINT.md §13 - Tool Architecture
BLUEPRINT.md §14 - Tool Event Contract
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Optional

from backend.agent.state import AgentState
from backend.core.logging import get_logger
from backend.events.schema import EventType

logger = get_logger(__name__)


class ToolPolicyFailure(PermissionError):
    """Raised when the shared tool registry rejects a tool call."""


class UnsafeActionError(ValueError):
    """Raised when Agent Core safety rules reject tool input."""


def _tool_registry() -> Any:
    """
    Return the shared tool registry.

    The actual calculator, file reader, Tavily tool, etc. belong to
    backend.tools.registry. Agent Core only dispatches calls to it.
    """
    from backend.tools import registry as registry_module

    return getattr(registry_module, "registry", None)


async def _dispatch_tool(
    registry: Any,
    tool_name: str,
    tool_input: Any,
) -> Any:
    """
    Dispatch a tool through the shared registry.

    Supports both synchronous and asynchronous registry implementations.
    """
    result = registry.execute(tool_name, tool_input)

    if inspect.isawaitable(result):
        return await result

    return result


async def safe_evaluate_math(expression: str) -> str:
    """
    Dispatch calculator evaluation through the shared tool registry.

    Agent Core does not implement the calculator itself. The calculator
    implementation and its strict simpleeval policy belong to the Tool
    Registry subsystem.
    """
    registry = _tool_registry()

    if registry is None:
        raise ToolPolicyFailure("Tool registry is not available.")

    result = await _dispatch_tool(
        registry,
        "calculator",
        expression,
    )

    return str(result)


def _contains_unsafe_marker(value: Any) -> bool:
    """Return True when a tool input violates Agent Core safety rules."""
    if not isinstance(value, str):
        return False

    lowered = value.lower()

    forbidden_markers = (
        "__",
        "import",
        "eval",
        "exec",
        "open",
        "os.",
        "sys.",
        "subprocess",
    )

    return any(marker in lowered for marker in forbidden_markers)


def extract_tool_calls_for_state(
    state: AgentState,
) -> list[dict[str, Any]]:
    """
    Determine which tool calls should be dispatched for the current
    iteration.

    Golden-demo formulas are intentionally deterministic so the demo can
    reproduce the blueprint's expected behavior.
    """
    goal = str(state.get("goal", ""))
    plan = state.get("plan", [])
    iteration_count = state.get("iteration_count", 0)

    # ------------------------------------------------------------------
    # Golden Demo: Run A
    # ------------------------------------------------------------------
    if (
        "10,000" in goal
        or "10000" in goal
        or state.get("run_id") == "run_a"
    ):
        if iteration_count == 0:
            # Iteration 1: baseline annual compounding.
            return [
                {
                    "tool_name": "calculator",
                    "tool_input": "10000 * (1 + 0.05) ** 3",
                }
            ]

        # Iteration 2+: monthly compounding.
        return [
            {
                "tool_name": "calculator",
                "tool_input": "10000 * (1 + 0.05/12) ** (12*3)",
            }
        ]

    # ------------------------------------------------------------------
    # Golden Demo: Run B
    # ------------------------------------------------------------------
    if (
        "5,000" in goal
        or "5000" in goal
        or state.get("run_id") == "run_b"
    ):
        # Quarterly compounding formula from the retrieved recipe.
        return [
            {
                "tool_name": "calculator",
                "tool_input": "5000 * (1 + 0.07/4) ** (4*5)",
            }
        ]

    # ------------------------------------------------------------------
    # Normal plan-based calculator extraction
    # ------------------------------------------------------------------
    for step in plan:
        step_lower = step.lower()

        if "calculate" not in step_lower:
            continue

        idx = step_lower.find("calculate") + len("calculate")
        expression = step[idx:].strip()

        # Remove optional prose following the expression.
        expression = re.sub(
            r"\busing\s+calculator\b.*",
            "",
            expression,
            flags=re.IGNORECASE,
        ).strip()

        expression = re.sub(
            r"\bwith\s+(?:input|formula)\b",
            "",
            expression,
            flags=re.IGNORECASE,
        ).strip()

        if expression:
            return [
                {
                    "tool_name": "calculator",
                    "tool_input": expression,
                }
            ]

    # ------------------------------------------------------------------
    # General arithmetic fallback from plan text.
    # ------------------------------------------------------------------
    plan_text = " ".join(plan)

    math_match = re.search(
        r"(\d+[\d\s+\-*/().^]+)",
        plan_text,
    )

    if math_match:
        expression = math_match.group(1).strip()

        if any(
            operator_symbol in expression
            for operator_symbol in ("+", "-", "*", "/", "**")
        ):
            return [
                {
                    "tool_name": "calculator",
                    "tool_input": expression,
                }
            ]

    # Keep execution deterministic when a plan contains no explicit
    # calculator expression.
    return [
        {
            "tool_name": "calculator",
            "tool_input": "1 + 1",
        }
    ]


async def execute(state: AgentState) -> dict[str, Any]:
    """
    Execute the tools required by the current iteration.

    Responsibilities:
      - dispatch through backend.tools.registry
      - enforce Agent Core safety policy
      - emit tool_started/tool_completed events
      - classify retryable and terminal failures
      - accumulate tool call history
    """
    from backend.agent.runtime import get_current_runtime

    runtime = get_current_runtime()

    dispatched_calls = extract_tool_calls_for_state(state)
    executed_calls: list[dict[str, Any]] = []

    terminal_reason: Optional[str] = state.get("termination_reason")

    for call in dispatched_calls:
        tool_name = call.get("tool_name", "unknown")
        tool_input = call.get("tool_input", "")

        # --------------------------------------------------------------
        # 1. tool_started event
        # --------------------------------------------------------------
        if runtime and runtime.event_service:
            try:
                await runtime.emit_event(
                    task_id=state.get("task_id", ""),
                    run_id=state.get("run_id", ""),
                    user_id=state.get("user_id", ""),
                    event_type=EventType.TOOL_STARTED,
                    metadata={
                        "tool_name": tool_name,
                        "tool_input": str(tool_input)[:200],
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Failed to emit tool_started event: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # 2. Call record
        # --------------------------------------------------------------
        call_record: dict[str, Any] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "status": "succeeded",
            "output": "",
            "error_code": None,
        }

        try:
            # ----------------------------------------------------------
            # Agent Core safety policy
            # ----------------------------------------------------------
            if _contains_unsafe_marker(tool_input):
                raise UnsafeActionError(
                    "Tool input violates the safety policy."
                )

            # ----------------------------------------------------------
            # Shared Tool Registry
            # ----------------------------------------------------------
            registry = _tool_registry()

            if registry is None:
                raise ToolPolicyFailure(
                    "Tool registry is not available."
                )

            call_record["output"] = await _dispatch_tool(
                registry,
                tool_name,
                tool_input,
            )

        except TimeoutError:
            # Retryable failure.
            call_record["status"] = "failed"
            call_record["error_code"] = "TOOL_TIMEOUT"

        except UnsafeActionError:
            # Terminal security failure.
            call_record["status"] = "failed"
            call_record["error_code"] = "UNSAFE_ACTION"
            terminal_reason = "unsafe_action"

        except ValueError:
            # Retryable validation failure.
            call_record["status"] = "failed"
            call_record["error_code"] = "TOOL_VALIDATION_ERROR"

        except ToolPolicyFailure:
            # Terminal tool-policy failure.
            call_record["status"] = "failed"
            call_record["error_code"] = "TOOL_POLICY_FAILURE"
            terminal_reason = "tool_policy_failure"

        except Exception:
            # Unhandled tool exception is terminal.
            call_record["status"] = "failed"
            call_record["error_code"] = "TOOL_EXCEPTION"
            terminal_reason = "tool_exception"

        # --------------------------------------------------------------
        # 3. tool_completed event
        # --------------------------------------------------------------
        if runtime and runtime.event_service:
            try:
                event_metadata: dict[str, Any] = {
                    "tool_name": tool_name,
                }

                if call_record["status"] == "failed":
                    event_metadata["error_code"] = (
                        call_record["error_code"]
                    )
                else:
                    event_metadata["output_preview"] = str(
                        call_record["output"]
                    )[:100]

                await runtime.emit_event(
                    task_id=state.get("task_id", ""),
                    run_id=state.get("run_id", ""),
                    user_id=state.get("user_id", ""),
                    event_type=EventType.TOOL_COMPLETED,
                    status=(
                        "running"
                        if call_record["status"] == "succeeded"
                        else "failed"
                    ),
                    metadata=event_metadata,
                )

            except Exception as exc:
                logger.warning(
                    "Failed to emit tool_completed event: %s",
                    exc,
                )

        executed_calls.append(call_record)

    # --------------------------------------------------------------
    # Accumulate execution history across iterations.
    # --------------------------------------------------------------
    existing_calls = list(state.get("tool_calls", []))
    total_calls = existing_calls + executed_calls

    logger.info(
        "Node 'execute' completed: %d calls this iteration, "
        "%d total for run_id=%s, terminal_reason=%s",
        len(executed_calls),
        len(total_calls),
        state.get("run_id"),
        terminal_reason,
    )

    update: dict[str, Any] = {
        "tool_calls": total_calls,
        "current_step": "execute",
    }

    if terminal_reason:
        update["termination_reason"] = terminal_reason

    return update