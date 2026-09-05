"""
Event envelope schema and telemetry security sanitization.

Source of truth: BLUEPRINT.md §14, §17, §18.

Design rules:
- Strictly adheres to the 10 durable event fields:
  event_id, task_id, run_id, user_id, sequence, schema_version,
  timestamp, event_type, status, metadata.
- Supported event types are exactly the 11 allowlisted types in §14, §17.
- Status vocabulary is strictly unified: 'pending', 'running', 'succeeded', 'failed'.
  The value 'completed' is strictly forbidden.
- Telemetry security (§17):
  Event metadata MUST NOT contain chain-of-thought, judge_reasoning, full prompts,
  API keys, secrets, raw reflection essays, or full file bodies.
  Prohibited keys are stripped and secrets in values are actively redacted.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Final, List, Optional, Set, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core.logging import redact_text, redact_value
from backend.db.models import TaskStatus

if TYPE_CHECKING:
    from backend.db.models import AgentEvent


# -- Allowlisted Event Types (BLUEPRINT.md §14) -----------------


class EventType(str, Enum):
    """
    Allowlisted event types for agent telemetry.
    Source: BLUEPRINT.md §14 Event Types.
    """
    TASK_STARTED = "task_started"
    PLANNING_STARTED = "planning_started"
    MEMORY_RETRIEVED = "memory_retrieved"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    EVALUATION_COMPLETED = "evaluation_completed"
    REFLECTION_COMPLETED = "reflection_completed"
    LEARNING_CANDIDATE_CREATED = "learning_candidate_created"
    LEARNING_SAVED = "learning_saved"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"


# -- Telemetry Security Allowlist & Prohibited Keys ------------

PROHIBITED_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "chain_of_thought",
        "judge_reasoning",
        "prompt",
        "prompts",
        "full_prompt",
        "raw_prompt",
        "raw_reflection",
        "raw_reflection_essay",
        "reflection_essay",
        "file_body",
        "full_file_body",
        "file_content",
        "api_key",
        "api_key_hash",
        "secret",
        "secrets",
        "anthropic_api_key",
        "tavily_api_key",
        "api_key_salt",
        "postgres_url",
    }
)


def is_prohibited_key(key: str) -> bool:
    """Check whether a metadata dictionary key is prohibited."""
    normalized = key.strip().lower().replace("-", "_")
    return normalized in PROHIBITED_METADATA_KEYS


def sanitize_metadata(val: Any) -> Any:
    """
    Recursively strip prohibited keys and redact secret patterns in metadata.

    Source: BLUEPRINT.md §17 Telemetry Privacy.
    """
    if isinstance(val, dict):
        cleaned: dict[str, Any] = {}
        for k, v in val.items():
            if is_prohibited_key(str(k)):
                continue
            cleaned[str(k)] = sanitize_metadata(v)
        return cleaned
    elif isinstance(val, list):
        return [sanitize_metadata(item) for item in val]
    elif isinstance(val, tuple):
        return tuple(sanitize_metadata(item) for item in val)
    elif isinstance(val, str):
        return redact_value(val)
    return val


def validate_safe_metadata(metadata: dict[str, Any]) -> None:
    """
    Strictly validate that metadata contains no prohibited keys or plaintext secrets.
    Raises ValueError if prohibited content is detected.
    """
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be a dictionary.")

    for k, v in metadata.items():
        if is_prohibited_key(str(k)):
            raise ValueError(f"Prohibited telemetry key found in metadata: '{k}'")
        if isinstance(v, dict):
            validate_safe_metadata(v)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    validate_safe_metadata(item)


# -- Event Schemas -----------------------------------------------


class EventCreate(BaseModel):
    """
    Payload used to construct an event before sequence allocation.
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    task_id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    event_type: EventType
    status: TaskStatus = TaskStatus.RUNNING
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = Field(default="1.0", max_length=10)
    event_id: Optional[uuid.UUID] = None
    timestamp: Optional[datetime] = None

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> TaskStatus:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower == "completed":
                raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
            return TaskStatus(v_lower)
        elif isinstance(v, TaskStatus):
            return v
        raise ValueError(f"Invalid status: {v}")

    @field_validator("metadata", mode="before")
    @classmethod
    def clean_metadata(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            return {}
        return sanitize_metadata(v)


class EventEnvelope(BaseModel):
    """
    Durable event envelope matching BLUEPRINT.md §14 and §18.

    The 10 durable event fields:
    - event_id
    - task_id
    - run_id
    - user_id
    - sequence
    - schema_version
    - timestamp
    - event_type
    - status
    - metadata
    """
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    task_id: uuid.UUID
    run_id: uuid.UUID
    user_id: uuid.UUID
    sequence: int = Field(ge=1, description="Monotonic sequence allocated by PostgreSQL per run_id")
    schema_version: str = Field(default="1.0", max_length=10)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: EventType
    status: TaskStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> TaskStatus:
        if isinstance(v, str):
            v_lower = v.lower().strip()
            if v_lower == "completed":
                raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
            return TaskStatus(v_lower)
        elif isinstance(v, TaskStatus):
            return v
        raise ValueError(f"Invalid status: {v}")

    @field_validator("metadata", mode="before")
    @classmethod
    def clean_metadata(cls, v: Any) -> dict[str, Any]:
        if not isinstance(v, dict):
            return {}
        return sanitize_metadata(v)

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_timezone_aware(cls, v: Any) -> datetime:
        if isinstance(v, str):
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        elif isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v
        elif v is None:
            return datetime.now(timezone.utc)
        return v

    @classmethod
    def from_db_model(cls, record: "AgentEvent") -> EventEnvelope:
        """Construct an EventEnvelope from an AgentEvent SQLAlchemy record."""
        return cls(
            event_id=record.event_id,
            task_id=record.task_id,
            run_id=record.run_id,
            user_id=record.user_id,
            sequence=record.sequence,
            schema_version=record.schema_version,
            timestamp=record.timestamp,
            event_type=EventType(record.event_type),
            status=TaskStatus(record.status),
            metadata=record.metadata_,
        )

    def to_db_model(self) -> "AgentEvent":
        """Convert this envelope to an AgentEvent SQLAlchemy model."""
        from backend.db.models import AgentEvent

        return AgentEvent(
            event_id=self.event_id,
            task_id=self.task_id,
            run_id=self.run_id,
            user_id=self.user_id,
            sequence=self.sequence,
            schema_version=self.schema_version,
            timestamp=self.timestamp,
            event_type=self.event_type.value,
            status=self.status.value,
            metadata_=self.metadata,
        )
