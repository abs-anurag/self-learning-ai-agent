"""
Evaluation metrics computation.

Source of truth: BLUEPRINT.md §12.
Canonical task_success:
  task_success = (
      deterministic_pass
      and tool_success
      and (judge_score >= 6.0)
      and final_answer_present
  )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


def compute_deterministic_pass(
    tool_calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    error: Optional[str] = None,
) -> bool:
    """
    Check if deterministic constraints and policies were satisfied.
    No policy violations, no blocked operations, parameters within bounds.
    """
    if error and any(w in error.lower() for w in ("policy", "unauthorized", "security", "denied")):
        return False

    for obs in observations:
        if isinstance(obs, dict):
            if obs.get("error_code") == "TOOL_POLICY_FAILURE":
                return False
            output = obs.get("output", {})
            if isinstance(output, dict) and output.get("error_code") == "TOOL_POLICY_FAILURE":
                return False

    return True


def compute_tool_success(
    tool_calls: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> bool:
    """
    Every invoked tool completed successfully without timeout,
    validation failure, policy rejection, or unhandled exception.
    If no tools were called, returns True.
    """
    if not tool_calls and not observations:
        return True

    for obs in observations:
        if not isinstance(obs, dict):
            continue
        # Direct failure flags
        if obs.get("success") is False:
            return False
        if obs.get("error_code") in {
            "TOOL_TIMEOUT",
            "TOOL_VALIDATION_ERROR",
            "TOOL_POLICY_FAILURE",
            "TOOL_EXCEPTION",
        }:
            return False
        # Inside output dict
        out = obs.get("output")
        if isinstance(out, dict):
            if out.get("success") is False:
                return False
            if "error" in out:
                return False

    return True


def compute_task_success(
    *,
    deterministic_pass: bool,
    tool_success: bool,
    judge_score: float,
    final_answer_present: bool,
    threshold: Optional[float] = None,
) -> bool:
    """
    Compute canonical task_success boolean.
    threshold defaults to settings.TASK_SUCCESS_THRESHOLD (6.0).
    """
    cutoff = threshold if threshold is not None else settings.TASK_SUCCESS_THRESHOLD
    return bool(
        deterministic_pass
        and tool_success
        and (judge_score >= cutoff)
        and final_answer_present
    )
