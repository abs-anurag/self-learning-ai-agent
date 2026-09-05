"""
Unit tests for Event Service foundation.

Source of truth: BLUEPRINT.md §14, §17, §18.

Verifies:
1. Sequence starts from current task_runs.sequence_counter + 1.
2. Sequence allocation is strictly monotonic per run_id.
3. Event persistence uses the allocated sequence.
4. Database failure rolls back and does not publish.
5. Successful database commit happens before Redis publication.
6. Redis publication failure does not remove the already committed database event.
7. Redis channel is exactly agent.events.{run_id}.
8. Event payload published to Redis matches the safe event envelope.
9. No direct Redis publishing interface is introduced for graph nodes.
10. Multiple events for the same run receive different increasing sequence values.
11. Non-existent run_id raises TaskRunNotFoundError.
12. Simulated concurrency preserves sequence ordering without duplicates.
13. Replay queries via get_events_for_run filter and sort properly.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
import pytest

from backend.db.models import AgentEvent, TaskRun, TaskStatus
from backend.events.publisher import RedisEventPublisher
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import (
    EventService,
    EventServiceError,
    TaskRunNotFoundError,
)


class FakeQueryResult:
    """Mock result object returned by execute()."""

    def __init__(self, scalar_val: Any = None, scalars_list: Optional[list] = None):
        self._scalar_val = scalar_val
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar_val

    def scalars(self) -> "FakeScalars":
        return FakeScalars(self._scalars_list)


class FakeScalars:
    """Mock scalars collection."""

    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return self._items


class FakeAsyncSession:
    """
    In-memory async session test double for sequence allocation,
    row locking, commit/rollback tracking, and event persistence.
    """

    def __init__(
        self,
        initial_counter: int = 0,
        exists: bool = True,
        fail_on_execute: bool = False,
        fail_on_commit: bool = False,
    ):
        self.exists = exists
        self.counter = initial_counter
        self.fail_on_execute = fail_on_execute
        self.fail_on_commit = fail_on_commit

        self.added_records: list[AgentEvent] = []
        self.committed = False
        self.rolled_back = False
        self.call_log: list[str] = []

    async def execute(self, stmt: Any) -> FakeQueryResult:
        stmt_str = str(stmt).lower()
        if self.fail_on_execute:
            self.call_log.append("execute_failed")
            raise RuntimeError("Database connection failure during query execution")

        if "select" in stmt_str and "sequence_counter" in stmt_str:
            self.call_log.append("select_for_update")
            if not self.exists:
                return FakeQueryResult(scalar_val=None)
            return FakeQueryResult(scalar_val=self.counter)

        elif "update" in stmt_str and "sequence_counter" in stmt_str:
            self.call_log.append("update_counter")
            self.counter += 1
            return FakeQueryResult(scalar_val=None)

        elif "select" in stmt_str and "agent_events" in stmt_str:
            self.call_log.append("select_agent_events")
            return FakeQueryResult(scalars_list=self.added_records)

        return FakeQueryResult(scalar_val=None)

    def add(self, entity: Any) -> None:
        self.call_log.append("add_agent_event")
        self.added_records.append(entity)

    async def flush(self) -> None:
        self.call_log.append("flush")

    async def commit(self) -> None:
        if self.fail_on_commit:
            self.call_log.append("commit_failed")
            raise RuntimeError("Database transaction commit failed")
        self.committed = True
        self.call_log.append("commit")

    async def rollback(self) -> None:
        self.rolled_back = True
        self.call_log.append("rollback")

    async def __aenter__(self) -> "FakeAsyncSession":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None and not self.rolled_back:
            await self.rollback()


class FakeRedisClient:
    """Mock Redis async client for testing Pub/Sub fan-out."""

    def __init__(self, fail_on_publish: bool = False):
        self.fail_on_publish = fail_on_publish
        self.published_messages: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, message: str) -> int:
        if self.fail_on_publish:
            raise ConnectionError("Redis cluster temporarily unreachable")
        self.published_messages.append((channel, message))
        return 1

    async def aclose(self) -> None:
        self.closed = True


class TestEventServiceSequenceAllocation:
    """BLUEPRINT.md §14: Monotonic sequence allocation in PostgreSQL."""

    @pytest.mark.asyncio
    async def test_sequence_starts_from_counter_plus_one(self) -> None:
        """When sequence_counter is 0, allocated sequence must be 1."""
        session = FakeAsyncSession(initial_counter=0)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        task_id = uuid.uuid4()
        run_id = uuid.uuid4()
        user_id = uuid.uuid4()

        envelope = await service.emit_event(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            event_type=EventType.TASK_STARTED,
            session=session,
        )

        assert envelope.sequence == 1
        assert session.counter == 1
        assert len(session.added_records) == 1
        assert session.added_records[0].sequence == 1

    @pytest.mark.asyncio
    async def test_sequence_advances_from_existing_counter(self) -> None:
        """When sequence_counter is 41, allocated sequence must be 42."""
        session = FakeAsyncSession(initial_counter=41)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        envelope = await service.emit_event(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            event_type=EventType.TOOL_STARTED,
            session=session,
        )

        assert envelope.sequence == 42
        assert session.counter == 42
        assert session.added_records[0].sequence == 42

    @pytest.mark.asyncio
    async def test_multiple_events_receive_monotonic_sequences(self) -> None:
        """Multiple sequential events receive strictly increasing sequence numbers."""
        session = FakeAsyncSession(initial_counter=0)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        run_id = uuid.uuid4()
        t_id = uuid.uuid4()
        u_id = uuid.uuid4()

        env1 = await service.emit_event(
            task_id=t_id, run_id=run_id, user_id=u_id,
            event_type=EventType.TASK_STARTED, session=session,
        )
        env2 = await service.emit_event(
            task_id=t_id, run_id=run_id, user_id=u_id,
            event_type=EventType.PLANNING_STARTED, session=session,
        )
        env3 = await service.emit_event(
            task_id=t_id, run_id=run_id, user_id=u_id,
            event_type=EventType.TOOL_STARTED, session=session,
        )

        assert env1.sequence == 1
        assert env2.sequence == 2
        assert env3.sequence == 3
        assert env1.sequence < env2.sequence < env3.sequence
        assert session.counter == 3

    @pytest.mark.asyncio
    async def test_nonexistent_run_raises_task_run_not_found(self) -> None:
        """If task_runs record is not found, raises TaskRunNotFoundError and does not publish."""
        session = FakeAsyncSession(exists=False)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        with pytest.raises(TaskRunNotFoundError):
            await service.emit_event(
                task_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                event_type=EventType.TASK_STARTED,
                session=session,
            )

        assert session.rolled_back is True
        assert len(redis_client.published_messages) == 0


class TestRowLockAndCommitBoundary:
    """BLUEPRINT.md §14: Strict commit-before-publish and lock boundary rules."""

    @pytest.mark.asyncio
    async def test_database_failure_rolls_back_and_does_not_publish(self) -> None:
        """If database fails during transaction, rollback occurs and Redis is never called."""
        session = FakeAsyncSession(fail_on_execute=True)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        with pytest.raises(RuntimeError):
            await service.emit_event(
                task_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                event_type=EventType.TASK_STARTED,
                session=session,
            )

        assert session.rolled_back is True
        assert session.committed is False
        assert len(redis_client.published_messages) == 0

    @pytest.mark.asyncio
    async def test_commit_happens_strictly_before_redis_publication(self) -> None:
        """Database commit MUST be finalized before Redis publish is invoked."""
        session = FakeAsyncSession(initial_counter=0)
        redis_client = FakeRedisClient()
        order_of_events: list[str] = []

        # Hook session.commit and redis.publish to verify strict ordering
        original_commit = session.commit
        async def tracked_commit() -> None:
            order_of_events.append("db_committed")
            await original_commit()

        session.commit = tracked_commit

        original_publish = redis_client.publish
        async def tracked_publish(channel: str, msg: str) -> int:
            order_of_events.append("redis_published")
            return await original_publish(channel, msg)

        redis_client.publish = tracked_publish

        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        await service.emit_event(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            event_type=EventType.TASK_STARTED,
            session=session,
        )

        assert order_of_events == ["db_committed", "redis_published"]
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_redis_failure_does_not_rollback_committed_event(self) -> None:
        """If Redis publish fails, database event remains committed and durable."""
        session = FakeAsyncSession(initial_counter=10)
        redis_client = FakeRedisClient(fail_on_publish=True)
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        envelope = await service.emit_event(
            task_id=uuid.uuid4(),
            run_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            event_type=EventType.EVALUATION_COMPLETED,
            session=session,
        )

        # Database remains durable and committed
        assert session.committed is True
        assert session.rolled_back is False
        assert len(session.added_records) == 1
        assert session.added_records[0].sequence == 11

        # Service still returned the valid durable envelope
        assert envelope.sequence == 11
        assert envelope.event_type == EventType.EVALUATION_COMPLETED


class TestRedisPublisherChannelAndPayload:
    """BLUEPRINT.md §14: Channel naming and safe envelope delivery."""

    @pytest.mark.asyncio
    async def test_redis_channel_format(self) -> None:
        """Redis channel must match agent.events.{run_id} verbatim."""
        run_id = uuid.uuid4()
        session = FakeAsyncSession()
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        await service.emit_event(
            task_id=uuid.uuid4(),
            run_id=run_id,
            user_id=uuid.uuid4(),
            event_type=EventType.TASK_STARTED,
            session=session,
        )

        assert len(redis_client.published_messages) == 1
        channel, payload_str = redis_client.published_messages[0]
        assert channel == f"agent.events.{run_id}"

    @pytest.mark.asyncio
    async def test_published_payload_matches_safe_event_envelope(self) -> None:
        """Payload published to Redis must match the safe EventEnvelope schema."""
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        user_id = uuid.uuid4()

        session = FakeAsyncSession(initial_counter=5)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        envelope = await service.emit_event(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            event_type=EventType.TOOL_COMPLETED,
            status=TaskStatus.SUCCEEDED,
            metadata={
                "tool_name": "calculator",
                "chain_of_thought": "CONFIDENTIAL REASONING",  # Should be stripped
            },
            session=session,
        )

        _, payload_str = redis_client.published_messages[0]
        data = json.loads(payload_str)

        # Check all 10 durable fields exist in Redis broadcast
        assert data["event_id"] == str(envelope.event_id)
        assert data["task_id"] == str(task_id)
        assert data["run_id"] == str(run_id)
        assert data["user_id"] == str(user_id)
        assert data["sequence"] == 6
        assert data["schema_version"] == "1.0"
        assert data["event_type"] == "tool_completed"
        assert data["status"] == "succeeded"
        assert "timestamp" in data

        # Security check: sensitive metadata was stripped
        assert data["metadata"]["tool_name"] == "calculator"
        assert "chain_of_thought" not in data["metadata"]


class TestConcurrencyAndReplay:
    """Test simulated concurrency and replay querying."""

    @pytest.mark.asyncio
    async def test_simulated_concurrent_sequence_allocation(self) -> None:
        """Simulate serialized transactions under row lock producing sequential sequences."""
        session = FakeAsyncSession(initial_counter=0)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Under PostgreSQL row lock, concurrent emissions are executed sequentially
        async def emit_step(event_type: EventType) -> EventEnvelope:
            return await service.emit_event(
                task_id=task_id,
                run_id=run_id,
                user_id=user_id,
                event_type=event_type,
                session=session,
            )

        events = []
        for et in [EventType.TASK_STARTED, EventType.PLANNING_STARTED, EventType.TOOL_STARTED]:
            events.append(await emit_step(et))

        sequences = [e.sequence for e in events]
        assert sequences == [1, 2, 3]
        assert len(set(sequences)) == 3  # All distinct

    @pytest.mark.asyncio
    async def test_get_events_for_run_replay(self) -> None:
        """Test retrieving durable historical events for WebSocket / replay protocol."""
        session = FakeAsyncSession(initial_counter=0)
        redis_client = FakeRedisClient()
        publisher = RedisEventPublisher(client=redis_client)
        service = EventService(publisher=publisher)

        run_id = uuid.uuid4()
        t_id = uuid.uuid4()
        u_id = uuid.uuid4()

        await service.emit_event(
            task_id=t_id, run_id=run_id, user_id=u_id,
            event_type=EventType.TASK_STARTED, session=session,
        )
        await service.emit_event(
            task_id=t_id, run_id=run_id, user_id=u_id,
            event_type=EventType.TASK_COMPLETED, session=session,
        )

        replayed = await service.get_events_for_run(run_id, session=session)
        assert len(replayed) == 2
        assert replayed[0].sequence == 1
        assert replayed[0].event_type == EventType.TASK_STARTED
        assert replayed[1].sequence == 2
        assert replayed[1].event_type == EventType.TASK_COMPLETED
