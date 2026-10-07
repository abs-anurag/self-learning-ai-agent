"""
AgentState definition, validation helpers, and routing logic.

Source of truth: BLUEPRINT.md §8, §9, §14.

Design rules:
- Strictly implements the 20 typed fields of AgentState from §9.
- AgentState.status is execution-local graph state. The authoritative status
  for execution is task_runs.status in PostgreSQL (§9).
- Status vocabulary is strictly unified: 'pending', 'running', 'succeeded', 'failed'.
  The value 'completed' is strictly forbidden (§1, §9, Appendix B).
- Telemetry security (§9, §17):
  Secrets, full system prompts, and chain-of-thought are never placed into AgentState.
- Large tool results are truncated before state assignment (§9).
- route_after_evaluate implements the conditional edge logic defined in §8.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Final, List, Optional, Set, TypedDict, Union

from backend.core.config import settings
from backend.core.logging import redact_value
from backend.events.schema import is_prohibited_key

# -- Constants & Vocabularies ------------------------------------

VALID_TASK_TYPES: Final[frozenset[str]] = frozenset(
    {"math", "research", "file", "code", "mixed", ""}
)

VALID_LEARNING_DECISIONS: Final[frozenset[str]] = frozenset(
    {"skip", "candidate_only", "promoted", ""}
)

VALID_STATUSES: Final[frozenset[str]] = frozenset(
    {"pending", "running", "succeeded", "failed"}
)

TERMINAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "repeated_failure",
        "llm_failure",
        "timeout",
        "unsafe_action",
        "invalid_state",
        "tool_policy_failure",
        "tool_exception",
        "max_iterations",
    }
)

DEFAULT_MAX_OBSERVATION_CHARS: Final[int] = 10000


# -- AgentState Schema -------------------------------------------


class AgentState(TypedDict):
    """
    Canonical working / graph state for the current run.
    Source: BLUEPRINT.md §9.

    Checkpointed by AsyncPostgresSaver for inspection and debug.
    """
    task_id: str
    run_id: str
    user_id: str
    goal: str
    understood_task: str
    task_type: str  # "math" | "research" | "file" | "code" | "mixed"
    retrieved_recipes: list[dict[str, Any]]
    plan: list[str]
    current_step: str
    tool_calls: list[dict[str, Any]]
    observations: list[dict[str, Any]]
    evaluation: dict[str, Any]
    reflection: str
    candidate_recipe: Optional[dict[str, Any]]
    learning_decision: str  # "skip" | "candidate_only" | "promoted"
    final_response: str
    status: str  # "pending" | "running" | "succeeded" | "failed"
    termination_reason: Optional[str]
    iteration_count: int
    max_iterations: int
    error: Optional[str]


# -- State Helpers & Factory -------------------------------------


def create_initial_state(
    task_id: str,
    run_id: str,
    user_id: str,
    goal: str,
    *,
    max_iterations: Optional[int] = None,
    status: str = "running",
) -> AgentState:
    """
    Create a clean, validated initial AgentState with safe defaults.

    iteration_count begins at 0.
    max_iterations defaults to settings.MAX_ITERATIONS (3 per §2, §8).
    """
    if not task_id or not run_id or not user_id:
        raise ValueError("task_id, run_id, and user_id must be non-empty strings.")

    if not goal:
        raise ValueError("goal must be a non-empty string.")

    status_clean = status.lower().strip()
    if status_clean == "completed":
        raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
    if status_clean not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}.")

    max_iter = max_iterations if max_iterations is not None else settings.MAX_ITERATIONS

    state: AgentState = {
        "task_id": str(task_id),
        "run_id": str(run_id),
        "user_id": str(user_id),
        "goal": goal.strip(),
        "understood_task": "",
        "task_type": "",
        "retrieved_recipes": [],
        "plan": [],
        "current_step": "",
        "tool_calls": [],
        "observations": [],
        "evaluation": {},
        "reflection": "",
        "candidate_recipe": None,
        "learning_decision": "",
        "final_response": "",
        "status": status_clean,
        "termination_reason": None,
        "iteration_count": 0,
        "max_iterations": max_iter,
        "error": None,
    }
    return state


def validate_agent_state(state: AgentState) -> None:
    """
    Validate an AgentState instance for type conformance,
    required keys, valid status, and security compliance.
    """
    if not isinstance(state, dict):
        raise TypeError("AgentState must be a dictionary.")

    required_fields = {
        "task_id",
        "run_id",
        "user_id",
        "goal",
        "understood_task",
        "task_type",
        "retrieved_recipes",
        "plan",
        "current_step",
        "tool_calls",
        "observations",
        "evaluation",
        "reflection",
        "candidate_recipe",
        "learning_decision",
        "final_response",
        "status",
        "termination_reason",
        "iteration_count",
        "max_iterations",
        "error",
    }

    missing = required_fields - set(state.keys())
    if missing:
        raise ValueError(f"Missing required AgentState fields: {sorted(missing)}")

    status = state["status"]
    if status == "completed":
        raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status '{status}'. Must be one of {sorted(VALID_STATUSES)}.")

    task_type = state["task_type"]
    if task_type not in VALID_TASK_TYPES:
        raise ValueError(f"Invalid task_type '{task_type}'. Must be one of {sorted(VALID_TASK_TYPES)}.")

    learning_decision = state["learning_decision"]
    if learning_decision not in VALID_LEARNING_DECISIONS:
        raise ValueError(
            f"Invalid learning_decision '{learning_decision}'. "
            f"Must be one of {sorted(VALID_LEARNING_DECISIONS)}."
        )

    term_reason = state["termination_reason"]
    if term_reason is not None and term_reason not in TERMINAL_REASONS:
        raise ValueError(
            f"Invalid termination_reason '{term_reason}'. "
            f"Must be None or one of {sorted(TERMINAL_REASONS)}."
        )

    if not isinstance(state["iteration_count"], int) or state["iteration_count"] < 0:
        raise ValueError("iteration_count must be a non-negative integer.")

    if not isinstance(state["max_iterations"], int) or state["max_iterations"] <= 0:
        raise ValueError("max_iterations must be a positive integer.")


def sanitize_state_update(update_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Sanitize a partial state update dictionary before merging into AgentState.

    - Strips prohibited telemetry keys (chain_of_thought, judge_reasoning, api_key, etc.).
    - Redacts sensitive token patterns from string values.
    - Rejects the forbidden status 'completed'.
    """
    if not isinstance(update_dict, dict):
        raise TypeError("State update must be a dictionary.")

    cleaned: dict[str, Any] = {}
    for k, v in update_dict.items():
        if is_prohibited_key(str(k)):
            continue

        if k == "status":
            if isinstance(v, str):
                v_clean = v.lower().strip()
                if v_clean == "completed":
                    raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
                if v_clean not in VALID_STATUSES:
                    raise ValueError(f"Invalid status '{v}'. Must be one of {sorted(VALID_STATUSES)}.")
                cleaned[k] = v_clean
                continue

        cleaned[k] = redact_value(v)

    return cleaned


