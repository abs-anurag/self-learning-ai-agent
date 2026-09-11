"""
Live Anthropic LLM provider calling the Anthropic API.

Source of truth: BLUEPRINT.md §15, §17, §23.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from backend.agent.providers.base import LLMProvider
from backend.agent.state import AgentState
from backend.agent.prompts import (
    SYSTEM_JUDGE_PROMPT,
    SYSTEM_PLANNING_PROMPT,
    SYSTEM_REFLECTION_PROMPT,
    build_judge_prompt,
    build_planning_prompt,
    build_reflection_prompt,
)
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """
    Live provider calling Anthropic API.
    Source: BLUEPRINT.md §15.
    Used when EXECUTION_MODE=live.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.ANTHROPIC_API_KEY.get_secret_value()
        self._client: Optional[Any] = None

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic

                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except ImportError as exc:
                raise RuntimeError("Anthropic provider is unavailable.") from exc
        return self._client

    async def _request(self, *, system: str, prompt: str) -> dict[str, Any]:
        client = self._get_client()
        response = await client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=1200,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(getattr(block, "text", "") for block in response.content)
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Anthropic provider returned invalid structured output.") from exc
        if not isinstance(value, dict):
            raise RuntimeError("Anthropic provider returned an invalid response shape.")
        return value

    async def plan(self, state: AgentState) -> dict[str, Any]:
        """Call Claude to generate initial plan."""
        return await self._request(
            system=SYSTEM_PLANNING_PROMPT + " Return JSON with a string array field named plan.",
            prompt=build_planning_prompt(
                state.get("goal", ""), state.get("understood_task", ""),
                state.get("task_type", ""), state.get("retrieved_recipes", []),
            ),
        )

    async def reflect(self, state: AgentState) -> dict[str, Any]:
        """Call Claude to reflect on execution failure."""
        return await self._request(
            system=SYSTEM_REFLECTION_PROMPT + " Return JSON with a string field named reflection.",
            prompt=build_reflection_prompt(
                state.get("goal", ""), state.get("plan", []),
                state.get("observations", []), state.get("evaluation", {}),
                state.get("termination_reason"),
            ),
        )

    async def judge(self, state: AgentState) -> dict[str, Any]:
        """Call Claude as judge to score execution."""
        return await self._request(
            system=SYSTEM_JUDGE_PROMPT + (
                " Return JSON with judge_score, deterministic_pass, tool_success, "
                "generalizable, and private judge_reasoning fields."
            ),
            prompt=build_judge_prompt(
                state.get("goal", ""), state.get("plan", []),
                state.get("observations", []), state.get("final_response", ""),
            ),
        )
