"""
Episodic experience recording and sanitization.

Source of truth: BLUEPRINT.md §10, §18.

This module provides functions to:
- Record episodic experiences to the database with full provenance
- Sanitize sensitive data (secrets, API keys, passwords, auth tokens, system prompts, judge reasoning)
- Handle SQLAlchemy session management properly

Design rules:
- All experiences include task_id, run_id, user_id provenance fields
- Sensitive data is sanitized before storage
- Raw system prompts and chain-of-thought are excluded
- Private judge reasoning is never stored in experiences
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from backend.db.models import Experience, TaskRun, Task


# Patterns for detecting sensitive information
SENSITIVE_PATTERNS = [
    # API Keys and tokens
    (re.compile(r'(api[_-]?key|apikey|access[_-]?key|secret[_-]?key)[\s:=]+[\"']?([a-zA-Z0-9_\-]{20,})[\"']?', re.IGNORECASE), '[API_KEY_REDACTED]'),
    (re.compile(r'(bearer|token)[\s:=]+[\"']?([a-zA-Z0-9_\-\.]{20,})[\"']?', re.IGNORECASE), '[TOKEN_REDACTED]'),

    # Passwords
    (re.compile(r'(password|passwd|pwd)[\s:=]+[\"']?([^\s\"']{6,})[\"']?', re.IGNORECASE), '[PASSWORD_REDACTED]'),

    # AWS keys
    (re.compile(r'(AKIA[0-9A-Z]{16})', re.IGNORECASE), '[AWS_KEY_REDACTED]'),

    # Private keys
    (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+ PRIVATE KEY-----', re.IGNORECASE), '[PRIVATE_KEY_REDACTED]'),

    # OAuth tokens
    (re.compile(r'(oauth[_-]?token|access[_-]?token)[\s:=]+[\"']?([a-zA-Z0-9_\-\.]{20,})[\"']?', re.IGNORECASE), '[OAUTH_TOKEN_REDACTED]'),

    # Connection strings with passwords
    (re.compile(r'(mongodb(\+srv)?|postgres|mysql|redis)://[^:]+:([^@]+)@', re.IGNORECASE), r'\1://[USER]:[PASSWORD_REDACTED]@'),
]

# Keys that should be removed entirely from dictionaries
SENSITIVE_KEYS = {
    'api_key', 'apikey', 'api-key', 'access_key', 'access-key', 'secret_key', 'secret-key',
    'password', 'passwd', 'pwd', 'pass',
    'token', 'auth_token', 'auth-token', 'bearer_token', 'bearer-token',
    'oauth_token', 'oauth-token', 'access_token', 'access-token',
    'private_key', 'private-key', 'secret', 'secrets',
    'system_prompt', 'system-prompt', 'systemprompt',
    'chain_of_thought', 'chain-of-thought', 'cot',
    'judge_reasoning', 'judge-reasoning', 'reasoning',
    'internal_prompt', 'internal-prompt',
}


def sanitize_string(text: str) -> str:
    """
    Sanitize a string by removing/masking sensitive patterns.

    Args:
        text: Input string to sanitize

    Returns:
        Sanitized string with sensitive data redacted
    """
    if not isinstance(text, str):
        return text

    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized


def sanitize_sensitive_data(data: Any) -> Any:
    """
    Recursively sanitize sensitive information from data structures.

    Removes or masks:
    - API keys, passwords, auth tokens
    - System prompts and chain-of-thought
    - Private judge reasoning
    - Secret keys and private keys
    - OAuth tokens and bearer tokens

    Args:
        data: Input data (dict, list, str, or primitive type)

    Returns:
        Sanitized copy of the data with sensitive information removed/masked

    Examples:
        >>> sanitize_sensitive_data({"api_key": "secret123", "name": "test"})
        {"name": "test"}

        >>> sanitize_sensitive_data({"url": "postgres://user:pass@host/db"})
        {"url": "postgres://[USER]:[PASSWORD_REDACTED]@host/db"}
    """
    if data is None:
        return None

    # Handle dictionaries
    if isinstance(data, dict):
        sanitized = {}
        for key, value in data.items():
            # Remove sensitive keys entirely
            key_lower = str(key).lower().replace('_', '-')
            if key_lower in SENSITIVE_KEYS:
                continue

            # Recursively sanitize values
            sanitized[key] = sanitize_sensitive_data(value)
        return sanitized

    # Handle lists
    if isinstance(data, (list, tuple)):
        return [sanitize_sensitive_data(item) for item in data]

    # Handle strings
    if isinstance(data, str):
        return sanitize_string(data)

    # Return primitives as-is
    return data


async def record_experience(
    db_session: AsyncSession,
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    task_type: str,
    tools_used: list[str],
    outcome_summary: str,
) -> Experience:
    """
    Record a single episodic experience to the database.

    This function creates an experience record with full provenance tracking
    and automatically sanitizes sensitive data before storage.

    Args:
        db_session: Active SQLAlchemy async database session
        task_id: UUID of the parent task
        run_id: UUID of the task run
        user_id: UUID of the user
        task_type: Type of task (math, research, file, code, mixed)
        tools_used: List of tool names used during this experience
        outcome_summary: Summary of what happened and the outcome

    Returns:
        The created Experience object

    Raises:
        SQLAlchemyError: If database operation fails
        ValueError: If required foreign keys don't exist

    Examples:
        >>> exp = await record_experience(
        ...     db_session=session,
        ...     task_id=task_uuid,
        ...     run_id=run_uuid,
        ...     user_id=user_uuid,
        ...     task_type="code",
        ...     tools_used=["bash", "edit", "read"],
        ...     outcome_summary="Successfully fixed the bug in auth.py:42"
        ... )
    """
    # Validate that the run exists and belongs to the task
    run_result = await db_session.execute(
        select(TaskRun).where(
            TaskRun.id == run_id,
            TaskRun.task_id == task_id,
            TaskRun.user_id == user_id
        )
    )
    run = run_result.scalar_one_or_none()

    if not run:
        raise ValueError(
            f"TaskRun {run_id} not found or doesn't belong to task {task_id} and user {user_id}"
        )

    # Validate that the task exists
    task_result = await db_session.execute(
        select(Task).where(
            Task.id == task_id,
            Task.user_id == user_id
        )
    )
    task = task_result.scalar_one_or_none()

    if not task:
        raise ValueError(
            f"Task {task_id} not found or doesn't belong to user {user_id}"
        )

    # Sanitize all input data
    sanitized_tools = sanitize_sensitive_data(tools_used)
    sanitized_summary = sanitize_sensitive_data(outcome_summary)
    sanitized_task_type = sanitize_sensitive_data(task_type)

    # Ensure tools_used is a list
    if not isinstance(sanitized_tools, list):
        sanitized_tools = []

    try:
        # Create the experience record
        experience = Experience(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            task_type=sanitized_task_type,
            tools_used=sanitized_tools,
            outcome_summary=sanitized_summary,
            created_at=datetime.now(timezone.utc),
        )

        db_session.add(experience)
        await db_session.flush()  # Flush to get the ID without committing

        return experience

    except SQLAlchemyError as e:
        await db_session.rollback()
        raise SQLAlchemyError(f"Failed to record experience: {str(e)}") from e