def truncate_observation(
    text: str,
    max_chars: int = DEFAULT_MAX_OBSERVATION_CHARS,
) -> str:
    """
    Truncate large tool results before state assignment per BLUEPRINT.md §9:
    'Large tool results are truncated before state assignment.'
    """
    if not isinstance(text, str):
        text = str(text)

    if len(text) <= max_chars:
        return text

    suffix = f"\n... [TRUNCATED: {len(text) - max_chars} characters omitted]"
    allowed_len = max(0, max_chars - len(suffix))
    return text[:allowed_len] + suffix


# -- Routing Logic -----------------------------------------------


def route_after_evaluate(state: AgentState) -> str:
    """
    Pure conditional edge function evaluated immediately after the evaluate node.
    Source: BLUEPRINT.md §8 line 296 verbatim.

    iteration_count has already been incremented inside evaluate.
    """
    eval_info = state.get("evaluation") or {}
    if eval_info.get("task_success", False):
        return "maybe_learn"

    # Check max iterations boundary (after 3 completed iterations, state["iteration_count"] == 3)
    if state["iteration_count"] >= state["max_iterations"]:
        return "respond"

    # Check fatal termination reasons
    terminal_reasons = {
        "repeated_failure",
        "llm_failure",
        "timeout",
        "unsafe_action",
        "invalid_state",
        "tool_policy_failure",
        "tool_exception",
    }
    if state.get("termination_reason") in terminal_reasons:
        return "respond"

    return "reflect"
