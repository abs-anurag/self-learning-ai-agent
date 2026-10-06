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

    async def understand(self, state: AgentState) -> dict[str, Any]:
        """Parse goal into structured understanding with task type detection."""
        goal = state.get("goal", "")
        goal_lower = goal.lower()

        # Detect task type from goal text
        task_type = "mixed"
        math_keywords = ["calculate", "compute", "multiply", "divide", "add", "subtract",
                         "sum", "product", "result", "equation", "math", "arithmetic",
                         "multiplied", "plus", "minus", "times"]
        research_keywords = ["search", "find", "look up", "research", "information"]
        file_keywords = ["read", "file", "open", "load", "content"]

        if any(kw in goal_lower for kw in math_keywords):
            task_type = "math"
        elif any(kw in goal_lower for kw in research_keywords):
            task_type = "research"
        elif any(kw in goal_lower for kw in file_keywords):
            task_type = "file"

        return {
            "understood_task": goal,
            "task_type": task_type,
        }

    async def act(self, state: AgentState) -> dict[str, Any]:
        """Determine tool to use and arguments based on state.

        Parses current_step and goal to pick the right tool.
        CRITICAL: Must return a registered tool name (calculator, file_reader, web_search).
        Must NEVER return 'internal'.
        """
        goal = state.get("goal", "")
        task_type = state.get("task_type", "")
        current_step = state.get("current_step", "")

        # Math/calculation tasks -> calculator
        if task_type == "math" or any(kw in goal.lower() for kw in [
            "calculate", "compute", "multiply", "divide", "add", "subtract",
            "multiplied", "sum", "product", "times", "plus", "minus",
        ]):
            expression = self._extract_math_expression(goal)
            return {
                "tool": "calculator",
                "args": {"expression": expression},
            }

        # Research tasks -> web_search
        if task_type == "research":
            return {
                "tool": "web_search",
                "args": {"query": goal},
            }

        # File tasks -> file_reader
        if task_type == "file":
            return {
                "tool": "file_reader",
                "args": {"path": goal},
            }

        # Default: try calculator for anything with numbers
        expression = self._extract_math_expression(goal)
        if expression:
            return {
                "tool": "calculator",
                "args": {"expression": expression},
            }

        # Fallback: calculator with the goal as expression
        return {
            "tool": "calculator",
            "args": {"expression": goal},
        }

    def _extract_math_expression(self, goal: str) -> str:
        """Extract a mathematical expression from natural language goal."""
        import re
        # Try to find explicit expressions like "25 * 48" or "25 x 48"
        # Handle "multiplied by", "times", "x" etc.
        text = goal.lower()

        # Replace natural language operators with math symbols
        text = re.sub(r'\bmultiplied\s+by\b', '*', text)
        text = re.sub(r'\btimes\b', '*', text)
        text = re.sub(r'\bdivided\s+by\b', '/', text)
        text = re.sub(r'\bplus\b', '+', text)
        text = re.sub(r'\bminus\b', '-', text)
        text = re.sub(r'\bx\b', '*', text)

        # Extract numeric expressions: look for patterns like "25 * 48"
        match = re.search(r'(\d+[\d\s\.\+\-\*/\(\)]*[\+\-\*/][\d\s\.\+\-\*/\(\)]*\d+)', text)
        if match:
            expr = match.group(1).strip()
            return expr

        # Look for any numbers and try to form an expression
        numbers = re.findall(r'\d+\.?\d*', text)
        if len(numbers) >= 2:
            # Check for operator context
            if '*' in text:
                return f"{numbers[0]} * {numbers[1]}"
            elif '/' in text:
                return f"{numbers[0]} / {numbers[1]}"
            elif '+' in text:
                return f"{numbers[0]} + {numbers[1]}"
            elif '-' in text:
                return f"{numbers[0]} - {numbers[1]}"
            # Default to multiplication if "multiply" context detected
            return f"{numbers[0]} * {numbers[1]}"

        return goal  # Fallback

    async def plan(self, state: AgentState) -> dict[str, Any]:
        """Return scripted or deterministic plan response."""
        run_id = state.get("run_id", "")
        if run_id in self.fixtures and "plan" in self.fixtures[run_id]:
            return self.fixtures[run_id]["plan"]

        task_type = state.get("task_type", "mixed")
        goal = state.get("goal", "")

        if task_type == "math":
            return {
                "plan": [
                    f"Use calculator tool to compute: {goal}",
                    "Verify the result",
                    "Format and explain the answer",
                ],
                "current_step": f"Use calculator tool to compute: {goal}",
            }

        return {
            "plan": [
                "Understand the requirements and extract key parameters",
                "Execute the appropriate tools to compute result",
                "Format and verify final answer",
            ],
            "current_step": "Execute the appropriate tools to compute result",
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

        tool_calls = state.get("tool_calls", [])
        has_failed_tools = any(
            c.get("status") == "failed"
            for c in tool_calls if isinstance(c, dict)
        )
        if has_failed_tools and not any(c.get("status") == "success" for c in tool_calls if isinstance(c, dict)):
            return {
                "judge_score": 3.0,
                "deterministic_pass": False,
                "tool_success": False,
                "generalizable": False,
                "task_success": False,
                "judge_reasoning": "Tool execution failed.",
            }

        return {
            "judge_score": 8.5,
            "deterministic_pass": True,
            "tool_success": True,
            "generalizable": True,
            "task_success": True,
            "judge_reasoning": "Task completed successfully with correct tool usage." if tool_calls else "Deterministic fixture evaluation passed.",
        }
