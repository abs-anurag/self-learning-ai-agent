"""
Abstract LLM provider interface.

Source of truth: BLUEPRINT.md §15.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from backend.agent.state import AgentState


class LLMProvider(ABC):
    """
    Abstract LLM provider interface for plan, reflect, and judge operations.
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
