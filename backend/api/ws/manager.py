from __future__ import annotations

import asyncio
import contextlib
import inspect
import uuid
from typing import AsyncIterator, Optional

from fastapi import Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocketState

from backend.api.dependencies import get_db, get_db_session
from backend.api.security.auth import authenticate_api_key
from backend.core.logging import get_logger
from backend.db.models import Task, TaskRun, TaskStatus, User
from backend.db.session import async_session_factory
from backend.events.publisher import RedisEventPublisher
from backend.events.schema import EventEnvelope
from backend.events.service import EventService

logger = get_logger(__name__)


class BufferOverflowError(Exception):
    """Raised when the WebSocket event queue exceeds buffer capacity."""
    pass


class WebSocketManager:
    """Manager for the SUBSCRIBE-THEN-REPLAY WebSocket protocol.

    Implements the exact flow required by BLUEPRINT.md Section 14, Section 15:
    1. Authenticate via API key query parameter.
    2. Authorize the user owns the requested task.
    3. Resolve the active run (status pending or running).
    4. Subscribe to Redis channel agent.events.{run_id} BEFORE PostgreSQL replay.
    5. Buffer live events in asyncio.Queue(maxsize=100).
    6. Replay durable events from PostgreSQL (sequence > last_sequence, ASC, limit=500).
    7. If buffer reaches capacity before replay completes, close with code 1013.
    8. Drain and reconcile buffer while preserving strict monotonic sequence ordering.
    9. Continue forwarding live events with gap reconciliation from PostgreSQL.
    10. Close with 1008 on auth/authorization errors, 1011 on internal errors.
    """

    REPLAY_BATCH_SIZE = 500
    REPLAY_BUFFER_SIZE = 100
    CLOSE_AUTH = 1008
    CLOSE_BUFFER_OVERFLOW = 1013
    CLOSE_INTERNAL = 1011

    def __init__(
        self,
        event_service: Optional[EventService] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        self.event_service = event_service or EventService()
        self.session_factory = session_factory or async_session_factory

    @contextlib.asynccontextmanager
    async def _get_db_session(self, websocket: WebSocket) -> AsyncIterator[AsyncSession]:
        """Resolve database session using FastAPI dependency overrides or factory."""
        override = None
        if hasattr(websocket, "app") and hasattr(websocket.app, "dependency_overrides"):
            override = (
                websocket.app.dependency_overrides.get(get_db_session)
                or websocket.app.dependency_overrides.get(get_db)
            )
        if override is not None:
            if inspect.isasyncgenfunction(override):
                async with contextlib.asynccontextmanager(override)() as session:
                    yield session
            else:
                res = override()
                if hasattr(res, "__aenter__"):
                    async with res as session:
                        yield session
                else:
                    yield res
        else:
            async with self.session_factory() as session:
                yield session

    async def _redis_subscriber(
        self,
        channel: str,
        queue: asyncio.Queue[EventEnvelope],
        subscribed_event: asyncio.Event,
        overflow_event: asyncio.Event,
        subscriber_failed: asyncio.Event,
        websocket: WebSocket,
    ) -> None:
        """Background task that receives live events from Redis and buffers them.

        Confirms subscription before signaling subscribed_event.
        If queue reaches maxsize, signals overflow_event and closes with code 1013.
        If subscription or client fails unexpectedly, signals subscriber_failed.
"""
        pubsub = None
        try:
            publisher = self.event_service.publisher
            if hasattr(publisher, "get_client"):
                client = await publisher.get_client()
                pubsub = client.pubsub()
            else:
                pubsub = publisher.pubsub()

            await pubsub.subscribe(channel)
            subscribed_event.set()
        except Exception as startup_exc:
            logger.error(
                "Redis subscription startup failure: %s",
                type(startup_exc).__name__,
            )
            subscriber_failed.set()
            subscribed_event.set()
            return

        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if msg and msg.get("type") == "message":
                    payload = msg["data"]
                    try:
                        if isinstance(payload, bytes):
                            payload = payload.decode("utf-8")
                        if isinstance(payload, str):
                            envelope = EventEnvelope.model_validate_json(payload)
                        elif isinstance(payload, dict):
                            envelope = EventEnvelope.model_validate(payload)
                        elif isinstance(payload, EventEnvelope):
                            envelope = payload
                        else:
                            continue
                    except Exception:
                        continue
                    try:
                        queue.put_nowait(envelope)
                    except asyncio.QueueFull:
                        overflow_event.set()
                        logger.warning("Buffer overflow detected in subscriber, queue size: %d", queue.qsize())
                        break
                await asyncio.sleep(0.001)
        except asyncio.CancelledError:
            pass
        except Exception as runtime_exc:
            logger.error(
                "Redis subscriber runtime failure: %s",
                type(runtime_exc).__name__,
            )
            subscriber_failed.set()
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe(channel)
                except Exception:
                    pass
                try:
                    await pubsub.close()
                except Exception:
                    pass

    async def _replay_events(
        self,
        run_id: str,
        websocket: WebSocket,
        overflow_event: asyncio.Event,
        subscriber_failed: asyncio.Event,
        db_session: Optional[AsyncSession] = None,
        start_sequence: int = 0,
    ) -> int:
        """Replay durable events from PostgreSQL ordered ASC in batches of <= 500."""
        last_seq = start_sequence
        while True:
            if overflow_event.is_set():
                raise BufferOverflowError("Buffer overflow during replay")
            if subscriber_failed.is_set():
                raise RuntimeError("Subscriber failed during replay")

            batch = await self.event_service.get_events_for_run(
                run_id,
                after_sequence=last_seq,
                limit=self.REPLAY_BATCH_SIZE,
                session=db_session,
            )
            if not batch:
                break

            for env in batch:
                if overflow_event.is_set():
                    raise BufferOverflowError("Buffer overflow during replay")
                if subscriber_failed.is_set():
                    raise RuntimeError("Subscriber failed during replay")
                if env.sequence <= last_seq:
                    continue
                await websocket.send_json(env.model_dump(mode="json"))
                last_seq = env.sequence

            if len(batch) < self.REPLAY_BATCH_SIZE:
                break
        return last_seq

    async def _reconcile_pending(
        self,
        run_id: str,
        pending: dict[int, EventEnvelope],
        websocket: WebSocket,
        last_seq: int,
        db_session: Optional[AsyncSession] = None,
    ) -> int:
        """Reconcile buffered events ensuring strict ascending sequence with no gaps or duplicates."""
        while pending:
            min_seq = min(pending.keys())
            if min_seq <= last_seq:
                del pending[min_seq]
                continue

            if min_seq == last_seq + 1:
                env = pending.pop(min_seq)
                await websocket.send_json(env.model_dump(mode="json"))
                last_seq = min_seq
            else:
                # Gap detected: min_seq > last_seq + 1
                # Fetch missing durable events from PostgreSQL
                gap_batch = await self.event_service.get_events_for_run(
                    run_id,
                    after_sequence=last_seq,
                    limit=min_seq - last_seq - 1,
                    session=db_session,
                )
                if gap_batch:
                    for g_env in gap_batch:
                        if g_env.sequence > last_seq:
                            await websocket.send_json(g_env.model_dump(mode="json"))
                            last_seq = g_env.sequence
                            pending.pop(last_seq, None)
                    continue
                else:
                    # A Redis event exists for a later sequence, but the durable
                    # PostgreSQL source has no event for the missing sequence.
                    # Never skip a sequence because PostgreSQL is the source of truth.
                    raise RuntimeError(
                        f"Unresolved event sequence gap for run {run_id}: "
                        f"expected {last_seq + 1}, received {min_seq}"
                    )

        return last_seq

    async def handle(
        self,
        websocket: WebSocket,
        task_id: str,
        api_key: Optional[str] = Query(None, description="API key for WebSocket authentication"),
        last_sequence: int = Query(default=0, ge=0, description="Replay events starting after this sequence"),
    ) -> None:
        """FastAPI entry-point for the WebSocket endpoint."""
        await websocket.accept()

        overflow_event = asyncio.Event()
        subscriber_failed = asyncio.Event()

        if not api_key or not api_key.strip():
            await websocket.close(code=self.CLOSE_AUTH)
            return

        try:
            task_uuid = uuid.UUID(str(task_id))
        except (ValueError, TypeError):
            await websocket.close(code=self.CLOSE_AUTH)
            return

        subscriber = None
        try:
            async with self._get_db_session(websocket) as db_session:
                user = await authenticate_api_key(api_key, db_session)
                if user is None:
                    await websocket.close(code=self.CLOSE_AUTH)
                    return

                task_res = await db_session.execute(
                    select(Task).where(Task.id == task_uuid)
                )
                task: Optional[Task] = task_res.scalar_one_or_none()
                if not task or task.user_id != user.id:
                    await websocket.close(code=self.CLOSE_AUTH)
                    return

                run_res = await db_session.execute(
                    select(TaskRun)
                    .where(
                        TaskRun.task_id == task_uuid,
                        TaskRun.status.in_([TaskStatus.PENDING.value, TaskStatus.RUNNING.value]),
                    )
                    .order_by(TaskRun.created_at.desc())
                    .limit(1)
                )
                task_run: Optional[TaskRun] = run_res.scalar_one_or_none()
                if not task_run:
                    await websocket.close(code=self.CLOSE_AUTH)
                    return
                run_id = str(task_run.id)

                channel = RedisEventPublisher.get_channel(run_id)
                buffer: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=self.REPLAY_BUFFER_SIZE)
                subscribed_event = asyncio.Event()

                subscriber = asyncio.create_task(
                    self._redis_subscriber(
                        channel,
                        buffer,
                        subscribed_event,
                        overflow_event,
                        subscriber_failed,
                        websocket,
                    )
                )

                # Guarantee Redis subscription is established before PostgreSQL replay
                await subscribed_event.wait()
                if subscriber_failed.is_set():
                    raise RuntimeError("Redis subscription initialization failed")

                # Replay PostgreSQL durable events (ordered ASC, batch size <= 500)
                last_seq = await self._replay_events(
                    run_id,
                    websocket,
                    overflow_event,
                    subscriber_failed,
                    db_session,
                    start_sequence=last_sequence,
                )

                # Reconcile any buffered events that arrived during replay
                pending: dict[int, EventEnvelope] = {}
                while not buffer.empty():
                    e = buffer.get_nowait()
                    if e.sequence > last_seq:
                        pending[e.sequence] = e
                last_seq = await self._reconcile_pending(
                    run_id, pending, websocket, last_seq, db_session
                )

            # Initialise `pending` before the live-forwarding loop so it is
            # never referenced before assignment on the first timeout iteration.
            pending: dict[int, EventEnvelope] = {}

            # Live event forwarding loop
            while True:
                if overflow_event.is_set():
                    raise BufferOverflowError("Buffer capacity exceeded")
                if subscriber_failed.is_set():
                    raise RuntimeError("Redis subscriber runtime failure")

                try:
                    env = await asyncio.wait_for(buffer.get(), timeout=0.2)
                    if env.sequence > last_seq:
                        pending[env.sequence] = env

                    while not buffer.empty():
                        e = buffer.get_nowait()
                        if e.sequence > last_seq:
                            pending[e.sequence] = e

                    if pending:
                        async with self._get_db_session(websocket) as live_db_session:
                            last_seq = await self._reconcile_pending(
                                run_id, pending, websocket, last_seq, live_db_session
                            )
                except asyncio.TimeoutError:
                    if overflow_event.is_set():
                        raise BufferOverflowError("Buffer capacity exceeded")
                    if subscriber.done():
                        exc = subscriber.exception()
                        if exc is not None:
                            raise exc
                        break
        except BufferOverflowError:
            if (
                websocket.client_state != WebSocketState.DISCONNECTED
                and websocket.application_state != WebSocketState.DISCONNECTED
            ):
                try:
                    await websocket.close(code=self.CLOSE_BUFFER_OVERFLOW)
                except Exception:
                    pass
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            if overflow_event.is_set():
                if (
                    websocket.client_state != WebSocketState.DISCONNECTED
                    and websocket.application_state != WebSocketState.DISCONNECTED
                ):
                    try:
                        await websocket.close(code=self.CLOSE_BUFFER_OVERFLOW)
                    except Exception:
                        pass
            else:
                logger.error("Unexpected error in WebSocket handler: %s", exc, exc_info=True)
                if (
                    websocket.client_state != WebSocketState.DISCONNECTED
                    and websocket.application_state != WebSocketState.DISCONNECTED
                ):
                    try:
                        await websocket.close(code=self.CLOSE_INTERNAL)
                    except Exception:
                        pass
        finally:
            if subscriber is not None and not subscriber.done():
                subscriber.cancel()
                try:
                    await subscriber
                except (asyncio.CancelledError, Exception):
                    pass


ws_manager = WebSocketManager()
