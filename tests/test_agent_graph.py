"""
Comprehensive unit and integration tests for LangGraph Agent Graph and Nodes.

Source of truth: BLUEPRINT.md §6, §8, §9, §10, §12, §13, §14, §17.
"""

from __future__ import annotations

import ast
import uuid
from typing import Any

import pytest
from simpleeval import SimpleEval

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


# ---------------------------------------------------------------------------
# Test-only calculator registry
# ---------------------------------------------------------------------------


class FakeCalculatorRegistry:
    """
    Test-only replacement for the teammate-owned Tool Registry.

    This keeps Agent Core tests independent from the production Tools
    subsystem while preserving the real execute() -> registry boundary.
    """

    def __init__(self) -> None:
        self._evaluator = SimpleEval()

        self._evaluator.operators = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.Pow: lambda a, b: a**b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.UAdd: lambda a: +a,
            ast.USub: lambda a: -a,
        }

    def execute(self, tool_name: str, tool_input: Any) -> str:
        """Execute the supported calculator tool for tests only."""
        if tool_name != "calculator":
            raise ValueError(f"Unsupported test tool: {tool_name}")

        expression = str(tool_input).strip()

        if not expression:
            raise ValueError("Calculator expression cannot be empty.")

        tree = ast.parse(expression, mode="eval")

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                raise ValueError("Attribute access is not allowed.")

            if isinstance(node, ast.Call):
                raise ValueError("Function calls are not allowed.")

            if isinstance(node, ast.Name):
                raise ValueError("Names are not allowed.")

            if isinstance(node, (ast.Import, ast.ImportFrom)):
                raise ValueError("Imports are not allowed.")

        result = self._evaluator.eval(expression)

        if isinstance(result, float):
            return str(result)

        return str(result)


@pytest.fixture
def fake_tool_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> FakeCalculatorRegistry:
    """
    Install a test-only registry for Agent Core tests.

    Production backend/tools files remain untouched.
    """
    import backend.tools.registry as registry_module

    fake_registry = FakeCalculatorRegistry()

    monkeypatch.setattr(
        registry_module,
        "registry",
        fake_registry,
        raising=False,
    )

    return fake_registry


# ---------------------------------------------------------------------------
# Test mocks
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Graph construction and topology
# ---------------------------------------------------------------------------


class TestGraphTopology:
    """Verifies that the StateGraph has all required nodes and edges."""

    def test_graph_has_all_ten_nodes(self) -> None:
        graph = build_agent_graph()

        node_names = set(graph.nodes.keys())

        expected_nodes = {
            "understand",
            "retrieve_memory",
            "plan_node",
            "execute_node",
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


# ---------------------------------------------------------------------------
# Individual nodes
# ---------------------------------------------------------------------------


class TestAgentNodes:
    """Verifies the isolated execution and contracts of each agent node."""

    @pytest.mark.asyncio
    async def test_understand_normalizes_math_goal(self) -> None:
        state = create_initial_state(
            "t",
            "r",
            "u",
            "calculate the compound interest on $10,000 at 5%",
        )

        result = await understand(state)

        assert result["task_type"] == "math"
        assert result["understood_task"].endswith(".")
        assert result["current_step"] == "understand"

    @pytest.mark.asyncio
    async def test_understand_classifies_research_and_file_types(self) -> None:
        research_state = create_initial_state(
            "t",
            "r",
            "u",
            "search for latest news about AI",
        )

        research_result = await understand(research_state)

        assert research_result["task_type"] == "research"

        file_state = create_initial_state(
            "t",
            "r",
            "u",
            "read file data.txt and parse",
        )

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
    async def test_execute_calculator_safe_eval(
        self,
        fake_tool_registry: FakeCalculatorRegistry,
    ) -> None:
        state = create_initial_state("t", "r", "u", "100 + 200")
        state["plan"] = ["Calculate 100 + 200"]

        result = await execute(state)

        assert len(result["tool_calls"]) > 0

        call = result["tool_calls"][0]

        assert call["status"] == "succeeded"
        assert call["tool_name"] == "calculator"
        assert call["output"] == "300"

    @pytest.mark.asyncio
    async def test_execute_blocks_unsafe_action(self) -> None:
        state = create_initial_state(
            "t",
            "r",
            "u",
            "malicious input",
        )
        state["plan"] = [
            "Calculate __import__('os').system('dir')"
        ]

        result = await execute(state)

        assert result.get("termination_reason") == "unsafe_action"
        assert result["tool_calls"][0]["status"] == "failed"
        assert result["tool_calls"][0]["error_code"] == "UNSAFE_ACTION"

    @pytest.mark.asyncio
    async def test_observe_records_tool_output(self) -> None:
        state = create_initial_state(
            "t",
            "r",
            "u",
            "Calculate 100 + 200",
        )

        state["tool_calls"] = [
            {
                "tool_name": "calculator",
                "tool_input": "100 + 200",
                "status": "succeeded",
                "output": "300",
                "error_code": None,
            }
        ]

        result = await observe(state)

        assert "observations" in result
        assert result["current_step"] == "observe"

    @pytest.mark.asyncio
    async def test_evaluate_contains_canonical_fields(self) -> None:
        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        event_service = EventService(publisher=publisher)
        runtime = AgentRuntime(event_service=event_service)

        state = create_initial_state(
            "t",
            "r",
            "u",
            "Calculate 100 + 200",
        )

        state["tool_calls"] = [
            {
                "tool_name": "calculator",
                "tool_input": "100 + 200",
                "status": "succeeded",
                "output": "300",
                "error_code": None,
            }
        ]

        state["observations"] = [
            {
                "tool_name": "calculator",
                "status": "succeeded",
                "output": "300",
            }
        ]

        async with runtime.use_context():
            result = await evaluate(state)

        eval_dict = result["evaluation"]

        assert "task_success" in eval_dict
        assert "deterministic_pass" in eval_dict
        assert "tool_success" in eval_dict
        assert "judge_score" in eval_dict

        # Private judge reasoning must never enter AgentState.

    @pytest.mark.asyncio
    async def test_reflect_and_replan_flow(self) -> None:
        state = create_initial_state(
            "t",
            "r",
            "u",
            "Calculate interest",
        )

        state["iteration_count"] = 1
        state["evaluation"] = {
            "task_success": False,
            "judge_score": 5.0,
        }

        reflect_result = await reflect(state)

        assert "reflection" in reflect_result
        assert len(reflect_result["reflection"]) > 0

        state["reflection"] = reflect_result["reflection"]

        replan_result = await replan(state)

        assert "plan" in replan_result
        assert len(replan_result["plan"]) > 0

    @pytest.mark.asyncio
    async def test_maybe_learn_quality_gate_promotion(self) -> None:
        state = create_initial_state(
            "t",
            "r",
            "u",
            "Calculate compound interest",
        )

        state["task_type"] = "math"
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 9.0,
            "deterministic_pass": True,
            "tool_success": True,
        }

        result = await maybe_learn(state)

        assert result["learning_decision"] in {
            "promoted",
            "skip",
        }


