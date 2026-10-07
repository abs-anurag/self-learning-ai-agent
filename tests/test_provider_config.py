"""
Tests for LLM provider configuration, selection, and credential safety.

Verifies:
1. Provider selection via LLM_PROVIDER and EXECUTION_MODE.
2. Missing or placeholder ANTHROPIC_API_KEY produces a clear, controlled RuntimeError
   rather than silently pretending to be a real LLM.
3. AnthropicProvider model configuration defaults to ANTHROPIC_MODEL.
4. FixtureProvider remains accessible as explicit demo/fallback mode.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.providers.anthropic import AnthropicProvider
from backend.agent.providers.fixture import FixtureProvider
from backend.agent.runtime import get_llm_provider
from backend.agent.state import create_initial_state
from backend.core.config import ExecutionMode, LLMProviderName, settings


def test_provider_selection_demo_mode():
    """Demo mode selects FixtureProvider."""
    provider = get_llm_provider(mode=ExecutionMode.DEMO)
    assert isinstance(provider, FixtureProvider)

    provider2 = get_llm_provider(provider=LLMProviderName.FIXTURE)
    assert isinstance(provider2, FixtureProvider)


def test_provider_selection_live_mode():
    """Live mode defaults to GeminiProvider, or AnthropicProvider when specified."""
    from backend.agent.providers.gemini import GeminiProvider

    provider = get_llm_provider(mode=ExecutionMode.LIVE)
    assert isinstance(provider, GeminiProvider)

    provider2 = get_llm_provider(provider=LLMProviderName.GEMINI)
    assert isinstance(provider2, GeminiProvider)

    provider3 = get_llm_provider(provider=LLMProviderName.ANTHROPIC)
    assert isinstance(provider3, AnthropicProvider)


def test_anthropic_missing_or_placeholder_key_raises_controlled_error():
    """Missing or placeholder key raises explicit controlled RuntimeError."""
    # Placeholder key
    provider_placeholder = AnthropicProvider(api_key="sk-ant-placeholder-key-do-not-commit")
    with pytest.raises(RuntimeError) as exc_info:
        provider_placeholder.validate_credentials()
    assert "ANTHROPIC_API_KEY is not configured or is a placeholder" in str(exc_info.value)

    # Empty key
    provider_empty = AnthropicProvider(api_key="")
    with pytest.raises(RuntimeError) as exc_info2:
        provider_empty.validate_credentials()
    assert "ANTHROPIC_API_KEY is not configured or is a placeholder" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_anthropic_execution_without_credentials_does_not_silently_fallback():
    """Calling LLM methods without credentials must fail with RuntimeError, not pretend."""
    provider = AnthropicProvider(api_key="sk-ant-placeholder-key-do-not-commit")
    state = create_initial_state("task-1", "run-1", "user-1", "What is polymorphism?")

    with pytest.raises(RuntimeError) as exc_info:
        await provider.understand(state)
    assert "ANTHROPIC_API_KEY is not configured" in str(exc_info.value)


@pytest.mark.asyncio
async def test_anthropic_live_mocked_success():
    """Valid credentials and mock response return real model output."""
    provider = AnthropicProvider(
        api_key="sk-ant-api03-mockedvalidkeyovertwentycharacterslong123456",
        model="claude-3-5-sonnet-20241022",
    )
    assert provider.model == "claude-3-5-sonnet-20241022"

    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_content = MagicMock()
    mock_content.text = '{"understood_task": "Explain polymorphism", "task_type": "research", "needs_tools": false}'
    mock_msg.content = [mock_content]
    mock_client.messages.create = AsyncMock(return_value=mock_msg)

    provider._client = mock_client

    state = create_initial_state("task-1", "run-1", "user-1", "What is polymorphism in Java?")
    result = await provider.understand(state)

    assert result["understood_task"] == "Explain polymorphism"
    assert result["task_type"] == "research"
    assert result["needs_tools"] is False
