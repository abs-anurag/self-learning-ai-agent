"""
Candidate recipe extraction from successful task execution.

Source of truth: BLUEPRINT.md section10, section11, section18.

This module extracts candidate recipes from successful task runs by:
1. Checking canonical task success criteria (deterministic_pass, tool_success, judge_score, final_answer)
2. Validating candidate eligibility (non-empty fields, evidence, provenance)
3. Sanitizing sensitive data before storage
4. Creating RecipeCandidate records for pre-gate structured lessons

Design rules:
- Canonical success: deterministic_pass AND tool_success AND judge_score >= TASK_SUCCESS_THRESHOLD AND final_answer_present
- No arbitrary "trivial task" taxonomy
- Security: sanitize API keys, tokens, secrets before storage
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings
from backend.db.models import RecipeCandidate

logger = logging.getLogger(__name__)


# Patterns for detecting sensitive data
SENSITIVE_PATTERNS = [
    re.compile(r'sk-[a-zA-Z0-9]{20,}', re.IGNORECASE),  # API keys (e.g., sk-ant-...)
    re.compile(r'tvly-[a-zA-Z0-9]{20,}', re.IGNORECASE),  # Tavily keys
    re.compile(r'Bearer\s+[a-zA-Z0-9_\-\.]{20,}', re.IGNORECASE),  # Bearer tokens
    re.compile(r'password["\s:=]+[^\s"]+', re.IGNORECASE),  # Passwords in strings
    re.compile(r'token["\s:=]+[^\s"]+', re.IGNORECASE),  # Tokens in strings
]


def check_canonical_task_success(
    deterministic_pass: bool,
    tool_success: bool,
    judge_score: float,
    final_answer_present: bool,
    settings: Settings,
) -> bool:
    """
    Check canonical task success criteria.

    Source: BLUEPRINT.md section11.

    Canonical success requires ALL of:
    - deterministic_pass: True (deterministic checks passed)
    - tool_success: True (no tool errors)
    - judge_score >= TASK_SUCCESS_THRESHOLD (LLM judge quality threshold)
    - final_answer_present: True (answer was provided)

    Args:
        deterministic_pass: Whether deterministic checks passed
        tool_success: Whether all tools succeeded without errors
        judge_score: LLM judge quality score (0-10)
        final_answer_present: Whether a final answer was provided
        settings: Application settings containing TASK_SUCCESS_THRESHOLD

    Returns:
        True if all canonical success criteria are met, False otherwise
    """
    threshold = settings.TASK_SUCCESS_THRESHOLD

    success = (
        deterministic_pass
        and tool_success
        and judge_score >= threshold
        and final_answer_present
    )

    logger.debug(
        f"Canonical success check: deterministic={deterministic_pass}, "
        f"tool_success={tool_success}, judge_score={judge_score} (threshold={threshold}), "
        f"final_answer={final_answer_present} => {success}"
    )

    return success


def is_candidate_eligible(
    task_data: dict[str, Any],
    settings: Settings,
) -> tuple[bool, str]:
    """
    Validate candidate recipe eligibility.

    Source: BLUEPRINT.md section10, section11.

    A candidate is eligible if:
    1. task_success (canonical criteria met)
    2. Non-empty lesson
    3. Non-empty recommended_strategy
    4. Non-empty successful_steps
    5. Evidence present
    6. Provenance present (source_task_id, run_id)

    Args:
        task_data: Dictionary containing task execution data with keys:
            - deterministic_pass: bool
            - tool_success: bool
            - judge_score: float
            - final_answer_present: bool
            - lesson: str
            - recommended_strategy: str
            - successful_steps: list
            - evidence: str
            - source_task_id: UUID
            - run_id: UUID
        settings: Application settings

    Returns:
        Tuple of (eligible: bool, reason: str)
        - If eligible: (True, "eligible")
        - If not eligible: (False, reason_string)
    """
    # Check canonical task success
    task_success = check_canonical_task_success(
        deterministic_pass=task_data.get("deterministic_pass", False),
        tool_success=task_data.get("tool_success", False),
        judge_score=task_data.get("judge_score", 0.0),
        final_answer_present=task_data.get("final_answer_present", False),
        settings=settings,
    )

    if not task_success:
        return False, "canonical task success criteria not met"

    # Check non-empty lesson
    lesson = task_data.get("lesson", "")
    if not lesson or not lesson.strip():
        return False, "lesson is empty"

    # Check non-empty recommended_strategy
    recommended_strategy = task_data.get("recommended_strategy", "")
    if not recommended_strategy or not recommended_strategy.strip():
        return False, "recommended_strategy is empty"

    # Check non-empty successful_steps
    successful_steps = task_data.get("successful_steps", [])
    if not successful_steps or len(successful_steps) == 0:
        return False, "successful_steps is empty"

    # Check evidence present
    evidence = task_data.get("evidence", "")
    if not evidence or not evidence.strip():
        return False, "evidence is empty"

    # Check provenance (source_task_id and run_id)
    source_task_id = task_data.get("source_task_id")
    run_id = task_data.get("run_id")
    if not source_task_id:
        return False, "source_task_id missing"
    if not run_id:
        return False, "run_id missing"

    logger.info(
        f"Candidate eligible: task_id={source_task_id}, run_id={run_id}, "
        f"judge_score={task_data.get('judge_score')}"
    )

    return True, "eligible"


def _sanitize_text(text: str) -> str:
    """
    Sanitize text by redacting sensitive data patterns.

    Security requirement: BLUEPRINT.md section17.
    Remove API keys, tokens, passwords, and other sensitive data before storage.

    Args:
        text: Text to sanitize

    Returns:
        Sanitized text with sensitive patterns replaced with [REDACTED]
    """
    if not text:
        return text

    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[REDACTED]", sanitized)

    return sanitized


def _sanitize_json(data: Any) -> Any:
    """
    Recursively sanitize JSON/dict data by redacting sensitive patterns.

    Args:
        data: JSON-serializable data (dict, list, str, etc.)

    Returns:
        Sanitized copy of the data
    """
    if isinstance(data, dict):
        return {key: _sanitize_json(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_sanitize_json(item) for item in data]
    elif isinstance(data, str):
        return _sanitize_text(data)
    else:
        return data


async def extract_candidate_recipe(
    db_session: AsyncSession,
    task_run_id: uuid.UUID,
    task_data: dict[str, Any],
    settings: Settings,
) -> Optional[RecipeCandidate]:
    """
    Extract and store a candidate recipe from successful task execution.

    Source: BLUEPRINT.md section10, section11, section18.

    This function:
    1. Validates candidate eligibility
    2. Sanitizes sensitive data
    3. Creates RecipeCandidate record in database
    4. Returns the created candidate or None if ineligible

    Args:
        db_session: Async SQLAlchemy database session
        task_run_id: ID of the task run (for logging; actual UUID from task_data)
        task_data: Dictionary containing all required fields:
            - source_task_id: UUID
            - run_id: UUID
            - user_id: UUID
            - task_type: str (math, research, file, code, mixed)
            - problem_pattern: str
            - context: str
            - recommended_strategy: str
            - successful_steps: list[dict]
            - failed_steps: list[dict]
            - tools_used: list[str]
            - lesson: str
            - evidence: str
            - evaluation_score: float (judge_score)
            - deterministic_pass: bool
            - generalizable: bool
            - deterministic_pass: bool
            - tool_success: bool
            - judge_score: float
            - final_answer_present: bool
        settings: Application settings

    Returns:
        RecipeCandidate instance if eligible and saved, None otherwise

    Raises:
        Exception: Database errors during save operation
    """
    # Check eligibility
    eligible, reason = is_candidate_eligible(task_data, settings)
    if not eligible:
        logger.info(f"Candidate not eligible for run_id={task_run_id}: {reason}")
        return None

    try:
        # Sanitize all text fields
        sanitized_data = {
            "source_task_id": task_data["source_task_id"],
            "run_id": task_data["run_id"],
            "user_id": task_data["user_id"],
            "task_type": task_data["task_type"],
            "problem_pattern": _sanitize_text(task_data["problem_pattern"]),
            "context": _sanitize_text(task_data["context"]),
            "recommended_strategy": _sanitize_text(task_data["recommended_strategy"]),
            "successful_steps": _sanitize_json(task_data["successful_steps"]),
            "failed_steps": _sanitize_json(task_data.get("failed_steps", [])),
            "tools_used": _sanitize_json(task_data["tools_used"]),
            "lesson": _sanitize_text(task_data["lesson"]),
            "evidence": _sanitize_text(task_data["evidence"]),
            "evaluation_score": task_data["judge_score"],
            "deterministic_pass": task_data["deterministic_pass"],
            "generalizable": task_data.get("generalizable", False),
        }

        # Create RecipeCandidate instance
        candidate = RecipeCandidate(**sanitized_data)

        # Add to session and flush (caller owns transaction)
        db_session.add(candidate)
        await db_session.flush()

        logger.info(
            f"Created recipe candidate id={candidate.id} from run_id={task_run_id}, "
            f"task_type={candidate.task_type}, score={candidate.evaluation_score}"
        )

        return candidate

    except KeyError as e:
        logger.error(f"Missing required field in task_data: {e}")
        raise ValueError(f"Missing required field: {e}") from e

    except Exception as e:
        logger.error(f"Failed to create recipe candidate for run_id={task_run_id}: {e}")
        await db_session.rollback()
        raise
