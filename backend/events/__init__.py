"""
Event Service foundation package.

Source of truth: BLUEPRINT.md §14, §17, §18.
"""

from backend.events.publisher import (
    EventPublisher,
    RedisEventPublisher,
)
from backend.events.schema import (
    PROHIBITED_METADATA_KEYS,
    EventCreate,
    EventEnvelope,
    EventType,
    is_prohibited_key,
    sanitize_metadata,
    validate_safe_metadata,
)
from backend.events.service import (
    EventService,
    EventServiceError,
    TaskRunNotFoundError,
)

__all__ = [
    "EventType",
    "EventEnvelope",
    "EventCreate",
    "PROHIBITED_METADATA_KEYS",
    "is_prohibited_key",
    "sanitize_metadata",
    "validate_safe_metadata",
    "EventPublisher",
    "RedisEventPublisher",
    "EventService",
    "EventServiceError",
    "TaskRunNotFoundError",
]
