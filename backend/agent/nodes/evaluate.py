"""
Evaluate node for LangGraph agent.

Source of truth: BLUEPRINT.md §8, §12.

This module re-exports the evaluate_node implementation from
backend.evaluation.scorer, maintaining the file location contract
defined in BLUEPRINT.md §8 Node Table.
"""

from __future__ import annotations

from backend.evaluation.scorer import (
    check_final_answer_present,
    compute_tool_success,
    evaluate_node,
)

__all__ = [
    "evaluate_node",
    "compute_tool_success",
    "check_final_answer_present",
]