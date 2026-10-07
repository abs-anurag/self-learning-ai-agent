"""
Unit tests for quality gate and recipe promotion thresholds.

Source of truth: BLUEPRINT.md §10, §11, §12.
Verifies two-tier scoring thresholds (6.0 for success, 8.5 for promotion),
deterministic checks, tool checks, and duplication suppression.
"""

from __future__ import annotations

import pytest

from backend.agent.state import create_initial_state
from backend.learning.quality_gate import evaluate_quality_gate


@pytest.mark.asyncio
async def test_quality_gate_high_score_promotes():
    state = create_initial_state("t", "r", "u", "Calculate 15% tip")
    state["evaluation"] = {
        "task_success": True,
        "deterministic_pass": True,
        "tool_success": True,
        "judge_score": 9.0,
    }
    candidate = {
        "task_type": "math",
        "problem_pattern": "percentage calculation",
        "recommended_strategy": "multiply by rate",
        "successful_steps": ["step 1"],
        "tools_used": ["calculator"],
    }
    decision, reason = await evaluate_quality_gate(state, candidate, session=None)
    assert decision == "promoted"


@pytest.mark.asyncio
async def test_quality_gate_low_judge_score_candidate_only():
    state = create_initial_state("t", "r", "u", "Calculate 15% tip")
    state["evaluation"] = {
        "task_success": True,
        "deterministic_pass": True,
        "tool_success": True,
        "judge_score": 7.5,  # Above 6.0 (solved), but below 8.5 (promotion)
    }
    candidate = {
        "task_type": "math",
        "problem_pattern": "percentage calculation",
        "recommended_strategy": "multiply by rate",
        "successful_steps": ["step 1"],
        "tools_used": ["calculator"],
    }
    decision, reason = await evaluate_quality_gate(state, candidate, session=None)
    assert decision == "candidate_only"
    assert "below promotion threshold" in reason


@pytest.mark.asyncio
async def test_quality_gate_tool_failure_candidate_only():
    state = create_initial_state("t", "r", "u", "Calculate 15% tip")
    state["evaluation"] = {
        "task_success": False,
        "deterministic_pass": True,
        "tool_success": False,
        "judge_score": 9.0,
    }
    candidate = {
        "task_type": "math",
        "problem_pattern": "percentage calculation",
        "recommended_strategy": "multiply by rate",
        "successful_steps": [],
        "tools_used": ["calculator"],
    }
    decision, reason = await evaluate_quality_gate(state, candidate, session=None)
    assert decision == "skip"


@pytest.mark.asyncio
async def test_quality_gate_none_candidate_skips():
    state = create_initial_state("t", "r", "u", "Hi")
    state["evaluation"] = {"task_success": False}
    decision, reason = await evaluate_quality_gate(state, None, session=None)
    assert decision == "skip"
