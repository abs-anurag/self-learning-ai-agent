"""
Unit tests for Google Gemini LLM provider, configuration, and credential safety.

Verifies:
1. Provider selection: LLM_PROVIDER=gemini and EXECUTION_MODE=live select GeminiProvider.
2. Missing or placeholder GEMINI_API_KEY raises explicit controlled RuntimeError.
3. No silent fallback to FixtureProvider in live mode.
4. Model configuration defaults to GEMINI_MODEL (gemini-3.8-flash).
5. Mocked Gemini API execution successfully handles understand/plan/dispatch/respond.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.providers.fixture import FixtureProvider
from backend.agent.providers.gemini import GeminiProvider
from backend.agent.runtime import get_llm_provider
from backend.agent.state import create_initial_state
from backend.core.config import ExecutionMode, LLMProviderName, settings


def test_gemini_provider_selection():
    """Gemini provider is selected via LLM_PROVIDER=gemini or EXECUTION_MODE=live."""
    provider = get_llm_provider(provider=LLMProviderName.GEMINI)
    assert isinstance(provider, GeminiProvider)

    provider_live = get_llm_provider(mode=ExecutionMode.LIVE)
    assert isinstance(provider_live, GeminiProvider)

    # Demo/fixture remains accessible
    provider_demo = get_llm_provider(mode=ExecutionMode.DEMO)
    assert isinstance(provider_demo, FixtureProvider)


def test_gemini_missing_or_placeholder_key_raises_controlled_error():
    """Missing or placeholder key raises explicit controlled RuntimeError."""
    # Placeholder key
    provider_placeholder = GeminiProvider(api_key="gemini-placeholder-key-do-not-commit")
    with pytest.raises(RuntimeError) as exc_info:
        provider_placeholder.validate_credentials()
    assert "GEMINI_API_KEY is not configured or is a placeholder" in str(exc_info.value)

    # Empty key
    provider_empty = GeminiProvider(api_key="")
    with pytest.raises(RuntimeError) as exc_info2:
        provider_empty.validate_credentials()
    assert "GEMINI_API_KEY is not configured or is a placeholder" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_gemini_execution_without_credentials_does_not_silently_fallback():
    """Calling LLM methods without credentials must fail with RuntimeError, not pretend."""
    provider = GeminiProvider(api_key="gemini-placeholder-key-do-not-commit")
    state = create_initial_state("task-1", "run-1", "user-1", "What is polymorphism?")

    with pytest.raises(RuntimeError) as exc_info:
        await provider.understand(state)
    assert "GEMINI_API_KEY is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_gemini_live_mocked_success():
    """Valid credentials and mock response return real model output."""
    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-3.8-flash",
    )
    assert provider.model == "gemini-3.8-flash"

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '{"understood_task": "Explain polymorphism", "task_type": "research", "needs_tools": false}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    provider._client = mock_client

    state = create_initial_state("task-1", "run-1", "user-1", "What is polymorphism in Java?")
    result = await provider.understand(state)

    assert result["understood_task"] == "Explain polymorphism"
    assert result["task_type"] == "research"
    assert result["needs_tools"] is False


@pytest.mark.asyncio
async def test_gemini_live_mocked_respond():
    """Mocked Gemini response returns structured text directly."""
    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-3.8-flash",
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Polymorphism in Java allows objects to be treated as instances of their parent class."
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)
    provider._client = mock_client

    state = create_initial_state("task-1", "run-1", "user-1", "What is polymorphism in Java?")
    result = await provider.respond(state)

    assert "Polymorphism in Java" in result["final_response"]


@pytest.mark.asyncio
async def test_gemini_dynamic_tool_selection():
    """Gemini properly generates calculator tool dispatch and direct dispatch."""
    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-3.8-flash",
    )
    mock_client = MagicMock()

    # 1. Math query dispatches calculator tool
    mock_resp_math = MagicMock()
    mock_resp_math.text = '{"call_tool": true, "tool_name": "calculator", "parameters": {"expression": "125 * 36"}, "thought": "Evaluate multiplication"}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp_math)
    provider._client = mock_client

    state_math = create_initial_state("task-1", "run-1", "user-1", "Calculate 125 * 36")
    action_math = await provider.decide_step_action(state_math)
    assert action_math["call_tool"] is True
    assert action_math["tool_name"] == "calculator"
    assert action_math["parameters"]["expression"] == "125 * 36"

    # 2. General query dispatches direct answer without tools
    mock_resp_direct = MagicMock()
    mock_resp_direct.text = '{"call_tool": false, "tool_name": null, "parameters": {}, "thought": "Direct explanation"}'
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp_direct)

    state_direct = create_initial_state("task-2", "run-2", "user-2", "What is polymorphism in Java?")
    action_direct = await provider.decide_step_action(state_direct)
    assert action_direct["call_tool"] is False
    assert action_direct["tool_name"] is None


@pytest.mark.asyncio
async def test_gemini_full_graph_integration():
    """Verify GeminiProvider integrates end-to-end with LangGraph agent graph."""
    from backend.agent.graph import create_agent_graph
    from backend.agent.runtime import AgentRuntime, set_current_runtime

    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-3.8-flash",
    )

    mock_client = MagicMock()
    # Sequence of responses for understand, plan, decide_step_action, judge, respond
    understand_resp = MagicMock(text='{"understood_task": "Explain TCP vs UDP", "task_type": "research", "needs_tools": false}')
    plan_resp = MagicMock(text='{"plan": ["Compare TCP and UDP protocols thoroughly"], "direct_answer_possible": true}')
    dispatch_resp = MagicMock(text='{"call_tool": false, "tool_name": null, "parameters": {}, "thought": "Synthesizing answer"}')
    judge_resp = MagicMock(text='{"judge_score": 9.5, "judge_reasoning": "Comprehensive comparison", "task_success": true, "deterministic_pass": true, "tool_success": true}')
    respond_resp = MagicMock(text="TCP is connection-oriented and reliable, while UDP is connectionless and fast.")

    mock_client.aio.models.generate_content = AsyncMock(side_effect=[
        understand_resp,
        plan_resp,
        dispatch_resp,
        judge_resp,
        respond_resp,
    ])
    provider._client = mock_client

    runtime = AgentRuntime(llm_provider=provider, session_factory=None)
    set_current_runtime(runtime)

    import uuid

    task_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    state = create_initial_state(task_id, run_id, user_id, "What is the difference between TCP and UDP?")
    app = create_agent_graph()
    final_state = await app.ainvoke(state)

    assert final_state["status"] == "succeeded"
    assert "TCP is connection-oriented" in final_state["final_response"]
    assert len(final_state["tool_calls"]) == 0
    assert final_state["evaluation"]["task_success"] is True


@pytest.mark.asyncio
async def test_gemini_fallback_ordering_on_429() -> None:
    """Verify GeminiProvider falls back through model candidates on 429 and caches active model."""
    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-3.8-flash",
        fallback_models=["gemini-3.5-flash", "gemini-flash-lite-latest"],
    )

    call_models: list[str] = []

    async def mock_generate_content(*args: Any, **kwargs: Any) -> Any:
        m = kwargs.get("model")
        call_models.append(m)
        if m == "gemini-3.8-flash":
            raise RuntimeError("429 Resource has been exhausted (quota exceeded)")
        elif m == "gemini-3.5-flash":
            raise RuntimeError("429 Too Many Requests")
        elif m == "gemini-flash-lite-latest":
            resp = MagicMock()
            resp.text = "Success from fallback"
            return resp
        raise RuntimeError(f"Unexpected model: {m}")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)
    provider._client = mock_client

    result = await provider._call_gemini("Test prompt")
    assert result == "Success from fallback"
    assert call_models == ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-flash-lite-latest"]
    assert provider._active_model == "gemini-flash-lite-latest"

    # Subsequent call reuses the active model directly
    call_models.clear()
    result2 = await provider._call_gemini("Second prompt")
    assert result2 == "Success from fallback"
    assert call_models == ["gemini-flash-lite-latest"]


@pytest.mark.asyncio
async def test_gemini_fallback_on_404_not_found() -> None:
    """Verify GeminiProvider falls back when a model is deprecated/not found."""
    provider = GeminiProvider(
        api_key="AIzaSyMockedValidGeminiKey39CharactersLong",
        model="gemini-deprecated-model",
        fallback_models=["gemini-flash-lite-latest"],
    )

    call_models: list[str] = []

    async def mock_generate_content(*args: Any, **kwargs: Any) -> Any:
        m = kwargs.get("model")
        call_models.append(m)
        if m == "gemini-deprecated-model":
            raise RuntimeError("404 NOT_FOUND. Model is no longer available.")
        elif m == "gemini-flash-lite-latest":
            resp = MagicMock()
            resp.text = "Success after 404"
            return resp
        raise RuntimeError(f"Unexpected model: {m}")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=mock_generate_content)
    provider._client = mock_client

    result = await provider._call_gemini("Test prompt")
    assert result == "Success after 404"
    assert call_models == ["gemini-deprecated-model", "gemini-flash-lite-latest"]
    assert provider._active_model == "gemini-flash-lite-latest"

