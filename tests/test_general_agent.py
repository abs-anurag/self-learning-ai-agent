"""
Comprehensive validation tests for the general-purpose METIS AI Agent.

Verifies the 6 mandatory task categories:
1. General knowledge question
2. Conceptual question
3. Programming / code-generation question
4. Calculation question
5. Current-information / web-search question
6. Multi-step question

Confirms:
- The agent is NOT a calculator-only bot.
- Direct answering is used when no tool is needed.
- Tools (calculator, web_search, file_reader) are invoked dynamically only when needed.
"""

from __future__ import annotations

import uuid
import pytest

from backend.agent.graph import create_agent_graph
from backend.agent.runtime import AgentRuntime, set_current_runtime
from backend.agent.state import create_initial_state


@pytest.fixture(autouse=True)
def setup_runtime():
    runtime = AgentRuntime(session_factory=None)
    set_current_runtime(runtime)
    return runtime


@pytest.mark.asyncio
async def test_category_1_general_knowledge():
    """1. General knowledge question answered directly without unnecessary tools."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "What is the capital of France?"

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert "Paris" in final_state["final_response"]
    # No tool was needed for general knowledge
    assert len(final_state["tool_calls"]) == 0
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_category_2_conceptual_question():
    """2. Conceptual question explained thoroughly with no tool required."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "Explain the key differences between TCP and UDP protocols."

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert "TCP" in final_state["final_response"]
    assert "UDP" in final_state["final_response"]
    assert len(final_state["tool_calls"]) == 0
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_category_3_code_generation():
    """3. Programming and code-generation question producing clean code."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "Write a Python function to check whether a string is a palindrome."

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert final_state["task_type"] == "code"
    assert "def is_palindrome" in final_state["final_response"]
    assert "```python" in final_state["final_response"]
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_category_4_calculation():
    """4. Calculation question dynamically invoking the safe calculator tool."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "Calculate 125 * 36"

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert final_state["task_type"] == "math"
    # Calculator was dynamically selected
    assert any(tc.get("tool") == "calculator" for tc in final_state["tool_calls"])
    assert "4,500" in final_state["final_response"] or "4500" in final_state["final_response"]
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_category_5_web_search(monkeypatch):
    """5. Current-information question dynamically invoking web search."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "Search for the latest news on AI agents"

    # Mock web_search execution to simulate live search results
    from backend.tools import registry
    orig_exec = registry.default_tool_registry.execute_tool

    async def mock_search(name, params, timeout=None):
        if name == "web_search":
            return {
                "success": True,
                "tool": "web_search",
                "output": {
                    "results": [
                        {"title": "AI Agents 2026", "url": "https://example.com/ai", "content": "Autonomous agents expand into general task solving."}
                    ],
                    "query": params.get("query", ""),
                    "result_count": 1,
                }
            }
        return await orig_exec(name, params, timeout)

    monkeypatch.setattr(registry.default_tool_registry, "execute_tool", mock_search)

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert any(tc.get("tool") == "web_search" for tc in final_state["tool_calls"])
    assert "AI Agents 2026" in final_state["final_response"]
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_category_6_multi_step_problem():
    """6. Multi-step calculation with formula modeling and verification."""
    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    goal = "Calculate the compound interest on $10,000 at 5% annual rate for 3 years, compounded monthly."

    state = create_initial_state(task_id, run_id, user_id, goal)
    app = create_agent_graph()

    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert final_state["task_type"] == "math"
    assert len(final_state["plan"]) >= 2
    assert any(tc.get("tool") == "calculator" for tc in final_state["tool_calls"])
    assert "1,614" in final_state["final_response"] or "1614" in final_state["final_response"]
    assert final_state["evaluation"]["task_success"] is True
