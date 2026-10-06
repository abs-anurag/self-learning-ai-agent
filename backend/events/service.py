"""
Event Service foundation with atomic sequence allocation and Redis streaming.

Source of truth: BLUEPRINT.md §1, §4, §14, §17, §18.

Design rules:
- Strictly implements sequence allocation per §14:
  1. Begin PostgreSQL transaction.
  2. SELECT sequence_counter FROM task_runs WHERE id = :run_id FOR UPDATE;
  3. Compute next_sequence = sequence_counter + 1.
  4. UPDATE task_runs SET sequence_counter = :next_sequence WHERE id = :run_id;
  5. Insert into agent_events: (event_id, task_id, run_id, user_id, sequence,
     schema_version, timestamp, event_type, status, metadata).
  6. Commit transaction.
  7. Post-commit: publish JSON envelope to Redis channel agent.events.{run_id}.
- Row-Lock Boundary Rule:
  The row lock on task_runs is held ONLY during steps 2 through 6.
  The lock is NEVER held while publishing to Redis or waiting for external I/O.
- If Redis publication fails, the database transaction is already committed;
  the event remains durable.
- If PostgreSQL fails, the transaction is rolled back and no Redis publish occurs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.core.logging import get_logger
from backend.db.models import AgentEvent, TaskRun, TaskStatus
from backend.db.session import _get_async_session_factory
from backend.events.publisher import EventPublisher, RedisEventPublisher
from backend.events.schema import (
    EventCreate,
    EventEnvelope,
    EventType,
    sanitize_metadata,
)

logger = get_logger(__name__)


# -- Exceptions --------------------------------------------------


class EventServiceError(Exception):
    """Base exception for Event Service operations."""
    pass


class TaskRunNotFoundError(EventServiceError):
    """Raised when the target task_runs record does not exist for sequence allocation."""
    pass


# -- Event Service -----------------------------------------------


class EventService:
    """
    Event Service layer responsible for transactional persistence,
    monotonic sequence allocation in PostgreSQL, and post-commit
    live broadcasting via Redis Pub/Sub.
    """

    def __init__(
        self,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        publisher: Optional[EventPublisher] = None,
    ) -> None:
        self.session_factory = session_factory or _get_async_session_factory()
        self.publisher = publisher or RedisEventPublisher()

    async def emit_event(
        self,
        *,
        task_id: Union[uuid.UUID, str],
        run_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        event_type: Union[EventType, str],
        status: Union[TaskStatus, str] = TaskStatus.RUNNING,
        metadata: Optional[dict[str, Any]] = None,
        event_id: Optional[Union[uuid.UUID, str]] = None,
        timestamp: Optional[datetime] = None,
        schema_version: str = "1.0",
        session: Optional[AsyncSession] = None,
    ) -> EventEnvelope:
        """
        Record and publish a durable telemetry event.

        Allocates the next monotonic sequence number in PostgreSQL under a row lock,
        commits the database transaction, and publishes the safe event envelope to Redis.
        """
        task_uuid = uuid.UUID(str(task_id))
        run_uuid = uuid.UUID(str(run_id))
        user_uuid = uuid.UUID(str(user_id))
        event_uuid = uuid.UUID(str(event_id)) if event_id else uuid.uuid4()

        event_type_obj = EventType(event_type) if isinstance(event_type, str) else event_type
        if isinstance(status, str):
            status_lower = status.lower().strip()
            if status_lower == "completed":
                raise ValueError("Status 'completed' is strictly forbidden. Use 'succeeded' or 'failed'.")
            status_obj = TaskStatus(status_lower)
        else:
            status_obj = status

        event_timestamp = timestamp or datetime.now(timezone.utc)
        if event_timestamp.tzinfo is None:
            event_timestamp = event_timestamp.replace(tzinfo=timezone.utc)

        clean_metadata = sanitize_metadata(metadata or {})

        if session is not None:
            return await self._persist_and_publish(
                session=session,
                event_uuid=event_uuid,
                task_uuid=task_uuid,
                run_uuid=run_uuid,
                user_uuid=user_uuid,
                event_type_obj=event_type_obj,
                status_obj=status_obj,
                clean_metadata=clean_metadata,
                event_timestamp=event_timestamp,
                schema_version=schema_version,
            )
        else:
            async with self.session_factory() as local_session:
                return await self._persist_and_publish(
                    session=local_session,
                    event_uuid=event_uuid,
                    task_uuid=task_uuid,
                    run_uuid=run_uuid,
                    user_uuid=user_uuid,
                    event_type_obj=event_type_obj,
                    status_obj=status_obj,
                    clean_metadata=clean_metadata,
                    event_timestamp=event_timestamp,
                    schema_version=schema_version,
                )

    # Alias for compatibility and ergonomic calling from nodes
    record_event = emit_event

    async def emit(
        self,
        event_create: EventCreate,
        session: Optional[AsyncSession] = None,
    ) -> EventEnvelope:
        """Emit an event using an EventCreate input schema."""
        return await self.emit_event(
            task_id=event_create.task_id,
            run_id=event_create.run_id,
            user_id=event_create.user_id,
            event_type=event_create.event_type,
            status=event_create.status,
            metadata=event_create.metadata,
            event_id=event_create.event_id,
            timestamp=event_create.timestamp,
            schema_version=event_create.schema_version,
            session=session,
        )

    async def _persist_and_publish(
        self,
        *,
        session: AsyncSession,
        event_uuid: uuid.UUID,
        task_uuid: uuid.UUID,
        run_uuid: uuid.UUID,
        user_uuid: uuid.UUID,
        event_type_obj: EventType,
        status_obj: TaskStatus,
        clean_metadata: dict[str, Any],
        event_timestamp: datetime,
        schema_version: str,
    ) -> EventEnvelope:
        """
        Execute atomic sequence allocation, insert, commit, and post-commit publish.
        """
        # --- 1. Database Transaction Boundary ---
        try:
            # 2. Lock task_runs row: SELECT sequence_counter FROM task_runs WHERE id = :run_id FOR UPDATE;
            stmt = (
                select(TaskRun.sequence_counter)
                .where(TaskRun.id == run_uuid)
                .with_for_update()
            )
            result = await session.execute(stmt)
            current_counter = result.scalar_one_or_none()

            if current_counter is None:
                raise TaskRunNotFoundError(
                    f"TaskRun '{run_uuid}' not found. Cannot allocate sequence."
                )

            # 3. Compute next sequence
            next_sequence = current_counter + 1

            # 4. Update counter: UPDATE task_runs SET sequence_counter = :next_sequence WHERE id = :run_id;
            update_stmt = (
                update(TaskRun)
                .where(TaskRun.id == run_uuid)
                .values(sequence_counter=next_sequence)
            )
            await session.execute(update_stmt)

            # 5. Insert into agent_events
            db_event = AgentEvent(
                event_id=event_uuid,
                task_id=task_uuid,
                run_id=run_uuid,
                user_id=user_uuid,
                sequence=next_sequence,
                schema_version=schema_version,
                timestamp=event_timestamp,
                event_type=event_type_obj.value,
                status=status_obj.value,
                metadata_=clean_metadata,
            )
            session.add(db_event)
            await session.flush()

            # 6. Commit transaction -- ROW LOCK RELEASED HERE
            await session.commit()

        except Exception:
            await session.rollback()
            raise

        # --- 2. Post-Commit Live Fan-Out Boundary ---
        # The row lock has been released. External publication cannot delay the DB lock.
        envelope = EventEnvelope(
            event_id=event_uuid,
            task_id=task_uuid,
            run_id=run_uuid,
            user_id=user_uuid,
            sequence=next_sequence,
            schema_version=schema_version,
            timestamp=event_timestamp,
            event_type=event_type_obj,
            status=status_obj,
            metadata=clean_metadata,
        )

        try:
            if self.publisher is not None:
                await self.publisher.publish_event(envelope)
        except Exception as pub_exc:
            logger.warning(
                "Redis publication failed for event %s (run_id %s): %s",
                event_uuid,
                run_uuid,
                type(pub_exc).__name__,
            )

        return envelope

    async def get_events_for_run(
        self,
        run_id: Union[uuid.UUID, str],
        *,
        after_sequence: int = 0,
        limit: int = 500,
        session: Optional[AsyncSession] = None,
    ) -> list[EventEnvelope]:
        """
        Query durable events from PostgreSQL for replay.
        Source: BLUEPRINT.md §14 (Replay Protocol).
        """
        run_uuid = uuid.UUID(str(run_id))
        stmt = (
            select(AgentEvent)
            .where(AgentEvent.run_id == run_uuid, AgentEvent.sequence > after_sequence)
            .order_by(AgentEvent.sequence.asc())
            .limit(limit)
        )

        if session is not None:
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [EventEnvelope.from_db_model(rec) for rec in records]
        else:
            async with self.session_factory() as local_session:
                result = await local_session.execute(stmt)
                records = result.scalars().all()
                return [EventEnvelope.from_db_model(rec) for rec in records]
