"""
Understand node: normalizes user goal and determines task type.

Source of truth: BLUEPRINT.md §6, §8, §9.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from backend.agent.state import AgentState, VALID_TASK_TYPES
from backend.core.logging import get_logger

logger = get_logger(__name__)


def classify_task_type(goal: str) -> str:
    """
    Classify the task into one of the canonical task types:
    'math' | 'research' | 'file' | 'code' | 'mixed'
    """
    g = goal.lower()

    # Math keywords
    math_patterns = [
        r"\bcalculate\b",
        r"\bcompound interest\b",
        r"\binterest\b",
        r"\bsum\b",
        r"\barithmetic\b",
        r"\bmultiply\b",
        r"\bdivide\b",
        r"\bequation\b",
        r"\bformula\b",
        r"\bpercentage\b",
        r"\brate\b",
        r"\bcompounded\b",
    ]
    is_math = any(re.search(pat, g) for pat in math_patterns)

    # Research keywords
    research_patterns = [
        r"\bsearch\b",
        r"\blookup\b",
        r"\bwho is\b",
        r"\bwhat is\b",
        r"\blatest news\b",
        r"\bfind information\b",
    ]
    is_research = any(re.search(pat, g) for pat in research_patterns)

    # File keywords
    file_patterns = [
        r"\bread file\b",
        r"\bopen file\b",
        r"\bfile contents\b",
        r"\.txt\b",
        r"\.json\b",
        r"\.csv\b",
    ]
    is_file = any(re.search(pat, g) for pat in file_patterns)

    # Code keywords
    code_patterns = [
        r"\bpython\b",
        r"\bexecute code\b",
        r"\brun script\b",
        r"\bfunction\b",
    ]
    is_code = any(re.search(pat, g) for pat in code_patterns)

    matches = sum([bool(is_math), bool(is_research), bool(is_file), bool(is_code)])
    if matches > 1:
        return "mixed"
    if is_math:
        return "math"
    if is_research:
        return "research"
    if is_file:
        return "file"
    if is_code:
        return "code"

    return "mixed" if matches == 0 else "math"


async def understand(state: AgentState) -> dict[str, Any]:
    """
    Normalizes the goal into understood_task and determines task_type.
    Source: BLUEPRINT.md §6, §8 line 328.
    """
    goal = state.get("goal", "").strip()
    task_type = state.get("task_type", "")

    if not task_type or task_type not in VALID_TASK_TYPES:
        task_type = classify_task_type(goal)

    # Normalize understood_task
    understood_task = goal
    if not understood_task.endswith((".", "?", "!")):
        understood_task += "."

    logger.info(
        "Node 'understand' completed: task_type=%s, understood_task=%s",
        task_type,
        understood_task[:60],
    )

    return {
        "understood_task": understood_task,
        "task_type": task_type,
        "current_step": "understand",
    }
