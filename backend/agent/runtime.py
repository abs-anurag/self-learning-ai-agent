"""
Agent Runtime execution context and LLM provider abstractions.

Source of truth: BLUEPRINT.md §4, §5, §6, §8, §14, §15.
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Optional, Union

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agent.providers import (
    AnthropicProvider,
    FixtureProvider,
    LLMProvider,
)
from backend.agent.state import AgentState, create_initial_state
from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger
from backend.db.session import (
    async_session_factory,
)
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import EventService

logger = get_logger(__name__)

_current_runtime: contextvars.ContextVar[Optional["AgentRuntime"]] = (
    contextvars.ContextVar("_current_runtime", default=None)
)


def get_current_runtime() -> Optional["AgentRuntime"]:
    """Retrieve the active AgentRuntime for the current coroutine."""
    return _current_runtime.get()


def get_llm_provider(
    mode: Optional[Union[ExecutionMode, str]] = None,
    **kwargs: Any,
) -> LLMProvider:
    """
    Return the provider defined by EXECUTION_MODE.

    demo -> FixtureProvider
    live -> AnthropicProvider
    """
    resolved_mode = mode or settings.EXECUTION_MODE

    if isinstance(resolved_mode, str):
        resolved_mode = resolved_mode.lower().strip()

    if resolved_mode in (ExecutionMode.DEMO, "demo"):
        return FixtureProvider(**kwargs)

    if resolved_mode in (ExecutionMode.LIVE, "live"):
        return AnthropicProvider(**kwargs)

    raise ValueError(
        f"Unsupported EXECUTION_MODE: {resolved_mode!r}. "
        "Expected 'demo' or 'live'."
    )


class AgentRuntime:
    """
    Async Agent Runtime for LangGraph execution.

    Responsibilities:
    - LLM provider selection
    - Event Service telemetry integration
    - LangGraph thread configuration
    - Per-invocation AsyncPostgresSaver lifecycle
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        event_service: Optional[EventService] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
        checkpointer_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.llm_provider = llm_provider or get_llm_provider()
        self.event_service = event_service or EventService(
            session_factory=session_factory
        )
        self.persistence_enabled = session_factory is not None
        self.session_factory = session_factory or async_session_factory
        self.checkpointer_factory = checkpointer_factory

    @staticmethod
    def get_thread_config(
        run_id: Union[str, uuid.UUID],
    ) -> dict[str, Any]:
        """
        LangGraph persistence identifier.

        Blueprint: thread_id = run_id.
        """
        return {
            "configurable": {
                "thread_id": str(run_id),
            }
        }

    @asynccontextmanager
    async def use_context(self) -> AsyncIterator["AgentRuntime"]:
        """Make this runtime available to graph nodes."""
        token = _current_runtime.set(self)
        try:
            yield self
        finally:
            _current_runtime.reset(token)

    async def emit_event(
        self,
        *,
        task_id: Union[uuid.UUID, str],
        run_id: Union[uuid.UUID, str],
        user_id: Union[uuid.UUID, str],
        event_type: Union[EventType, str],
        status: str = "running",
        metadata: Optional[dict[str, Any]] = None,
        session: Optional[AsyncSession] = None,
    ) -> EventEnvelope:
        """Emit telemetry exclusively through EventService."""
        return await self.event_service.emit_event(
            task_id=task_id,
            run_id=run_id,
            user_id=user_id,
            event_type=event_type,
            status=status,
            metadata=metadata,
            session=session,
        )

    @asynccontextmanager
    async def checkpointer_context(
        self,
        url: Optional[str] = None,
    ) -> AsyncIterator[Any]:
        """
        Create a fresh AsyncPostgresSaver for one invocation.

        The psycopg connection is closed when this context exits.
        """
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "AsyncPostgresSaver is required by the blueprint. "
                "Install langgraph-checkpoint-postgres."
            ) from exc

        target_url = url or settings.POSTGRES_URL.get_secret_value()
        database_url = make_url(target_url)
        if database_url.drivername == "postgresql+asyncpg":
            database_url = database_url.set(drivername="postgresql")
        connection_string = database_url.render_as_string(hide_password=False)

        checkpointer_context = (
            self.checkpointer_factory(connection_string)
            if self.checkpointer_factory is not None
            else AsyncPostgresSaver.from_conn_string(connection_string)
        )
        async with checkpointer_context as saver:
            if hasattr(saver, "setup"):
                await saver.setup()
            yield saver

    async def run(
        self,
        run_id: Union[str, uuid.UUID],
        task_id: Union[str, uuid.UUID],
        user_id: Union[str, uuid.UUID],
        goal: str,
    ) -> AgentState:
        """
        Execute one LangGraph run.

        The runtime creates the per-invocation PostgreSQL checkpointer,
        executes the graph with thread_id = run_id, and disposes the
        database engine before returning.
        """
        from backend.agent.graph import create_agent_graph

        async with self.use_context():
            await self.emit_event(
                task_id=task_id,
                run_id=run_id,
                user_id=user_id,
                event_type=EventType.TASK_STARTED,
                status="running",
                metadata={"goal": goal[:200]},
            )

            initial_state = create_initial_state(
                task_id=task_id,
                run_id=run_id,
                user_id=user_id,
                goal=goal,
            )

            config = self.get_thread_config(run_id)

            async with self.checkpointer_context() as checkpointer:
                graph = create_agent_graph(
                    checkpointer=checkpointer,
                )

                return await graph.ainvoke(
                    initial_state,
                    config=config,
                )

    async def close(self) -> None:
        """Close runtime-owned publisher resources."""
        if (
            hasattr(self.event_service, "publisher")
            and hasattr(self.event_service.publisher, "close")
        ):
            await self.event_service.publisher.close()


__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "FixtureProvider",
    "get_llm_provider",
    "get_current_runtime",
    "AgentRuntime",
]