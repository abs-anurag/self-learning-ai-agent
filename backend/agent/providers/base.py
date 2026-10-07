"""
Abstract LLM provider interface.

Source of truth: BLUEPRINT.md §15.
Provides interface for understand, plan, execute step, reflect, judge, and respond operations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from backend.agent.state import AgentState


class LLMProvider(ABC):
    """
    Abstract LLM provider interface for general-purpose agent operations.
    Source: BLUEPRINT.md §15.
    """

    @abstractmethod
    async def plan(self, state: AgentState) -> dict[str, Any]:
        """Formulate initial action plan based on agent state."""
        pass

    @abstractmethod
    async def reflect(self, state: AgentState) -> dict[str, Any]:
        """Formulate diagnosis and failure reflection based on agent state."""
        pass

    @abstractmethod
    async def judge(self, state: AgentState) -> dict[str, Any]:
        """Evaluate task execution and compute judge score and flags."""
        pass

    async def understand(self, state: AgentState) -> dict[str, Any]:
        """Normalize goal into understood_task and determine task_type."""
        return {
            "understood_task": state.get("goal", ""),
            "task_type": "research",
            "needs_tools": False,
        }

    async def decide_step_action(self, state: AgentState) -> dict[str, Any]:
        """Determine whether to invoke a tool or generate direct output for the current step."""
        return {
            "call_tool": False,
            "tool_name": None,
            "parameters": {},
            "thought": "Direct processing",
        }

    async def respond(self, state: AgentState) -> dict[str, Any]:
        """Synthesize final response for the user."""
        return {
            "final_response": "Task completed.",
        }