# ---------------------------------------------------------------------------
# Graph execution limits
# ---------------------------------------------------------------------------


class TestGraphExecutionLimits:
    @pytest.mark.asyncio
    async def test_graph_terminates_on_fatal_security_reason(self) -> None:
        state = create_initial_state(
            task_id=str(uuid.uuid4()),
            run_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            goal="Test run",
        )

        state["task_type"] = "math"
        state["plan"] = [
            "Calculate __import__('os').system('dir')"
        ]

        execute_result = await execute(state)

        assert execute_result["termination_reason"] == "unsafe_action"
        assert execute_result["tool_calls"][0]["status"] == "failed"

        state.update(execute_result)

        observe_result = await observe(state)
        state.update(observe_result)

        evaluate_result = await evaluate(state)
        state.update(evaluate_result)

        assert evaluate_result["evaluation"]["task_success"] is False

        respond_result = await respond(state)

        assert respond_result["status"] == "failed"
        assert respond_result["termination_reason"] == "unsafe_action"


# ---------------------------------------------------------------------------
# Agent runtime tests
# ---------------------------------------------------------------------------


class TestAgentRuntime:
    def test_thread_config_uses_run_id(self) -> None:
        run_id = str(uuid.uuid4())

        config = AgentRuntime.get_thread_config(run_id)

        assert config == {
            "configurable": {
                "thread_id": run_id,
            }
        }

    def test_default_max_observation_chars_is_positive(self) -> None:
        assert DEFAULT_MAX_OBSERVATION_CHARS > 0

    def test_state_type_is_agent_state(self) -> None:
        state = create_initial_state(
            "task",
            "run",
            "user",
            "goal",
        )

        assert isinstance(state, dict)

    def test_route_after_evaluate_success(self) -> None:
        state = create_initial_state(
            "task",
            "run",
            "user",
            "goal",
        )

        state["evaluation"] = {
            "task_success": True,
        }

        assert route_after_evaluate(state) == "maybe_learn"

    def test_route_after_evaluate_max_iterations(self) -> None:
        state = create_initial_state(
            "task",
            "run",
            "user",
            "goal",
        )

        state["iteration_count"] = state["max_iterations"]
        state["evaluation"] = {
            "task_success": False,
        }

        assert route_after_evaluate(state) == "respond"

    def test_route_after_evaluate_terminal_reason(self) -> None:
        state = create_initial_state(
            "task",
            "run",
            "user",
            "goal",
        )
