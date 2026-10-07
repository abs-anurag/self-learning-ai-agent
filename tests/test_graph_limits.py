"""
Unit tests for AgentState, Graph Limits, Routing Logic, and Agent Runtime.

Source of truth: BLUEPRINT.md §2, §8, §9, §14, §15, §17.

Verifies:
1. AgentState creation, required fields, and safe defaults.
2. Status vocabulary enforcement: pending, running, succeeded, failed; completed rejected.
3. Telemetry security: prohibited keys stripped, secrets redacted, observations truncated.
4. Routing logic (route_after_evaluate):
   - task_success=True -> maybe_learn
   - iteration_count >= max_iterations (3) -> respond
   - Terminal failure reasons -> respond
   - Retriable failure with iteration_count < 3 -> reflect
5. Hard iteration limit (max_iterations = 3).
6. LLM provider selection (demo -> FixtureProvider, live -> AnthropicProvider).
7. AgentRuntime context, thread config (thread_id = run_id), and event emission.
8. Checkpointer engine lifecycle (create and dispose).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
import pytest

from backend.agent.providers import (
    AnthropicProvider,
    FixtureProvider,
    LLMProvider,
)
from backend.agent.runtime import (
    AgentRuntime,
    get_llm_provider,
)
from backend.agent.state import (
    TERMINAL_REASONS,
    VALID_STATUSES,
    AgentState,
    create_initial_state,
    route_after_evaluate,
    sanitize_state_update,
    truncate_observation,
    validate_agent_state,
)
from backend.core.config import ExecutionMode
from backend.events.publisher import RedisEventPublisher
from backend.events.schema import EventType
from backend.events.service import EventService


# -- Mock Test Doubles for Redis and DB --------------------------


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
        elif "update" in stmt_str and "sequence_counter" in stmt_str:
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

    async def __aenter__(self) -> MockDbSession:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()


# -- Test AgentState Creation & Defaults -------------------------


class TestAgentStateCreationAndDefaults:
    """BLUEPRINT.md §9: AgentState typing, required fields, and defaults."""

    def test_create_initial_state_has_all_twenty_fields(self) -> None:
        task_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        goal = "Calculate compound interest"

        state = create_initial_state(task_id, run_id, user_id, goal)

        expected_fields = {
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
        assert set(state.keys()) == expected_fields
        assert len(state) == 21  # 21 fields defined in TypedDict

    def test_default_values_on_initial_state(self) -> None:
        task_id = "task-1"
        run_id = "run-1"
        user_id = "user-1"
        goal = "Test goal"

        state = create_initial_state(task_id, run_id, user_id, goal)

        assert state["task_id"] == "task-1"
        assert state["run_id"] == "run-1"
        assert state["user_id"] == "user-1"
        assert state["goal"] == "Test goal"
        assert state["understood_task"] == ""
        assert state["task_type"] == ""
        assert state["retrieved_recipes"] == []
        assert state["plan"] == []
        assert state["current_step"] == ""
        assert state["tool_calls"] == []
        assert state["observations"] == []
        assert state["evaluation"] == {}
        assert state["reflection"] == ""
        assert state["candidate_recipe"] is None
        assert state["learning_decision"] == ""
        assert state["final_response"] == ""
        assert state["status"] == "running"
        assert state["termination_reason"] is None
        assert state["iteration_count"] == 0
        assert state["max_iterations"] == 3
        assert state["error"] is None

    def test_invalid_identifiers_rejected(self) -> None:
        with pytest.raises(ValueError):
            create_initial_state("", "run-1", "user-1", "goal")
        with pytest.raises(ValueError):
            create_initial_state("task-1", "", "user-1", "goal")
        with pytest.raises(ValueError):
            create_initial_state("task-1", "run-1", "", "goal")
        with pytest.raises(ValueError):
            create_initial_state("task-1", "run-1", "user-1", "")


# -- Test Status Vocabulary & Validation -------------------------


class TestStatusVocabularyAndValidation:
    """BLUEPRINT.md §1, §9, Appendix B: Strict status vocabulary."""

    @pytest.mark.parametrize("valid_status", ["pending", "running", "succeeded", "failed"])
    def test_valid_statuses_accepted(self, valid_status: str) -> None:
        state = create_initial_state("t", "r", "u", "g", status=valid_status)
        assert state["status"] == valid_status
        validate_agent_state(state)

    def test_completed_is_strictly_forbidden(self) -> None:
        with pytest.raises(ValueError) as exc:
            create_initial_state("t", "r", "u", "g", status="completed")
        assert "completed" in str(exc.value).lower()

        state = create_initial_state("t", "r", "u", "g")
        state["status"] = "completed"
        with pytest.raises(ValueError) as exc:
            validate_agent_state(state)
        assert "completed" in str(exc.value).lower()

    def test_invalid_task_type_rejected(self) -> None:
        state = create_initial_state("t", "r", "u", "g")
        state["task_type"] = "invalid_category"
        with pytest.raises(ValueError) as exc:
            validate_agent_state(state)
        assert "task_type" in str(exc.value)

    def test_invalid_learning_decision_rejected(self) -> None:
        state = create_initial_state("t", "r", "u", "g")
        state["learning_decision"] = "unsupported_decision"
        with pytest.raises(ValueError) as exc:
            validate_agent_state(state)
        assert "learning_decision" in str(exc.value)

    def test_invalid_iteration_count_rejected(self) -> None:
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = -1
        with pytest.raises(ValueError):
            validate_agent_state(state)


# -- Test Telemetry Security & Sanitization ----------------------


class TestTelemetrySecurityAndSanitization:
    """BLUEPRINT.md §9, §17: Telemetry security, prohibited fields, redaction."""

    def test_sanitize_state_update_strips_prohibited_keys(self) -> None:
        raw_update = {
            "plan": ["step 1"],
            "chain_of_thought": "secret internal reasoning that must not leak",
            "judge_reasoning": "raw evaluation reasoning",
            "prompt": "full system prompt text",
            "api_key": "sk-ant-testkey12345",
            "current_step": "plan",
        }
        cleaned = sanitize_state_update(raw_update)

        assert "chain_of_thought" not in cleaned
        assert "judge_reasoning" not in cleaned
        assert "prompt" not in cleaned
        assert "api_key" not in cleaned
        assert cleaned["plan"] == ["step 1"]
        assert cleaned["current_step"] == "plan"

    def test_sanitize_state_update_redacts_tokens(self) -> None:
        raw_update = {
            "error": "Failed with key sk-ant-secrettoken1234567890abcdef",
        }
        cleaned = sanitize_state_update(raw_update)
        assert "sk-ant-" not in cleaned["error"]
        assert "[REDACTED]" in cleaned["error"]

    def test_sanitize_state_update_rejects_completed_status(self) -> None:
        with pytest.raises(ValueError) as exc:
            sanitize_state_update({"status": "completed"})
        assert "completed" in str(exc.value).lower()

    def test_observation_truncation(self) -> None:
        """BLUEPRINT.md §9: Large tool results are truncated before state assignment."""
        short_text = "Small tool result"
        assert truncate_observation(short_text, max_chars=100) == short_text

        long_text = "A" * 200
        truncated = truncate_observation(long_text, max_chars=100)
        assert len(truncated) <= 100
        assert "[TRUNCATED:" in truncated


# -- Test Routing Logic & Graph Limits ---------------------------


class TestRoutingLogicAndGraphLimits:
    """BLUEPRINT.md §8: route_after_evaluate conditional edge and iteration limits."""

    def test_success_routes_to_maybe_learn(self) -> None:
        """When evaluation.task_success is True, routes immediately to maybe_learn."""
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 1
        state["evaluation"] = {"task_success": True, "judge_score": 9.0}

        destination = route_after_evaluate(state)
        assert destination == "maybe_learn"

    def test_iteration_limit_boundary_routes_to_respond(self) -> None:
        """After 3 completed iterations (iteration_count >= 3), routes to respond."""
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 3
        state["max_iterations"] = 3
        state["evaluation"] = {"task_success": False, "judge_score": 4.0}

        destination = route_after_evaluate(state)
        assert destination == "respond"

    @pytest.mark.parametrize("terminal_reason", list(TERMINAL_REASONS - {"max_iterations"}))
    def test_terminal_failure_routes_to_respond(self, terminal_reason: str) -> None:
        """Fatal/terminal failure reasons terminate iteration loop and route to respond."""
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 1
        state["max_iterations"] = 3
        state["evaluation"] = {"task_success": False}
        state["termination_reason"] = terminal_reason

        destination = route_after_evaluate(state)
        assert destination == "respond"

    def test_retriable_failure_routes_to_reflect(self) -> None:
        """Retriable failure with iteration_count < max_iterations routes to reflect."""
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 1
        state["max_iterations"] = 3
        state["evaluation"] = {"task_success": False, "judge_score": 5.0}
        state["termination_reason"] = None

        destination = route_after_evaluate(state)
        assert destination == "reflect"

    def test_second_iteration_retriable_routes_to_reflect(self) -> None:
        """At iteration_count = 2, retriable failure still routes to reflect for iteration 3."""
        state = create_initial_state("t", "r", "u", "g")
        state["iteration_count"] = 2
        state["max_iterations"] = 3
        state["evaluation"] = {"task_success": False}

        destination = route_after_evaluate(state)
        assert destination == "reflect"


# -- Test LLM Provider Abstraction -------------------------------


class TestLLMProviders:
    """BLUEPRINT.md §15: LLMProvider abstraction (FixtureProvider vs AnthropicProvider)."""

    def test_get_llm_provider_demo_mode(self) -> None:
        provider = get_llm_provider(mode=ExecutionMode.DEMO)
        assert isinstance(provider, FixtureProvider)

        provider_str = get_llm_provider(mode="demo")
        assert isinstance(provider_str, FixtureProvider)

    def test_get_llm_provider_live_mode(self) -> None:
        from backend.agent.providers.gemini import GeminiProvider
        provider = get_llm_provider(mode=ExecutionMode.LIVE)
        assert isinstance(provider, (GeminiProvider, AnthropicProvider))

    @pytest.mark.asyncio
    async def test_fixture_provider_methods(self) -> None:
        provider = FixtureProvider()
        state = create_initial_state("t", "r", "u", "g")

        plan_res = await provider.plan(state)
        assert "plan" in plan_res
        assert isinstance(plan_res["plan"], list)

        reflect_res = await provider.reflect(state)
        assert "reflection" in reflect_res

        judge_res = await provider.judge(state)
        assert "judge_score" in judge_res
        assert judge_res["task_success"] is True


# -- Test AgentRuntime Context -----------------------------------


class TestAgentRuntime:
    """BLUEPRINT.md §4, §8, §15: AgentRuntime execution context."""

    def test_runtime_initialization_defaults(self) -> None:
        runtime = AgentRuntime()
        assert isinstance(runtime.llm_provider, LLMProvider)
        assert isinstance(runtime.event_service, EventService)

    def test_get_thread_config_matches_run_id(self) -> None:
        """BLUEPRINT.md §8: thread_id = run_id."""
        run_id = uuid.uuid4()
        config = AgentRuntime.get_thread_config(run_id)
        assert config == {"configurable": {"thread_id": str(run_id)}}

    @pytest.mark.asyncio
    async def test_runtime_emit_event_delegates_to_event_service(self) -> None:
        """Telemetry emitted through runtime delegates directly to EventService."""
        redis_client = MockRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        event_service = EventService(publisher=publisher)
        runtime = AgentRuntime(event_service=event_service)

        session = MockDbSession(initial_counter=0)
        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()

        envelope = await runtime.emit_event(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            event_type=EventType.TASK_STARTED,
            session=session,
        )

        assert envelope.sequence == 1
        assert envelope.event_type == EventType.TASK_STARTED
        assert session.committed is True
        assert len(redis_client.published) == 1
        assert redis_client.published[0][0] == f"agent.events.{run_id}"

    @pytest.mark.asyncio
    async def test_checkpointer_context_engine_lifecycle(self) -> None:
        """BLUEPRINT.md §8: Checkpointer engine created and safely disposed per invocation."""
        runtime = AgentRuntime()
        async with runtime.checkpointer_context() as saver:
            # saver is instantiated or None (if package not installed)
            assert saver is None or hasattr(saver, "get_tuple")
        # Exiting context manager disposes engine cleanly without errors
