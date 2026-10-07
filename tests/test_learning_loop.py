"""
Unit tests for self-learning loop and candidate extraction.

Source of truth: BLUEPRINT.md §10, §11.
Verifies candidate extraction, non-triviality filter, and recipe candidate fields.
"""

from __future__ import annotations

import pytest

from backend.agent.state import create_initial_state
from backend.learning.candidate import extract_candidate_recipe


def test_extract_candidate_from_success():
    state = create_initial_state("t", "r", "u", "Calculate mortgage payment with interest")
    state["task_type"] = "math"
    state["understood_task"] = "Mortgage calculation"
    state["plan"] = ["Identify principal and rate", "Execute formula"]
    state["tool_calls"] = [{"tool": "calculator", "parameters": {"expression": "1000 * 0.05"}}]
    state["evaluation"] = {"task_success": True, "judge_score": 9.0}

    candidate = extract_candidate_recipe(state)
    assert candidate is not None
    assert candidate["task_type"] == "math"
    assert candidate["problem_pattern"] == "Mortgage calculation"
    assert "calculator" in candidate["tools_used"]
    assert candidate["status"] == "candidate"


def test_extract_candidate_fails_on_unsuccessful():
    state = create_initial_state("t", "r", "u", "Calculate mortgage")
    state["evaluation"] = {"task_success": False}
    candidate = extract_candidate_recipe(state)
    assert candidate is None


def test_extract_candidate_skips_trivial():
    state = create_initial_state("t", "r", "u", "1+1")  # Length < 5
    state["evaluation"] = {"task_success": True}
    candidate = extract_candidate_recipe(state)
    assert candidate is None
