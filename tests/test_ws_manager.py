"""
Unit and integration tests for WebSocket Manager (SUBSCRIBE-THEN-REPLAY).

Source of truth: BLUEPRINT.md §1, §14, §15, §17, §18.

Verifies:
1. Valid WebSocket authentication via api_key query parameter.
2. Missing or empty API key closes connection with code 1008.
3. Invalid API key closes connection with code 1008.
4. Unauthorized task ownership closes connection with code 1008.
5. Nonexistent task or invalid task UUID closes connection with code 1008.
6. Missing active run (only completed/failed runs) closes connection with code 1008.
7. Full PostgreSQL replay delivers all durable events in ascending order.
8. Partial replay via last_sequence query param delivers only events with sequence > last_sequence.
9. Replay of >500 events verifies multi-batch pagination (batch size 500).
10. Redis subscription is established BEFORE PostgreSQL replay query executes.
11. Events arriving during PostgreSQL replay are buffered and drained without loss.
12. Strict monotonic sequence ordering is preserved and duplicate replayed sequences are discarded.
13. Live events arriving after replay are forwarded to the client in real time.
14. Bounded buffer overflow (>100 events) closes connection with code 1013.
15. Internal server errors during replay/handling close connection with code 1011.
16. Graceful client disconnect cleans up background tasks and unsubscribes Redis PubSub.
17. Telemetry sanitization ensures no secrets, API keys, or judge_reasoning are streamed.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.api.dependencies import get_db, get_db_session
from backend.api.main import app
from backend.api.security.auth import hash_api_key
from backend.api.ws.manager import BufferOverflowError, WebSocketManager, ws_manager
from backend.db.models import AgentEvent, Task, TaskRun, TaskStatus, User
from backend.events.schema import EventEnvelope, EventType
from tests.test_api_auth import FullInMemoryAsyncSession, InMemoryDB, MockQueryResult


class WSAsyncSession(FullInMemoryAsyncSession):
    """Extended test session that supports limit on agent_events queries and logs operations."""

    def __init__(self, db: InMemoryDB, call_log: Optional[list[str]] = None) -> None:
        super().__init__(db)
        self.call_log = call_log if call_log is not None else []
        self.fail_on_agent_events: bool = False
        self.block_replay_event: Optional[asyncio.Event] = None

    async def execute(self, stmt: Any) -> MockQueryResult:
        stmt_str = str(stmt).lower()

        if "from agent_events" in stmt_str:
            self.call_log.append("replay_query")
            if self.block_replay_event is not None:
                await self.block_replay_event.wait()
            if self.fail_on_agent_events:
                raise RuntimeError("Database connection failure during replay")

            params: dict[str, Any] = {}
            try:
                params = dict(stmt.compile().params)
            except Exception:
                params = getattr(stmt, "_params", {}) or {}

            def get_p(prefix: str, default: Any = None) -> Any:
                for k, v in params.items():
                    if k == prefix or k.startswith(f"{prefix}_"):
                        return v
                return default

            run_id = get_p("run_id")
            user_id = get_p("user_id")
            after_seq = get_p("sequence", 0) or 0
            limit_val = get_p("param")

            evts = list(self.db.agent_events.values())
            if run_id:
                evts = [e for e in evts if str(e.run_id) == str(run_id)]
            if user_id:
                evts = [e for e in evts if str(e.user_id) == str(user_id)]
            if after_seq:
                evts = [e for e in evts if e.sequence > after_seq]

            evts.sort(key=lambda x: x.sequence, reverse=("desc" in stmt_str))
            if limit_val and isinstance(limit_val, int):
                evts = evts[:limit_val]

            single_evt = evts[0] if evts else None
            return MockQueryResult(
                scalar_value=single_evt,
                scalars_list=evts,
            )

        # Handle TaskRun status filtering for WebSocket queries
        if "from task_runs" in stmt_str:
            # Check if this is a filtered status query (for active runs only)
            if "task_runs.status" in stmt_str and " in " in stmt_str:
                # Log that we processed an active run query
                self.call_log.append("active_run_query")
                task_id = None
                user_id = None
                params: dict[str, Any] = {}
                try:
                    params = dict(stmt.compile().params)
                except Exception:
                    params = getattr(stmt, "_params", {}) or {}

                def get_p(prefix: str, default: Any = None) -> Any:
                    for k, v in params.items():
                        if k == prefix or k.startswith(f"{prefix}_"):
                            return v
                    return default

                task_id = get_p("task_id")
                # Filter to only PENDING and RUNNING runs
                runs = [
                    r for r in self.db.task_runs.values()
                    if r.status in (TaskStatus.PENDING.value, TaskStatus.RUNNING.value)
                ]
                if task_id:
                    runs = [r for r in runs if r.task_id == task_id]

                runs.sort(key=lambda x: x.created_at, reverse=True)
                run_single = runs[0] if runs else None
                return MockQueryResult(scalar_value=run_single, scalars_list=runs)

        return await super().execute(stmt)


class MockPubSub:
    """In-memory Redis PubSub mock for deterministic WebSocket testing."""

    def __init__(self, call_log: Optional[list[str]] = None) -> None:
        self.subscribed_channels: list[str] = []
        self.unsubscribed_channels: list[str] = []
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.closed: bool = False
        self.subscribed_event = threading.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.call_log = call_log if call_log is not None else []

    async def subscribe(self, channel: str) -> None:
        self.loop = asyncio.get_running_loop()
        self.call_log.append("subscribe")
        self.subscribed_channels.append(channel)
        self.subscribed_event.set()

    async def unsubscribe(self, channel: str) -> None:
        self.call_log.append("unsubscribe")
        self.unsubscribed_channels.append(channel)

    async def close(self) -> None:
        self.call_log.append("pubsub_close")
        self.closed = True

    async def get_message(
        self, ignore_subscribe_messages: bool = True, timeout: float = 0.1
    ) -> Optional[dict[str, Any]]:
        try:
            return await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def publish_envelope(self, envelope: EventEnvelope) -> None:
        self.subscribed_event.wait(timeout=3.0)
        data = envelope.model_dump_json()
        msg = {"type": "message", "data": data}
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)
        else:
            self.queue.put_nowait(msg)


class MockPublisher:
    """Mock RedisEventPublisher for testing."""

    def __init__(self, pubsub_instance: Optional[MockPubSub] = None) -> None:
        self.pubsub_instance = pubsub_instance or MockPubSub()
        self.published_events: list[EventEnvelope] = []

    async def get_client(self) -> "MockPublisher":
        return self

    def pubsub(self) -> MockPubSub:
        return self.pubsub_instance

    async def publish_event(self, event: EventEnvelope) -> bool:
        self.published_events.append(event)
        self.pubsub_instance.publish_envelope(event)
        return True

    async def close(self) -> None:
        pass


def create_db_event(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    sequence: int,
    event_type: EventType = EventType.TOOL_STARTED,
    status: TaskStatus = TaskStatus.RUNNING,
    metadata: Optional[dict[str, Any]] = None,
) -> AgentEvent:
    """Helper to instantiate a valid AgentEvent entity."""
    return AgentEvent(
        event_id=uuid.uuid4(),
        task_id=task_id,
        run_id=run_id,
        user_id=user_id,
        sequence=sequence,
        schema_version="1.0",
        timestamp=datetime.now(timezone.utc),
        event_type=event_type.value,
        status=status.value,
        metadata_=metadata or {"step": sequence},
    )


def create_envelope(
    task_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    sequence: int,
    event_type: EventType = EventType.TOOL_STARTED,
    status: TaskStatus = TaskStatus.RUNNING,
    metadata: Optional[dict[str, Any]] = None,
) -> EventEnvelope:
    """Helper to instantiate a valid EventEnvelope."""
    return EventEnvelope(
        event_id=uuid.uuid4(),
        task_id=task_id,
        run_id=run_id,
        user_id=user_id,
        sequence=sequence,
        schema_version="1.0",
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        status=status,
        metadata=metadata or {"step": sequence},
    )


@pytest.fixture
def ws_test_env():
    """Fixture providing an isolated environment with in-memory DB and mock PubSub."""
    db = InMemoryDB()
    call_log: list[str] = []

    # Create user A
    key_a = "test_user_a_key_12345"
    hash_a = hash_api_key(key_a)
    user_a = User(
        id=uuid.uuid4(),
        api_key_hash=hash_a,
        display_name="User Alpha",
        created_at=datetime.now(timezone.utc),
    )
    db.add(user_a)

    # Create user B
    key_b = "test_user_b_key_67890"
    hash_b = hash_api_key(key_b)
    user_b = User(
        id=uuid.uuid4(),
        api_key_hash=hash_b,
        display_name="User Beta",
        created_at=datetime.now(timezone.utc),
    )
    db.add(user_b)

    # Create task for user A
    task_a = Task(
        id=uuid.uuid4(),
        user_id=user_a.id,
        goal="Perform analysis",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(task_a)

    # Create active run for task A
    run_a = TaskRun(
        id=uuid.uuid4(),
        task_id=task_a.id,
        user_id=user_a.id,
        status="running",
        iteration_count=1,
        sequence_counter=0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(run_a)

    # Setup mock publisher
    mock_pubsub = MockPubSub(call_log=call_log)
    mock_publisher = MockPublisher(pubsub_instance=mock_pubsub)

    original_publisher = ws_manager.event_service.publisher
    ws_manager.event_service.publisher = mock_publisher

    # Session reference holder so tests can toggle error behavior
    session_holder = {"session": None, "next_block_replay_event": None}

    async def override_get_db():
        session = WSAsyncSession(db, call_log=call_log)
        if session_holder["next_block_replay_event"] is not None:
            session.block_replay_event = session_holder["next_block_replay_event"]
            session_holder["next_block_replay_event"] = None
        session_holder["session"] = session
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db

    client = TestClient(app, raise_server_exceptions=False)

    yield {
        "client": client,
        "db": db,
        "user_a": user_a,
        "key_a": key_a,
        "user_b": user_b,
        "key_b": key_b,
        "task_a": task_a,
        "run_a": run_a,
        "pubsub": mock_pubsub,
        "publisher": mock_publisher,
        "call_log": call_log,
        "session_holder": session_holder,
    }

    ws_manager.event_service.publisher = original_publisher
    app.dependency_overrides.clear()


class TestWebSocketAuthAndAuthorization:
    """BLUEPRINT.md §15, §17: WebSocket Authentication and Task Ownership."""

    def test_ws_auth_valid(self, ws_test_env: dict[str, Any]) -> None:
        """Valid API key and owned task successfully establishes WebSocket connection."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        key_a = ws_test_env["key_a"]
        pubsub = ws_test_env["pubsub"]

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            # Subscription confirmed
            assert pubsub.subscribed_event.wait(timeout=2.0) is True
            assert f"agent.events.{ws_test_env['run_a'].id}" in pubsub.subscribed_channels

    def test_ws_auth_missing_key(self, ws_test_env: dict[str, Any]) -> None:
        """Missing API key query parameter must close connection with code 1008."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/{task_a.id}") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_auth_empty_key(self, ws_test_env: dict[str, Any]) -> None:
        """Empty or whitespace-only API key must close connection with code 1008."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key=   ") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_auth_invalid_key(self, ws_test_env: dict[str, Any]) -> None:
        """Invalid API key must close connection with code 1008."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key=invalid_api_key_token") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_unauthorized_task_ownership(self, ws_test_env: dict[str, Any]) -> None:
        """Accessing a task owned by another user must close connection with code 1008."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        user_b = ws_test_env["user_b"]
        key_a = ws_test_env["key_a"]

        # Task owned by User B
        task_b = Task(
            id=uuid.uuid4(),
            user_id=user_b.id,
            goal="Secret task",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        db.add(task_b)

        run_b = TaskRun(
            id=uuid.uuid4(),
            task_id=task_b.id,
            user_id=user_b.id,
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        db.add(run_b)

        # User A attempts to connect to User B's task
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/{task_b.id}?api_key={key_a}") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_nonexistent_task(self, ws_test_env: dict[str, Any]) -> None:
        """Connecting to a non-existent task ID must close connection with code 1008."""
        client = ws_test_env["client"]
        key_a = ws_test_env["key_a"]
        random_task_id = uuid.uuid4()

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/{random_task_id}?api_key={key_a}") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_invalid_uuid_task(self, ws_test_env: dict[str, Any]) -> None:
        """Connecting with a non-UUID task ID must close connection with code 1008."""
        client = ws_test_env["client"]
        key_a = ws_test_env["key_a"]

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(f"/ws/tasks/not-a-valid-uuid?api_key={key_a}") as ws:
                ws.receive_json()
        assert exc_info.value.code == 1008

    def test_ws_missing_active_run(self, ws_test_env: dict[str, Any]) -> None:
        """A task with no pending or running run must close connection with code 1008.

        Implementation: manager.py:303-305
        """
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]

        task_completed = Task(
            id=uuid.uuid4(),
            user_id=user_a.id,
            goal="Completed task",
            status="succeeded",
            created_at=datetime.now(timezone.utc),
        )
        db.add(task_completed)

        # Only succeeded run (not active - only PENDING/RUNNING are active)
        run_completed = TaskRun(
            id=uuid.uuid4(),
            task_id=task_completed.id,
            user_id=user_a.id,
            status=TaskStatus.SUCCEEDED.value,
            created_at=datetime.now(timezone.utc),
        )
        db.add(run_completed)

        # Connection closes with 1008
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(f"/ws/tasks/{task_completed.id}?api_key={key_a}") as ws:
                ws.receive_json()
        assert exc.value.code == 1008


class TestWebSocketReplayProtocol:
    """BLUEPRINT.md §14: Replay Protocol and Monotonic Sequence Ordering."""

    def test_ws_full_replay(self, ws_test_env: dict[str, Any]) -> None:
        """Full replay sends all durable PostgreSQL events in ascending sequence order."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]

        # Populate durable events in DB
        e1 = create_db_event(task_a.id, run_a.id, user_a.id, sequence=1, event_type=EventType.TASK_STARTED)
        e2 = create_db_event(task_a.id, run_a.id, user_a.id, sequence=2, event_type=EventType.PLANNING_STARTED)
        e3 = create_db_event(task_a.id, run_a.id, user_a.id, sequence=3, event_type=EventType.TOOL_STARTED)
        db.add(e1)
        db.add(e2)
        db.add(e3)

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            m1 = ws.receive_json()
            m2 = ws.receive_json()
            m3 = ws.receive_json()

            assert m1["sequence"] == 1
            assert m1["event_type"] == "task_started"
            assert m2["sequence"] == 2
            assert m2["event_type"] == "planning_started"
            assert m3["sequence"] == 3
            assert m3["event_type"] == "tool_started"

    def test_ws_partial_replay(self, ws_test_env: dict[str, Any]) -> None:
        """Partial replay via last_sequence replays only events with sequence > last_sequence."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]

        for seq in range(1, 6):
            db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=seq))

        # Reconnect with last_sequence=2 -> should receive sequences 3, 4, 5
        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}&last_sequence=2") as ws:
            m3 = ws.receive_json()
            m4 = ws.receive_json()
            m5 = ws.receive_json()

            assert m3["sequence"] == 3
            assert m4["sequence"] == 4
            assert m5["sequence"] == 5

    def test_ws_replay_more_than_500_events(self, ws_test_env: dict[str, Any]) -> None:
        """Replaying >500 events verifies multi-batch pagination (batch size 500)."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]

        total_events = 520
        for seq in range(1, total_events + 1):
            db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=seq))

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            received_seqs = []
            for _ in range(total_events):
                msg = ws.receive_json()
                received_seqs.append(msg["sequence"])

            assert received_seqs == list(range(1, total_events + 1))

    def test_ws_subscribe_before_replay(self, ws_test_env: dict[str, Any]) -> None:
        """Redis Pub/Sub subscription MUST occur before PostgreSQL replay query executes."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        key_a = ws_test_env["key_a"]
        call_log = ws_test_env["call_log"]

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            pass

        assert "subscribe" in call_log
        assert "replay_query" in call_log
        subscribe_index = call_log.index("subscribe")
        replay_index = call_log.index("replay_query")
        assert subscribe_index < replay_index, "Redis subscription must be established before PostgreSQL replay!"


