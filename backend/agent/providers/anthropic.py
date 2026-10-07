"""
Live Anthropic LLM provider calling the Anthropic API.

Source of truth: BLUEPRINT.md §15, §17, §23.
Supports general-purpose operations: understand, plan, step dispatch,
reflect, judge, and respond with fallback resilience.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from backend.agent.prompts import (
    JUDGE_PROMPT,
    PLAN_PROMPT,
    REFLECT_PROMPT,
    RESPOND_PROMPT,
    STEP_DISPATCH_PROMPT,
    SYSTEM_PROMPT,
    UNDERSTAND_PROMPT,
)
from backend.agent.providers.base import LLMProvider
from backend.agent.providers.fixture import FixtureProvider
from backend.agent.state import AgentState
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


class AnthropicProvider(LLMProvider):
    """
    Live provider calling Anthropic API.
    Used when EXECUTION_MODE=live.
    Gracefully falls back to dynamic fixture generator if API key is invalid/placeholder.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.ANTHROPIC_API_KEY.get_secret_value()
        self._client: Optional[Any] = None
        self._fallback = FixtureProvider()
        self.model = "claude-3-5-sonnet-20241022"

    def _is_live_ready(self) -> bool:
        if not self._api_key or "placeholder" in self._api_key or len(self._api_key) < 20:
            return False
        return True

    def _get_client(self) -> Any:
        if self._client is None and self._is_live_ready():
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            except Exception as exc:
                logger.warning("Could not initialize Anthropic client: %s", exc)
                self._client = None
        return self._client

    async def _call_claude(self, prompt: str, system: str = SYSTEM_PROMPT) -> Optional[str]:
        client = self._get_client()
        if client is None:
            return None

        try:
            message = await client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            if message.content and len(message.content) > 0:
                return message.content[0].text
        except Exception as exc:
            logger.warning("Anthropic API call failed: %s; falling back", exc)
        return None

    def _parse_json(self, text: Optional[str]) -> Optional[dict[str, Any]]:
        if not text:
            return None
        try:
            # Match json block if fenced
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            return json.loads(text.strip())
        except Exception:
            return None

    async def understand(self, state: AgentState) -> dict[str, Any]:
        prompt = UNDERSTAND_PROMPT.format(goal=state.get("goal", ""))
        raw = await self._call_claude(prompt)
        parsed = self._parse_json(raw)
        if parsed and "understood_task" in parsed and "task_type" in parsed:
            return parsed
        return await self._fallback.understand(state)

    async def plan(self, state: AgentState) -> dict[str, Any]:
        retrieved = state.get("retrieved_recipes", [])
        retrieved_text = json.dumps(retrieved, indent=2) if retrieved else "None"
        prompt = PLAN_PROMPT.format(
            goal=state.get("goal", ""),
            understood_task=state.get("understood_task", ""),
            task_type=state.get("task_type", ""),
            retrieved_recipes_text=retrieved_text,
            available_tools="calculator, web_search, file_reader, code_executor",
        )
        raw = await self._call_claude(prompt)
        parsed = self._parse_json(raw)
        if parsed and "plan" in parsed and isinstance(parsed["plan"], list):
            parsed["current_step"] = parsed["plan"][0] if parsed["plan"] else "plan"
            return parsed
        return await self._fallback.plan(state)

    async def decide_step_action(self, state: AgentState) -> dict[str, Any]:
        from backend.tools.registry import default_tool_registry
        tools_spec = json.dumps(default_tool_registry.list_tools(), indent=2)
        prompt = STEP_DISPATCH_PROMPT.format(
            goal=state.get("goal", ""),
            plan=json.dumps(state.get("plan", [])),
            current_step=state.get("current_step", ""),
            observations_text=json.dumps(state.get("observations", [])),
            tools_spec=tools_spec,
        )
        raw = await self._call_claude(prompt)
        parsed = self._parse_json(raw)
        if parsed and "call_tool" in parsed:
            return parsed
        return await self._fallback.decide_step_action(state)

    async def reflect(self, state: AgentState) -> dict[str, Any]:
        prompt = REFLECT_PROMPT.format(
            goal=state.get("goal", ""),
            plan=json.dumps(state.get("plan", [])),
            tool_calls=json.dumps(state.get("tool_calls", [])),
            observations=json.dumps(state.get("observations", [])),
            evaluation=json.dumps(state.get("evaluation", {})),
        )
        raw = await self._call_claude(prompt)
        parsed = self._parse_json(raw)
        if parsed and "reflection" in parsed:
            return parsed
        return await self._fallback.reflect(state)

    async def judge(self, state: AgentState) -> dict[str, Any]:
        outcome = state.get("final_response") or json.dumps(state.get("observations", []))
        prompt = JUDGE_PROMPT.format(
            goal=state.get("goal", ""),
            plan=json.dumps(state.get("plan", [])),
            tool_calls=json.dumps(state.get("tool_calls", [])),
            observations=json.dumps(state.get("observations", [])),
            outcome=outcome,
        )
        raw = await self._call_claude(prompt)
        parsed = self._parse_json(raw)
        if parsed and "judge_score" in parsed and "task_success" in parsed:
            return parsed
        return await self._fallback.judge(state)

    async def respond(self, state: AgentState) -> dict[str, Any]:
        prompt = RESPOND_PROMPT.format(
            goal=state.get("goal", ""),
            task_type=state.get("task_type", ""),
            observations_text=json.dumps(state.get("observations", [])),
            draft_response=state.get("final_response", ""),
        )
        raw = await self._call_claude(prompt)
        if raw and raw.strip():
            return {"final_response": raw.strip()}
        return await self._fallback.respond(state)
