"""
Deterministic fixture provider returning scripted responses.

Source of truth: BLUEPRINT.md §2, §15, §20.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from backend.agent.providers.base import LLMProvider
from backend.agent.state import AgentState
from backend.core.logging import get_logger

logger = get_logger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class FixtureProvider(LLMProvider):
    """
    Deterministic provider returning scripted responses from JSON fixtures.
    Source: BLUEPRINT.md §15.
    Used when EXECUTION_MODE=demo.
    """

    def __init__(
        self,
        fixtures: Optional[dict[str, Any]] = None,
        fixtures_path: Optional[Path] = None,
    ) -> None:
        self.fixtures = fixtures or {}
        if not self.fixtures and fixtures_path and fixtures_path.exists():
            try:
                with open(fixtures_path, "r", encoding="utf-8") as f:
                    self.fixtures = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load fixture responses: %s", exc)

    async def plan(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic plan response."""
        run_id = state.get("run_id", "")
        if run_id in self.fixtures and "plan" in self.fixtures[run_id]:
            return self.fixtures[run_id]["plan"]

        return {
            "plan": [
                "Understand the requirements and extract key parameters",
                "Execute the appropriate tools to compute result",
                "Format and verify final answer",
            ],
            "current_step": "plan",
        }

    async def reflect(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic reflection response."""
        run_id = state.get("run_id", "")
        if run_id in self.fixtures and "reflect" in self.fixtures[run_id]:
            return self.fixtures[run_id]["reflect"]

        return {
            "reflection": "Strategy adjustment needed based on observation and evaluation.",
        }

    async def judge(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic judge evaluation response."""
        run_id = state.get("run_id", "")
        if run_id in self.fixtures and "judge" in self.fixtures[run_id]:
            return self.fixtures[run_id]["judge"]

        return {
            "judge_score": 8.5,
            "deterministic_pass": True,
            "tool_success": True,
            "generalizable": True,
            "task_success": True,
        }
