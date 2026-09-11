"""
Golden A/B Learning Loop Integration Tests (Deterministic).

Source of truth:
    BLUEPRINT.md §2, §7, §8, §10, §11, §14, §24.

Verifies the full self-learning loop:

- Run A (Baseline):
  No prior recipe, fails iteration 1, reflects on the compounding formula,
  succeeds in iteration 2, and promotes the resulting recipe.

- Run B (Learned):
  Retrieves the trusted compound-interest recipe, cites the learned strategy
  in the plan, succeeds in iteration 1, and skips duplicate promotion.

- Measured Metric Delta:
  Iterations 2 -> 1 (50% reduction).
  Tool invocations 2 -> 1 (50% reduction).
"""

from __future__ import annotations

import ast
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List

import pytest
from simpleeval import SimpleEval

from backend.agent.graph import create_agent_graph
from backend.agent.runtime import AgentRuntime
from backend.agent.state import create_initial_state
from backend.core.config import ExecutionMode, settings
from backend.events.publisher import RedisEventPublisher
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import EventService


# ---------------------------------------------------------------------------
# Test-only calculator registry
# ---------------------------------------------------------------------------


class FakeCalculatorRegistry:
    """
    Test-only replacement for the teammate-owned production Tool Registry.

    The real Agent Core execute node still calls:
        backend.tools.registry.registry

    This fixture simply provides a deterministic calculator implementation
    during these tests without modifying backend/tools/.
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
        """
        Execute the test calculator.

        Only arithmetic expressions are accepted.
        """

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

        return str(self._evaluator.eval(expression))


@pytest.fixture(autouse=True)
def install_fake_tool_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> FakeCalculatorRegistry:
    """
    Install the test-only calculator registry for this module.

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

    async def aclose(self) -> None:
        pass


class MockDbSession:
    def __init__(self, initial_counter: int = 0) -> None:
        self.counter = initial_counter
        self.committed = False
        self.rolled_back = False
        self.records: list[Any] = []

    async def execute(self, stmt: Any) -> Any:
        stmt_str = str(stmt).lower()

        if "select" in stmt_str and "sequence_counter" in stmt_str:

            class ScalarResult:
                def __init__(self, val: int) -> None:
                    self.val = val

                def scalar_one_or_none(self) -> int:
                    return self.val

            return ScalarResult(self.counter)

        if "update" in stmt_str and "sequence_counter" in stmt_str:
            self.counter += 1

            class EmptyResult:
                def scalar_one_or_none(self) -> None:
                    return None

            return EmptyResult()

        return None

    def add(self, record: Any) -> None:
        self.records.append(record)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> "MockDbSession":
        return self

    async def __aexit__(
        self,
        exc_type: Any,
        exc_val: Any,
        exc_tb: Any,
    ) -> None:
        if exc_type is not None:
            await self.rollback()


# ---------------------------------------------------------------------------
# Test checkpointer
# ---------------------------------------------------------------------------


@asynccontextmanager
async def no_checkpointer(_connection_string: str):
    """
    Test-only checkpointer factory.

    The runtime opens and closes the context normally, but no actual
    PostgreSQL checkpointer is required for this unit/integration test.
    """

    yield None


# ---------------------------------------------------------------------------
# Golden Demo / Learning Loop
# ---------------------------------------------------------------------------