class TestWebSocketBufferingAndLiveForwarding:
    """BLUEPRINT.md §14: Event Buffering, Drain, and Live Streaming."""

    def test_ws_events_arriving_during_replay(self, ws_test_env: dict[str, Any]) -> None:
        """Events arriving from Redis while replay is in progress are buffered and drained."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]
        pubsub = ws_test_env["pubsub"]

        # 1 durable event in DB
        db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=1))

        # Event 2 arriving via Redis
        live_e2 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=2)

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            pubsub.publish_envelope(live_e2)

            m1 = ws.receive_json()
            m2 = ws.receive_json()

            assert m1["sequence"] == 1
            assert m2["sequence"] == 2

    def test_ws_strict_sequence_ordering_and_deduplication(self, ws_test_env: dict[str, Any]) -> None:
        """Replay + buffered live events maintain strict ascending sequence with no duplicates."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]
        pubsub = ws_test_env["pubsub"]

        # Durable events in DB: sequence 1, 2, 3
        db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=1))
        db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=2))
        db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=3))

        # Overlapping live event 2 & 3 + new event 4 arriving on Redis
        live_e2 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=2)
        live_e3 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=3)
        live_e4 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=4)

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            pubsub.publish_envelope(live_e2)
            pubsub.publish_envelope(live_e3)
            pubsub.publish_envelope(live_e4)

            seqs = [
                ws.receive_json()["sequence"],
                ws.receive_json()["sequence"],
                ws.receive_json()["sequence"],
                ws.receive_json()["sequence"],
            ]

            assert seqs == [1, 2, 3, 4]

    def test_ws_live_forwarding(self, ws_test_env: dict[str, Any]) -> None:
        """Live events published after replay are forwarded to the client in real time."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]
        pubsub = ws_test_env["pubsub"]

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            # Publish event 1
            e1 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=1, event_type=EventType.TASK_STARTED)
            pubsub.publish_envelope(e1)
            m1 = ws.receive_json()
            assert m1["sequence"] == 1
            assert m1["event_type"] == "task_started"

            # Publish event 2
            e2 = create_envelope(task_a.id, run_a.id, user_a.id, sequence=2, event_type=EventType.TOOL_STARTED)
            pubsub.publish_envelope(e2)
            m2 = ws.receive_json()
            assert m2["sequence"] == 2
            assert m2["event_type"] == "tool_started"


class TestWebSocketCloseCodesAndCleanup:
    """BLUEPRINT.md §14, §15: Close Codes 1013, 1011, and Resource Cleanup."""

    def test_ws_buffer_overflow_close_1013(self, ws_test_env: dict[str, Any]) -> None:
        """Buffer overflow during replay closes connection with code 1013 (BLUEPRINT.md §660-681)."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]
        pubsub = ws_test_env["pubsub"]
        session_holder = ws_test_env["session_holder"]
        db = ws_test_env["db"]

        # Add some durable events so replay actually runs and checks overflow_event
        for seq in range(1, 6):
            db.add(create_db_event(task_a.id, run_a.id, user_a.id, sequence=seq))

        # Arrange: inject block event into session BEFORE websocket connects
        # so replay query blocks immediately when it runs
        block_event = asyncio.Event()
        session_holder["next_block_replay_event"] = block_event

        disconnect_code = None
        try:
            with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
                pubsub.subscribed_event.wait(timeout=2.0)

                # Act: pump 110 events while replay is blocked
                for seq in range(1, 111):
                    env = create_envelope(task_a.id, run_a.id, user_a.id, sequence=seq)
                    pubsub.publish_envelope(env)

                # Allow event loop to process events so subscriber fills buffer and triggers overflow
                time.sleep(3.0)

                # Unblock replay so it can detect overflow and close with 1013
                block_event.set()

                # Receive until disconnect or max attempts
                for _ in range(200):
                    try:
                        ws.receive_json()
                    except WebSocketDisconnect as exc:
                        disconnect_code = exc.code
                        break
        except WebSocketDisconnect as exc:
            disconnect_code = exc.code

        assert disconnect_code == 1013, (
            f"Expected 1013 on buffer overflow, got {disconnect_code}"
        )

    def test_ws_internal_error_close_1011(self, ws_test_env: dict[str, Any]) -> None:
        """Unexpected internal server error must close connection with code 1011."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        key_a = ws_test_env["key_a"]
        session_holder = ws_test_env["session_holder"]

        # Cause database session to fail on replay query
        original_execute = WSAsyncSession.execute

        async def failing_execute(self, stmt: Any):
            stmt_str = str(stmt).lower()
            if "from agent_events" in stmt_str:
                raise RuntimeError("Catastrophic DB failure")
            return await original_execute(self, stmt)

        WSAsyncSession.execute = failing_execute
        try:
            with pytest.raises(WebSocketDisconnect) as exc_info:
                with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
                    ws.receive_json()
            assert exc_info.value.code == 1011
        finally:
            WSAsyncSession.execute = original_execute

    def test_ws_graceful_disconnect_redis_cleanup(self, ws_test_env: dict[str, Any]) -> None:
        """Graceful client disconnect must cancel background subscriber and cleanup Redis."""
        client = ws_test_env["client"]
        task_a = ws_test_env["task_a"]
        key_a = ws_test_env["key_a"]
        call_log = ws_test_env["call_log"]
        pubsub = ws_test_env["pubsub"]

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            assert pubsub.subscribed_event.wait(timeout=2.0) is True

        # After exiting context manager, client disconnected
        time.sleep(0.1)
        channel = f"agent.events.{ws_test_env['run_a'].id}"
        assert channel in pubsub.unsubscribed_channels or pubsub.closed is True
        assert "unsubscribe" in call_log or "pubsub_close" in call_log

    def test_ws_no_prohibited_keys_in_streamed_events(self, ws_test_env: dict[str, Any]) -> None:
        """Event payloads streamed over WebSocket must not expose prohibited keys."""
        client = ws_test_env["client"]
        db = ws_test_env["db"]
        task_a = ws_test_env["task_a"]
        run_a = ws_test_env["run_a"]
        user_a = ws_test_env["user_a"]
        key_a = ws_test_env["key_a"]

        # Attempt to insert event with prohibited metadata
        event_with_metadata = create_db_event(
            task_a.id,
            run_a.id,
            user_a.id,
            sequence=1,
            event_type=EventType.EVALUATION_COMPLETED,
            metadata={
                "public_info": "safe",
                "judge_reasoning": "CONFIDENTIAL EVALUATION REASONING",
                "chain_of_thought": "CONFIDENTIAL THOUGHTS",
                "api_key": "sk-secret-key",
            },
        )
        db.add(event_with_metadata)

        with client.websocket_connect(f"/ws/tasks/{task_a.id}?api_key={key_a}") as ws:
            msg = ws.receive_json()
            meta = msg.get("metadata", {})
            assert "public_info" in meta
            assert "judge_reasoning" not in meta
            assert "chain_of_thought" not in meta
            assert "api_key" not in meta
