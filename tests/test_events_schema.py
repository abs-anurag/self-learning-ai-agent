"""
Unit tests for Event Envelope and telemetry schema validation.

Source of truth: BLUEPRINT.md §14, §17, §18.

Verifies:
1. Event envelope validation and the 10 durable fields.
2. All 11 required event types are accepted.
3. Invalid event types are rejected.
4. Status vocabulary enforced (completed is rejected).
5. Sensitive telemetry fields (chain_of_thought, judge_reasoning, prompt, etc.)
   are safely stripped.
6. Secret token patterns in metadata strings are actively redacted.
7. Strict validation function rejects prohibited metadata.
8. JSON serialization and deserialization roundtrip.
9. Bidirectional mapping between SQLAlchemy AgentEvent and EventEnvelope.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from backend.db.models import AgentEvent, TaskStatus
from backend.events.schema import (
    EventCreate,
    EventEnvelope,
    EventType,
    PROHIBITED_METADATA_KEYS,
    is_prohibited_key,
    sanitize_metadata,
    validate_safe_metadata,
)


REQUIRED_EVENT_TYPES = [
    "task_started",
    "planning_started",
    "memory_retrieved",
    "tool_started",
    "tool_completed",
    "evaluation_completed",
    "reflection_completed",
    "learning_candidate_created",
    "learning_saved",
    "task_completed",
    "task_failed",
]


class TestEventEnvelopeValidation:
    """Test EventEnvelope schema definition and validation rules."""

    def test_valid_event_envelope_all_fields(self) -> None:
        """Verify that an envelope with all 10 durable fields validates correctly."""
        event_id = uuid.uuid4()
        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        envelope = EventEnvelope(
            event_id=event_id,
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            sequence=1,
            schema_version="1.0",
            timestamp=now,
            event_type=EventType.TASK_STARTED,
            status=TaskStatus.RUNNING,
            metadata={"step": 1, "tool": "calculator"},
        )

        assert envelope.event_id == event_id
        assert envelope.task_id == task_id
        assert envelope.run_id == run_id
        assert envelope.user_id == user_id
        assert envelope.sequence == 1
        assert envelope.schema_version == "1.0"
        assert envelope.timestamp == now
        assert envelope.event_type == EventType.TASK_STARTED
        assert envelope.status == TaskStatus.RUNNING
        assert envelope.metadata == {"step": 1, "tool": "calculator"}

    def test_default_values(self) -> None:
        """Verify defaults for event_id, schema_version, timestamp, and metadata."""
        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()

        envelope = EventEnvelope(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            sequence=1,
            event_type="planning_started",
            status="running",
        )

        assert isinstance(envelope.event_id, uuid.UUID)
        assert envelope.schema_version == "1.0"
        assert envelope.timestamp.tzinfo is not None
        assert envelope.metadata == {}

    def test_invalid_sequence_rejected(self) -> None:
        """Sequence must be >= 1 (PostgreSQL sequences start at 1)."""
        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()

        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(
                task_id=task_id,
                run_id=run_id,
                user_id=user_id,
                sequence=0,
                event_type="task_started",
                status="running",
            )
        assert "sequence" in str(exc_info.value)

    def test_extra_fields_forbidden(self) -> None:
        """Extra undeclared fields must be rejected."""
        with pytest.raises(ValidationError):
            EventEnvelope(
                task_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                sequence=1,
                event_type="task_started",
                status="running",
                unauthorized_field="malicious_payload",
            )


class TestEventTypes:
    """BLUEPRINT.md §14: Exactly 11 allowlisted event types."""

    def test_all_eleven_event_types_exist_in_enum(self) -> None:
        actual_types = {e.value for e in EventType}
        assert actual_types == set(REQUIRED_EVENT_TYPES)
        assert len(actual_types) == 11

    @pytest.mark.parametrize("event_type_str", REQUIRED_EVENT_TYPES)
    def test_all_required_event_types_accepted(self, event_type_str: str) -> None:
        """Each required event type is successfully accepted."""
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=1,
            event_type=event_type_str,
            status="running",
        )
        assert envelope.event_type.value == event_type_str

    @pytest.mark.parametrize(
        "invalid_type",
        [
            "unknown_event",
            "task_in_progress",
            "agent_thinking",
            "custom_telemetry",
            "node_executed",
            "",
        ],
    )
    def test_invalid_event_types_rejected(self, invalid_type: str) -> None:
        """Any unapproved event type is strictly rejected."""
        with pytest.raises(ValidationError):
            EventEnvelope(
                task_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                sequence=1,
                event_type=invalid_type,
                status="running",
            )


class TestStatusVocabulary:
    """BLUEPRINT.md §1, §2, Appendix B: Strict unified status vocabulary."""

    @pytest.mark.parametrize("valid_status", ["pending", "running", "succeeded", "failed"])
    def test_valid_statuses_accepted(self, valid_status: str) -> None:
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=1,
            event_type="task_started",
            status=valid_status,
        )
        assert envelope.status.value == valid_status

    def test_completed_status_is_strictly_forbidden(self) -> None:
        """The status 'completed' is strictly rejected per blueprint."""
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(
                task_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                sequence=1,
                event_type="task_started",
                status="completed",
            )
        assert "completed" in str(exc_info.value).lower()


class TestTelemetrySecurity:
    """BLUEPRINT.md §17: Telemetry privacy, prohibited keys, redaction."""

    @pytest.mark.parametrize(
        "prohibited_key",
        [
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
        ],
    )
    def test_prohibited_metadata_keys_stripped(self, prohibited_key: str) -> None:
        """Prohibited telemetry keys are automatically stripped from metadata."""
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=1,
            event_type="task_started",
            status="running",
            metadata={
                prohibited_key: "confidential reasoning / prompt / secret",
                "safe_field": "safe_value",
            },
        )
        assert prohibited_key not in envelope.metadata
        assert envelope.metadata == {"safe_field": "safe_value"}

    def test_nested_prohibited_keys_stripped(self) -> None:
        """Prohibited keys in nested dicts or lists are safely stripped."""
        nested_meta = {
            "node": "plan",
            "details": {
                "chain_of_thought": "hidden thoughts",
                "tool_name": "calculator",
            },
            "history": [
                {"prompt": "my full prompt", "iteration": 1},
                {"safe_note": "ok", "iteration": 2},
            ],
        }
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=1,
            event_type="planning_started",
            status="running",
            metadata=nested_meta,
        )
        assert "chain_of_thought" not in envelope.metadata["details"]
        assert envelope.metadata["details"]["tool_name"] == "calculator"
        assert "prompt" not in envelope.metadata["history"][0]
        assert envelope.metadata["history"][0]["iteration"] == 1
        assert envelope.metadata["history"][1]["safe_note"] == "ok"

    def test_secret_tokens_in_string_values_redacted(self) -> None:
        """API key patterns inside string values are redacted."""
        meta = {
            "error": "Failed with token sk-ant-api03-secret1234567890abcdef",
            "tool": "tavily",
        }
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=1,
            event_type="tool_completed",
            status="failed",
            metadata=meta,
        )
        assert "sk-ant-" not in envelope.metadata["error"]
        assert "[REDACTED]" in envelope.metadata["error"]
        assert envelope.metadata["tool"] == "tavily"

    def test_validate_safe_metadata_rejects_prohibited_keys(self) -> None:
        """validate_safe_metadata raises ValueError if prohibited keys exist."""
        with pytest.raises(ValueError) as exc:
            validate_safe_metadata({"chain_of_thought": "thinking..."})
        assert "chain_of_thought" in str(exc.value)

        # Clean metadata passes without error
        validate_safe_metadata({"iteration": 1, "tool_name": "calculator"})


class TestSerializationAndDbMapping:
    """Test JSON serialization and conversion with SQLAlchemy model."""

    def test_json_roundtrip(self) -> None:
        """Verify model_dump_json and parsing back produces identical envelope."""
        original = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=5,
            schema_version="1.0",
            event_type=EventType.TOOL_COMPLETED,
            status=TaskStatus.SUCCEEDED,
            metadata={"tool_name": "calculator", "duration_ms": 120},
        )
        json_str = original.model_dump_json()
        data = json.loads(json_str)

        assert data["sequence"] == 5
        assert data["event_type"] == "tool_completed"
        assert data["status"] == "succeeded"
        assert data["metadata"]["tool_name"] == "calculator"

        # Reconstruct
        restored = EventEnvelope.model_validate(data)
        assert restored.event_id == original.event_id
        assert restored.sequence == original.sequence
        assert restored.event_type == original.event_type
        assert restored.status == original.status

    def test_db_model_bidirectional_conversion(self) -> None:
        """Test converting between SQLAlchemy AgentEvent and Pydantic EventEnvelope."""
        envelope = EventEnvelope(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            sequence=3,
            event_type=EventType.EVALUATION_COMPLETED,
            status=TaskStatus.SUCCEEDED,
            metadata={"score": 8.5},
        )

        db_model = envelope.to_db_model()
        assert isinstance(db_model, AgentEvent)
        assert db_model.event_id == envelope.event_id
        assert db_model.sequence == envelope.sequence
        assert db_model.event_type == "evaluation_completed"
        assert db_model.status == "succeeded"
        assert db_model.metadata_ == {"score": 8.5}

        # Convert back
        reconstructed = EventEnvelope.from_db_model(db_model)
        assert reconstructed.event_id == envelope.event_id
        assert reconstructed.sequence == envelope.sequence
        assert reconstructed.event_type == envelope.event_type
        assert reconstructed.status == envelope.status
        assert reconstructed.metadata == envelope.metadata
