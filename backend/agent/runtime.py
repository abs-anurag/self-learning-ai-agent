"""
Agent Runtime execution context and LLM provider abstractions.

Source of truth: BLUEPRINT.md §4, §5, §6, §8, §14, §15.

Design rules:
- Re-exports LLMProvider, AnthropicProvider, FixtureProvider per §15.
- Provider selection: EXECUTION_MODE=demo selects FixtureProvider;
  EXECUTION_MODE=live selects AnthropicProvider (§15).
- thread_id = run_id per §8.
- Checkpointer lifecycle per §8:
  Engines and AsyncPostgresSaver are instantiated per invocation and safely
  disposed before asyncio.run() exits.
- Telemetry integration: emits strictly through EventService.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional, Union

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backend.agent.providers import (
    AnthropicProvider,
    FixtureProvider,
    GeminiProvider,
    LLMProvider,
)
from backend.agent.state import AgentState
from backend.core.config import ExecutionMode, LLMProviderName, settings
from backend.core.logging import get_logger
from backend.db.session import (
    async_session_factory,
    create_engine_instance,
    dispose_engine,
)
from backend.events.publisher import EventPublisher
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import EventService

logger = get_logger(__name__)


# -- Provider Factory --------------------------------------------


def get_llm_provider(
    mode: Optional[Union[ExecutionMode, str]] = None,
    provider: Optional[Union[LLMProviderName, str]] = None,
    **kwargs: Any,
) -> LLMProvider:
    """
    Factory returning LLMProvider based on execution mode and provider configuration.
    Source: BLUEPRINT.md §15.

    - LLM_PROVIDER=gemini -> GeminiProvider
    - LLM_PROVIDER=anthropic -> AnthropicProvider
    - LLM_PROVIDER=fixture or EXECUTION_MODE=demo -> FixtureProvider
    - EXECUTION_MODE=live defaults to GeminiProvider
    """
    # 1. Explicit provider passed by caller
    if provider is not None:
        p = provider.value if isinstance(provider, LLMProviderName) else str(provider).lower().strip()
        if p in (LLMProviderName.GEMINI.value, "gemini"):
            return GeminiProvider(**kwargs)
        elif p in (LLMProviderName.ANTHROPIC.value, "anthropic"):
            return AnthropicProvider(**kwargs)
        elif p in (LLMProviderName.FIXTURE.value, "fixture"):
            return FixtureProvider(**kwargs)

    # 2. Explicit mode passed by caller
    if mode is not None:
        m = mode.value if isinstance(mode, ExecutionMode) else str(mode).lower().strip()
        if m in (ExecutionMode.DEMO.value, "demo"):
            return FixtureProvider(**kwargs)
        elif m in (ExecutionMode.LIVE.value, "live"):
            prov = settings.LLM_PROVIDER
            p = prov.value if isinstance(prov, LLMProviderName) else str(prov).lower().strip()
            if p in (LLMProviderName.ANTHROPIC.value, "anthropic"):
                return AnthropicProvider(**kwargs)
            return GeminiProvider(**kwargs)

    # 3. Environment settings
    if settings.EXECUTION_MODE == ExecutionMode.DEMO or settings.LLM_PROVIDER == LLMProviderName.FIXTURE:
        return FixtureProvider(**kwargs)

    if settings.LLM_PROVIDER == LLMProviderName.ANTHROPIC:
        return AnthropicProvider(**kwargs)

    return GeminiProvider(**kwargs)


# -- Agent Runtime Context ---------------------------------------


class AgentRuntime:
    """
    Controlled runtime execution context for agent runs.
    Source: BLUEPRINT.md §4, §8, §15.

    Manages:
    - LLM provider instance.
    - EventService reference for telemetry.
    - LangGraph thread configuration (thread_id = run_id).
    - Checkpointer per-invocation lifecycle.
    """

    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        event_service: Optional[EventService] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ) -> None:
        self.llm_provider = llm_provider or get_llm_provider()
        self.event_service = event_service or EventService(session_factory=session_factory)
        self.session_factory = session_factory or async_session_factory

    @staticmethod
    def get_thread_config(run_id: Union[str, uuid.UUID]) -> dict[str, Any]:
        """
        Generate LangGraph thread configuration.
        Source: BLUEPRINT.md §8 (thread_id = run_id).
        """
        return {"configurable": {"thread_id": str(run_id)}}

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
        """
        Emit a telemetry event via the Event Service.

        Preserves the single telemetry path:
        Nodes -> Runtime -> Event Service -> PostgreSQL -> Redis Pub/Sub.
        """
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
        Async context manager managing the checkpointer lifecycle per BLUEPRINT.md §8:

        Inside each Celery task invocation:
        1. Create a fresh async engine for general DB tasks.
        2. Derive standard psycopg-compatible postgresql:// URL.
        3. Instantiate checkpointer: saver = AsyncPostgresSaver.from_conn_string(conn_str).
        4. Call await saver.setup() to run idempotent migrations if needed.
        5. Yield saver for StateGraph compilation and execution.
        6. Cleanly close checkpointer and dispose the engine before exiting.
        """
        engine: AsyncEngine = create_engine_instance(url)
        saver_cm: Any = None
        saver: Any = None
        try:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                from backend.db.session import get_psycopg_postgres_url

                conn_str = get_psycopg_postgres_url(url)
                saver_cm = AsyncPostgresSaver.from_conn_string(conn_str)
                saver = await saver_cm.__aenter__()
                if hasattr(saver, "setup"):
                    await saver.setup()
            except Exception as exc:
                logger.warning(
                    "Checkpointer setup skipped: %s; yielding None checkpointer for lightweight execution.",
                    exc,
                )
                if saver_cm is not None:
                    try:
                        await saver_cm.__aexit__(None, None, None)
                    except Exception:
                        pass
                    saver_cm = None
                saver = None

            yield saver
        finally:
            if saver_cm is not None:
                try:
                    await saver_cm.__aexit__(None, None, None)
                except Exception as close_exc:
                    logger.warning("Failed to close checkpointer connection: %s", close_exc)
            await dispose_engine(engine)

    async def close(self) -> None:
        """Close any open publisher or runtime resources."""
        if hasattr(self.event_service, "publisher") and hasattr(
            self.event_service.publisher, "close"
        ):
            await self.event_service.publisher.close()


from contextvars import ContextVar

_current_runtime_var: ContextVar[Optional[AgentRuntime]] = ContextVar("_current_runtime_var", default=None)


def get_current_runtime() -> AgentRuntime:
    """Retrieve the current AgentRuntime context, creating a default one if unset."""
    rt = _current_runtime_var.get()
    if rt is None:
        rt = AgentRuntime()
        _current_runtime_var.set(rt)
    return rt


def set_current_runtime(runtime: AgentRuntime) -> None:
    """Set the current AgentRuntime context."""
    _current_runtime_var.set(runtime)


__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "FixtureProvider",
    "get_llm_provider",
    "AgentRuntime",
    "get_current_runtime",
    "set_current_runtime",
]
