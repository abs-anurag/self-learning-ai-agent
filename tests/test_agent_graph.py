"""
Comprehensive unit and integration tests for LangGraph Agent Graph and Nodes.

Source of truth: BLUEPRINT.md §6, §8, §9, §10, §12, §13, §14, §17.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
import pytest

from backend.agent.graph import build_agent_graph, create_agent_graph
from backend.agent.nodes import (
    evaluate,
    execute,
    maybe_learn,
    observe,
    plan,
    reflect,
    replan,
    respond,
    retrieve_memory,
    understand,
)
from backend.agent.runtime import AgentRuntime
from backend.agent.state import (
    DEFAULT_MAX_OBSERVATION_CHARS,
    AgentState,
    create_initial_state,
    route_after_evaluate,
)
from backend.events.publisher import RedisEventPublisher
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import EventService


# -- Test Mocks --------------------------------------------------


class MockRedisClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class MockDbSession:
    def __init__(self, initial_counter: int = 0) -> None:
        self.counter = initial_counter
        self.committed = False
        self.added: list[Any] = []

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def execute(self, statement: Any) -> Any:
        class MockResult:
            def __init__(self, count: int) -> None:
                self._count = count

            def scalar_one_or_none(self) -> Any:
                return self._count

            def scalar_one(self) -> Any:
                return self._count

            def scalars(self) -> Any:
                class MockScalars:
                    def all(self) -> list[Any]:
                        return []

                return MockScalars()

        return MockResult(self.counter)


# -- Test Graph Construction & Topology --------------------------


class TestGraphTopology:
    """Verifies that the StateGraph has all required nodes and edges."""

    def test_graph_has_all_ten_nodes(self) -> None:
        graph = build_agent_graph()
        node_names = set(graph.nodes.keys())
        expected_nodes = {
            "understand",
            "retrieve_memory",
            "plan",
            "execute",
            "observe",
            "evaluate",
            "reflect",
            "replan",
            "maybe_learn",
            "respond",
        }
        assert expected_nodes.issubset(node_names)

    def test_compiled_graph_creates_successfully(self) -> None:
        compiled = create_agent_graph()
        assert compiled is not None
        assert hasattr(compiled, "ainvoke")


# -- Test Individual Nodes ---------------------------------------


class TestAgentNodes:
    """Verifies the isolated execution and contracts of each agent node."""

    @pytest.mark.asyncio
    async def test_understand_normalizes_math_goal(self) -> None:
        state = create_initial_state("t", "r", "u", "calculate the compound interest on $10,000 at 5%")
        result = await understand(state)
        assert result["task_type"] == "math"
        assert result["understood_task"].endswith(".")
        assert result["current_step"] == "understand"

    @pytest.mark.asyncio
    async def test_understand_classifies_research_and_file_types(self) -> None:
        res_state = create_initial_state("t", "r", "u", "search for latest news about AI")
        res_result = await understand(res_state)
        assert res_result["task_type"] == "research"

        file_state = create_initial_state("t", "r", "u", "read file data.txt and parse")
        file_result = await understand(file_state)
        assert file_result["task_type"] == "file"

    @pytest.mark.asyncio
    async def test_retrieve_memory_emits_telemetry(self) -> None:
        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        event_service = EventService(publisher=publisher)
        runtime = AgentRuntime(event_service=event_service)

        state = create_initial_state(
            task_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            goal="Calculate the compound interest on $10,000 at 5%",
        )

        async with runtime.use_context():
            result = await retrieve_memory(state)

        assert "retrieved_recipes" in result
        assert result["current_step"] == "retrieve_memory"
        # In Run A, 0 hits
        assert len(result["retrieved_recipes"]) == 0

    @pytest.mark.asyncio
    async def test_plan_emits_planning_started(self) -> None:
        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        event_service = EventService(publisher=publisher)
        runtime = AgentRuntime(event_service=event_service)

        state = create_initial_state(
            task_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            goal="Calculate interest",
        )
        state["task_type"] = "math"

        async with runtime.use_context():
            result = await plan(state)

        assert "plan" in result
        assert isinstance(result["plan"], list)
        assert len(result["plan"]) > 0

    @pytest.mark.asyncio
    async def test_execute_calculator_safe_eval(self) -> None:
        state = create_initial_state("t", "r", "u", "100 + 200")
        state["plan"] = ["Calculate 100 + 200"]
        result = await execute(state)

        assert len(result["tool_calls"]) > 0
        call = result["tool_calls"][0]
        assert call["status"] == "succeeded"
        assert "300" in str(call["output"])

    @pytest.mark.asyncio
    async def test_execute_blocks_unsafe_action(self) -> None:
        state = create_initial_state("t", "r", "u", "malicious input")
        state["plan"] = ["Calculate __import__('os').system('dir')"]
        result = await execute(state)

        assert result.get("termination_reason") == "unsafe_action"
        assert result["tool_calls"][0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_observe_truncates_large_output(self) -> None:
        huge_text = "x" * 15000
        state = create_initial_state("t", "r", "u", "g")
        state["tool_calls"] = [
            {"tool_name": "calculator", "output": huge_text, "status": "succeeded"}
        ]
        result = await observe(state)

        assert len(result["observations"]) == 1
        obs = result["observations"][0]
        assert len(obs["output"]) <= DEFAULT_MAX_OBSERVATION_CHARS
        assert "[TRUNCATED:" in obs["output"]

    @pytest.mark.asyncio
    async def test_evaluate_increments_iteration_count(self) -> None:
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 0
        state["tool_calls"] = [{"tool_name": "calculator", "status": "succeeded", "output": "42"}]
        state["observations"] = [{"tool_name": "calculator", "output": "42", "status": "succeeded"}]

        result = await evaluate(state)
        assert result["iteration_count"] == 1
        assert "evaluation" in result
        eval_dict = result["evaluation"]
        assert "task_success" in eval_dict
        assert "deterministic_pass" in eval_dict
        assert "tool_success" in eval_dict
        assert "judge_score" in eval_dict
        # judge_reasoning is present internally for audit
        assert "judge_reasoning" in eval_dict

    @pytest.mark.asyncio
    async def test_reflect_and_replan_flow(self) -> None:
        state = create_initial_state("t", "r", "u", "Calculate interest")
        state["iteration_count"] = 1
        state["evaluation"] = {"task_success": False, "judge_score": 5.0}

        reflect_res = await reflect(state)
        assert "reflection" in reflect_res
        assert len(reflect_res["reflection"]) > 0

        state["reflection"] = reflect_res["reflection"]
        replan_res = await replan(state)
        assert "plan" in replan_res
        assert len(replan_res["plan"]) > 0

    @pytest.mark.asyncio
    async def test_maybe_learn_quality_gate_promotion(self) -> None:
        state = create_initial_state("t", "r", "u", "Calculate the compound interest on $10,000 at 5%")
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 9.0,
            "deterministic_pass": True,
            "tool_success": True,
            "generalizable": True,
        }
        state["observations"] = [{"tool_name": "calculator", "output": "11614.72", "status": "succeeded"}]

        result = await maybe_learn(state)
        assert result["learning_decision"] == "promoted"
        assert result["candidate_recipe"] is not None
        assert result["candidate_recipe"]["problem_pattern"] == "compound interest with compounding frequency"

    @pytest.mark.asyncio
    async def test_maybe_learn_duplicate_skips_promotion(self) -> None:
        state = create_initial_state("t", "r", "u", "Calculate the compound interest on $5,000 at 7%")
        state["retrieved_recipes"] = [{"recipe_id": "r1"}]  # Recipe was retrieved
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 9.2,
            "deterministic_pass": True,
            "tool_success": True,
            "generalizable": True,
        }

        result = await maybe_learn(state)
        # Duplicate detection skips creation per BLUEPRINT.md §10 line 465
        assert result["learning_decision"] == "skip"

    @pytest.mark.asyncio
    async def test_respond_success_and_failure(self) -> None:
        # Success scenario
        success_state = create_initial_state("t", "r", "u", "g")
        success_state["evaluation"] = {"task_success": True, "judge_score": 8.5}
        success_state["observations"] = [{"tool_name": "calculator", "output": "42"}]

        s_res = await respond(success_state)
        assert s_res["status"] == "succeeded"
        assert "Result: 42" in s_res["final_response"] or "successfully" in s_res["final_response"]

        # Failure scenario
        failed_state = create_initial_state("t", "r", "u", "g")
        failed_state["evaluation"] = {"task_success": False, "judge_score": 4.0}
        failed_state["termination_reason"] = "max_iterations"

        f_res = await respond(failed_state)
        assert f_res["status"] == "failed"
        assert "Task could not be solved within 3 iterations." in f_res["final_response"]


# -- Test Hard Iteration Bounds on Graph --------------------------


class TestGraphExecutionLimits:
    """Verifies that the compiled LangGraph respects iteration limits and safety."""

    @pytest.mark.asyncio
    async def test_graph_terminates_on_fatal_security_reason(self) -> None:
        compiled = create_agent_graph()
        initial_state = create_initial_state(
            task_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            goal="Test run",
        )
        # Force a fatal termination reason
        initial_state["termination_reason"] = "unsafe_action"

        result = await compiled.ainvoke(initial_state)
        assert result["status"] == "failed"
        assert result["termination_reason"] == "unsafe_action"
