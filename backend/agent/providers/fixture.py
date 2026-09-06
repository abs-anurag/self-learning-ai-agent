"""
Deterministic fixture provider returning scripted responses.

Source of truth: BLUEPRINT.md §2, §15, §20, §24.
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
    Source: BLUEPRINT.md §15, §24.
    Used when EXECUTION_MODE=demo.
    """

    def __init__(
        self,
        fixtures: Optional[dict[str, Any]] = None,
        fixtures_path: Optional[Path] = None,
    ) -> None:
        self.fixtures: dict[str, Any] = fixtures or {}
        if not self.fixtures and fixtures_path and fixtures_path.exists():
            try:
                with open(fixtures_path, "r", encoding="utf-8") as f:
                    self.fixtures = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load fixture responses: %s", exc)

        if not self.fixtures:
            self._load_default_fixtures()

    def _load_default_fixtures(self) -> None:
        """Load standard Golden Demo fixtures from fixtures directory if available."""
        run_a_file = FIXTURES_DIR / "run_a_responses.json"
        run_b_file = FIXTURES_DIR / "run_b_responses.json"
        if run_a_file.exists():
            try:
                with open(run_a_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        self.fixtures["run_a"] = data
            except Exception as exc:
                logger.debug("Could not load run_a_responses.json: %s", exc)
        if run_b_file.exists():
            try:
                with open(run_b_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data:
                        self.fixtures["run_b"] = data
            except Exception as exc:
                logger.debug("Could not load run_b_responses.json: %s", exc)

    def _resolve_scenario(self, state: AgentState) -> Optional[dict[str, Any]]:
        """Resolve fixture scenario by run_id, scenario tag, or goal pattern."""
        run_id = str(state.get("run_id", ""))
        if run_id in self.fixtures:
            return self.fixtures[run_id]

        goal = str(state.get("goal", "")).lower()
        if ("10,000" in goal or "10000" in goal) and "run_a" in self.fixtures:
            return self.fixtures["run_a"]
        if ("5,000" in goal or "5000" in goal) and "run_b" in self.fixtures:
            return self.fixtures["run_b"]

        return None

    async def plan(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic plan response."""
        scenario = self._resolve_scenario(state)
        if scenario:
            iter_count = state.get("iteration_count", 0)
            iter_key = f"iteration_{iter_count + 1}"
            if iter_key in scenario and "plan" in scenario[iter_key]:
                return scenario[iter_key]["plan"]
            if "plan" in scenario:
                return scenario["plan"]

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
        scenario = self._resolve_scenario(state)
        if scenario:
            iter_count = state.get("iteration_count", 0)
            # In evaluate, iteration_count has already incremented (e.g. 1 after first failure)
            iter_key = f"iteration_{iter_count}" if iter_count > 0 else "iteration_1"
            if iter_key in scenario and "reflect" in scenario[iter_key]:
                return scenario[iter_key]["reflect"]
            if "reflect" in scenario:
                return scenario["reflect"]

        return {
            "reflection": "Strategy adjustment needed based on observation and evaluation.",
        }

    async def judge(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic judge evaluation response."""
        scenario = self._resolve_scenario(state)
        if scenario:
            # During evaluate node, iteration_count is the completed iteration number (0-indexed before increment, or +1)
            iter_count = state.get("iteration_count", 0)
            iter_key = f"iteration_{iter_count + 1}"
            if iter_key in scenario and "judge" in scenario[iter_key]:
                return scenario[iter_key]["judge"]
            if "judge" in scenario:
                return scenario["judge"]

        return {
            "judge_score": 8.5,
            "deterministic_pass": True,
            "tool_success": True,
            "generalizable": True,
            "task_success": True,
        }