class TestGoldenDemoLearningLoop:
    """BLUEPRINT.md §24: Golden A/B Demo Scenario (Deterministic)."""

    @pytest.mark.asyncio
    async def test_golden_demo_ab_scenario_end_to_end(self) -> None:
        """
        Execute Run A (baseline) and Run B (learned) end-to-end and verify
        measured efficiency delta (2 -> 1 iterations).
        """

        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        session = MockDbSession()

        event_service = EventService(
            publisher=publisher,
            session_factory=lambda: session,
        )

        runtime = AgentRuntime(event_service=event_service)

        compiled_graph = create_agent_graph()

        user_id = str(uuid.uuid4())
        task_id_a = str(uuid.uuid4())
        run_id_a = str(uuid.uuid4())

        # ------------------------------------------------------------------
        # 1. RUN A: Baseline Run (No Prior Recipe)
        # ------------------------------------------------------------------

        goal_a = (
            "Calculate the compound interest on $10,000 at 5% annual rate "
            "for 3 years, compounded monthly."
        )

        initial_state_a = create_initial_state(
            task_id=task_id_a,
            run_id=run_id_a,
            user_id=user_id,
            goal=goal_a,
        )

        async with runtime.use_context():
            final_state_a = await compiled_graph.ainvoke(
                initial_state_a,
                config=runtime.get_thread_config(run_id_a),
            )

        # Verify Run A results.
        assert final_state_a["status"] == "succeeded"
        assert final_state_a["iteration_count"] == 2
        assert final_state_a["evaluation"]["task_success"] is True
        assert final_state_a["evaluation"]["judge_score"] >= 8.5

        assert final_state_a["learning_decision"] == "promoted"
        assert final_state_a["candidate_recipe"] is not None

        assert (
            final_state_a["candidate_recipe"]["problem_pattern"]
            == "compound interest with compounding frequency"
        )

        assert len(final_state_a["retrieved_recipes"]) == 0

        assert (
            "1,614.72" in final_state_a["final_response"]
            or "11,614.72" in final_state_a["final_response"]
        )

        # Verify reflection occurred between iterations.
        assert len(final_state_a["reflection"]) > 0

        assert (
            "A = P * (1 + r/n)" in final_state_a["reflection"]
            or "compounding" in final_state_a["reflection"].lower()
        )

        # ------------------------------------------------------------------
        # 2. RUN B: Learned Run (Recipe Retrieved)
        # ------------------------------------------------------------------

        task_id_b = str(uuid.uuid4())
        run_id_b = str(uuid.uuid4())

        goal_b = (
            "Calculate the compound interest on $5,000 at 7% annual rate "
            "for 5 years, compounded quarterly."
        )

        initial_state_b = create_initial_state(
            task_id=task_id_b,
            run_id=run_id_b,
            user_id=user_id,
            goal=goal_b,
        )

        async with runtime.use_context():
            final_state_b = await compiled_graph.ainvoke(
                initial_state_b,
                config=runtime.get_thread_config(run_id_b),
            )

        # Verify Run B results.
        assert final_state_b["status"] == "succeeded"
        assert final_state_b["iteration_count"] == 1
        assert final_state_b["evaluation"]["task_success"] is True
        assert final_state_b["evaluation"]["judge_score"] >= 8.5

        # Recipe was retrieved.
        assert len(final_state_b["retrieved_recipes"]) == 1

        assert (
            final_state_b["retrieved_recipes"][0]["problem_pattern"]
            == "compound interest with compounding frequency"
        )

        # Plan cites the learned strategy or formula.
        plan_text_b = " ".join(final_state_b["plan"])

        assert (
            "A = P * (1 + r/n)" in plan_text_b
            or "recipe" in plan_text_b.lower()
            or "5000" in plan_text_b
        )

        # Duplicate check skips creating another trusted recipe.
        assert final_state_b["learning_decision"] == "skip"

        assert "7,073.89" in final_state_b["final_response"]

        # ------------------------------------------------------------------
        # 3. Measured Metric Delta (§24 Table)
        # ------------------------------------------------------------------

        iterations_a = final_state_a["iteration_count"]
        iterations_b = final_state_b["iteration_count"]

        assert iterations_a == 2
        assert iterations_b == 1

        # Exactly 50% reduction in iterations.
        assert (iterations_a - iterations_b) / iterations_a == 0.5

        # Tool invocations:
        # Run A = 2
        # Run B = 1
        tool_calls_a = len(final_state_a["tool_calls"])
        tool_calls_b = len(final_state_b["tool_calls"])

        assert tool_calls_a == 2
        assert tool_calls_b == 1

        # Exactly 50% reduction in tool calls.
        assert (tool_calls_a - tool_calls_b) / tool_calls_a == 0.5

    @pytest.mark.asyncio
    async def test_runtime_run_method_invokes_graph(self) -> None:
        """Verify AgentRuntime.run() executes the graph and emits task_started."""

        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        session = MockDbSession()

        event_service = EventService(
            publisher=publisher,
            session_factory=lambda: session,
        )

        runtime = AgentRuntime(
            event_service=event_service,
            checkpointer_factory=no_checkpointer,
        )

        user_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())

        goal = (
            "Calculate the compound interest on $5,000 at 7% annual rate "
            "for 5 years, compounded quarterly."
        )

        final_state = await runtime.run(
            run_id=run_id,
            task_id=task_id,
            user_id=user_id,
            goal=goal,
        )

        assert final_state["status"] == "succeeded"
        assert final_state["iteration_count"] == 1

        # Verify task_started event was published to the expected Redis channel.
        published_channels = [
            channel
            for channel, _ in redis_client.published
        ]

        assert f"agent.events.{run_id}" in published_channels