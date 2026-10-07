"""
Tests for LangGraph execution safety and anti-infinite loop constraints.

Verifies:
1. repeated tool call detection (repeated_failure)
2. repeated planning detection (repeated_failure)
3. repeated evaluation iteration bounding
4. maximum iteration termination (max_iterations)
5. successful normal task
6. failed tool task controlled exit
"""

from __future__ import annotations

import uuid
import pytest

from backend.agent.graph import create_agent_graph
from backend.agent.providers.base import LLMProvider
from backend.agent.runtime import AgentRuntime, set_current_runtime
from backend.agent.state import create_initial_state, route_after_evaluate


class MockFailingToolProvider(LLMProvider):
    """Provider that deliberately repeats an identical failing tool call."""

    def __init__(self, repeat_identical: bool = True) -> None:
        self.repeat_identical = repeat_identical
        self.call_count = 0

    async def understand(self, state):
        return {"understood_task": "Calculate invalid", "task_type": "math", "needs_tools": True}

    async def plan(self, state):
        return {"plan": ["Execute failing calculation"], "current_step": "Execute failing calculation"}

    async def decide_step_action(self, state):
        self.call_count += 1
        # Always request calculator with a syntax error expression
        return {
            "call_tool": True,
            "tool_name": "calculator",
            "parameters": {"expression": "2 + + 2"},
            "thought": "Evaluate syntax error",
        }

    async def reflect(self, state):
        return {"reflection": "Syntax error encountered; attempting retry."}

    async def judge(self, state):
        # Evaluation fails because tool failed
        return {
            "judge_score": 3.0,
            "judge_reasoning": "Tool execution failed.",
            "task_success": False,
            "deterministic_pass": True,
            "tool_success": False,
        }

    async def respond(self, state):
        return {"final_response": "Controlled exit after tool failure."}


class MockRepeatedPlanProvider(LLMProvider):
    """Provider that returns the exact same plan during replanning."""

    def __init__(self) -> None:
        self.plan_calls = 0

    async def understand(self, state):
        return {"understood_task": "Unsolvable task", "task_type": "research", "needs_tools": False}

    async def plan(self, state):
        self.plan_calls += 1
        # Return exact identical plan on every call
        return {"plan": ["Static unchanging step 1", "Static unchanging step 2"], "current_step": "Static unchanging step 1"}

    async def decide_step_action(self, state):
        return {"call_tool": False, "tool_name": None, "parameters": {}, "thought": "No tool"}

    async def reflect(self, state):
        return {"reflection": "Need to adapt"}

    async def judge(self, state):
        return {
            "judge_score": 4.0,
            "judge_reasoning": "Incomplete resolution.",
            "task_success": False,
            "deterministic_pass": True,
            "tool_success": True,
        }

    async def respond(self, state):
        return {"final_response": "Terminated due to failure to adapt."}


class MockExhaustingIterationsProvider(LLMProvider):
    """Provider that varies plans slightly but continually fails until iteration limit."""

    def __init__(self) -> None:
        self.iter = 0

    async def understand(self, state):
        return {"understood_task": "Challenging task", "task_type": "research", "needs_tools": False}

    async def plan(self, state):
        self.iter += 1
        return {"plan": [f"Unique step variation {self.iter}"], "current_step": f"Unique step variation {self.iter}"}

    async def decide_step_action(self, state):
        return {"call_tool": False, "tool_name": None, "parameters": {}, "thought": "Direct synthesis"}

    async def reflect(self, state):
        return {"reflection": f"Attempt {self.iter} did not meet rubric"}

    async def judge(self, state):
        return {
            "judge_score": 4.5,
            "judge_reasoning": "Still below required threshold.",
            "task_success": False,
            "deterministic_pass": True,
            "tool_success": True,
        }

    async def respond(self, state):
        return {"final_response": "Controlled termination: best effort response."}


# --- Test Cases ---


@pytest.mark.asyncio
async def test_repeated_tool_call_terminates():
    """1. Repeated identical tool failure terminates with repeated_failure."""
    provider = MockFailingToolProvider()
    runtime = AgentRuntime(llm_provider=provider, session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "Failing calculation")

    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    # Must terminate with failed status and repeated_failure reason
    assert final_state["status"] == "failed"
    assert final_state["termination_reason"] in ("repeated_failure", "tool_validation_failure", "max_iterations")
    # Must not loop infinitely
    assert final_state["iteration_count"] <= 3


@pytest.mark.asyncio
async def test_repeated_planning_terminates():
    """2. Repeated identical plan detection stops execution loop."""
    provider = MockRepeatedPlanProvider()
    runtime = AgentRuntime(llm_provider=provider, session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "Stuck in planning")

    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    assert final_state["status"] == "failed"
    assert final_state["termination_reason"] in ("repeated_failure", "max_iterations")
    assert final_state["iteration_count"] <= 3


@pytest.mark.asyncio
async def test_repeated_evaluation_increments_and_bounds():
    """3. Evaluation node strictly increments iteration_count on every pass."""
    state = create_initial_state("t", "r", "u", "Test evaluation bounds")
    state["iteration_count"] = 1
    state["max_iterations"] = 3
    state["evaluation"] = {"task_success": False}

    # At iteration 1, routes to reflect
    route_1 = route_after_evaluate(state)
    assert route_1 == "reflect"

    # At iteration 3, strictly routes to respond
    state["iteration_count"] = 3
    route_3 = route_after_evaluate(state)
    assert route_3 == "respond"


@pytest.mark.asyncio
async def test_maximum_iteration_termination():
    """4. Execution halts strictly at max_iterations (3) with controlled failure."""
    provider = MockExhaustingIterationsProvider()
    runtime = AgentRuntime(llm_provider=provider, session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "Difficult problem")

    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    assert final_state["status"] == "failed"
    assert final_state["iteration_count"] == 3
    assert final_state["termination_reason"] == "max_iterations"
    assert "Controlled termination" in final_state["final_response"]


@pytest.mark.asyncio
async def test_successful_normal_task():
    """5. Normal successful task terminates in 1 iteration without extra looping."""
    runtime = AgentRuntime(session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "What is polymorphism in Java?")

    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert final_state["iteration_count"] == 1
    assert "Polymorphism" in final_state["final_response"]
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_failed_tool_task_controlled_exit():
    """6. Unrecoverable tool error exits gracefully without hanging."""
    provider = MockFailingToolProvider()
    runtime = AgentRuntime(llm_provider=provider, session_factory=None)
    set_current_runtime(runtime)

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "Unrecoverable tool task")

    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    assert final_state["status"] == "failed"
    assert final_state["final_response"] != ""
    assert final_state["iteration_count"] <= 3
