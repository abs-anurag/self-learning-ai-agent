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
    LLMProvider,
)
from backend.agent.state import AgentState
from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger
from backend.db.models import TaskStatus
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
    **kwargs: Any,
) -> LLMProvider:
    """
    Factory returning LLMProvider based on execution mode.
    Source: BLUEPRINT.md §15.

    - EXECUTION_MODE=demo -> FixtureProvider
    - EXECUTION_MODE=live -> AnthropicProvider
    """
    resolved_mode = mode or settings.EXECUTION_MODE
    if isinstance(resolved_mode, str):
        resolved_mode = resolved_mode.lower().strip()

    if resolved_mode in (ExecutionMode.DEMO, "demo"):
        return FixtureProvider(**kwargs)
    elif resolved_mode in (ExecutionMode.LIVE, "live"):
        return AnthropicProvider(**kwargs)
    else:
        logger.warning("Unrecognized execution mode '%s'; defaulting to FixtureProvider.", resolved_mode)
        return FixtureProvider(**kwargs)


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
        1. Create AsyncPostgresSaver from connection string using from_conn_string.
        2. Call await saver.setup() to ensure tables exist.
        3. Yield saver for execution.
        4. Connection is closed automatically when context exits.
        """
        target_url = url or settings.POSTGRES_URL.get_secret_value()
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # Use the classmethod from_conn_string which manages the connection lifecycle
            async with AsyncPostgresSaver.from_conn_string(target_url) as saver:
                # Idempotent setup if available
                if hasattr(saver, "setup"):
                    await saver.setup()
                yield saver
        except ImportError:
            logger.warning(
                "langgraph-checkpoint-postgres not installed; "
                "yielding None checkpointer for lightweight execution."
            )
            yield None

    async def run(
        self,
        *,
        run_id: Union[str, uuid.UUID],
        task_id: Union[str, uuid.UUID],
        user_id: Union[str, uuid.UUID],
        goal: str,
        task_type: str = "",
        max_iterations: Optional[int] = None,
        initial_state: Optional[dict[str, Any]] = None,
        url: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Execute the agent graph for a single task run.

        Source: BLUEPRINT.md §8, §15.

        Lifecycle:
        1. Create AsyncPostgresSaver via from_conn_string (per-invocation, manages its own connection).
        2. Call saver.setup() if available.
        3. Compile the LangGraph with the checkpointer.
        4. Create initial AgentState.
        5. Invoke the graph with thread_id = run_id.
        6. Process final state.
        7. Update authoritative task/run status in PostgreSQL.
        8. Checkpointer connection closed automatically when context exits; node engine disposed separately.

        Args:
            run_id: Task run identifier (UUID string or UUID object).
            task_id: Task identifier (UUID string or UUID object).
            user_id: User identifier (UUID string or UUID object).
            goal: Task goal string.
            task_type: Optional task type ("math", "research", "file", "code", "mixed").
            max_iterations: Optional iteration limit (default: settings.MAX_ITERATIONS).
            initial_state: Optional pre-built state dict to merge with defaults.
            url: Optional PostgreSQL URL override.

        Returns:
            dict: Final AgentState after graph execution completes.

        Raises:
            RuntimeError: If langgraph is not installed.
        """
        # Defensive import: langgraph must be installed for real execution.
        try:
            from langgraph.graph import END, START, StateGraph  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "langgraph is required for AgentRuntime.run(). "
                "Install langgraph>=0.2.0,<0.3.0."
            ) from exc

        from backend.agent.graph import build_agent_graph
        from backend.agent.state import create_initial_state

        run_id_str = str(run_id)
        task_id_str = str(task_id)
        user_id_str = str(user_id)

        logger.info(
            f"[AgentRuntime.run] Starting execution for task {task_id_str}, "
            f"run {run_id_str}, user {user_id_str}"
        )

        # Build initial state
        if initial_state is not None:
            state = create_initial_state(
                task_id=task_id_str,
                run_id=run_id_str,
                user_id=user_id_str,
                goal=goal,
                max_iterations=max_iterations,
            )
            state.update(initial_state)
        else:
            state = create_initial_state(
                task_id=task_id_str,
                run_id=run_id_str,
                user_id=user_id_str,
                goal=goal,
                max_iterations=max_iterations,
            )
            if task_type:
                state["task_type"] = task_type

        # -- Per-invocation checkpointer lifecycle (BLUEPRINT.md §8) --
        async with self.checkpointer_context(url=url) as saver:
            # Compile graph with checkpointer
            graph = build_agent_graph(checkpointer=saver)

            # Build config with thread_id = run_id
            config = self.get_thread_config(run_id_str)
            # Pass runtime, settings into node config
            config["runtime"] = self
            config["settings"] = settings

            # Provide a db_session for nodes that need it (evaluate, learn, etc.)
            # The session is created from a separate per-invocation engine
            # (node_engine) distinct from the checkpointer engine.
            from sqlalchemy.ext.asyncio import async_sessionmaker
            from backend.db.session import create_engine_instance

            node_engine = create_engine_instance(url)
            node_session_factory = async_sessionmaker(
                bind=node_engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )

            try:
                async with node_session_factory() as db_session:
                    config["db_session"] = db_session

                    # Execute the graph
                    try:
                        final_state = await graph.ainvoke(state, config=config)
                    except Exception as exc:
                        logger.error(
                            f"[AgentRuntime.run] Graph execution failed for run {run_id_str}: {exc}",
                            exc_info=True,
                        )
                        # Update authoritative run status to failed
                        try:
                            await self._update_run_status(
                                run_id_str,
                                "failed",
                                termination_reason="graph_execution_error",
                            )
                        except Exception:
                            logger.warning(
                                f"[AgentRuntime.run] Failed to update run status after graph error for {run_id_str}"
                            )
                        raise

                    # Process final state and update authoritative status
                    final_status = final_state.get("status", "failed")
                    termination_reason = final_state.get("termination_reason") or "unknown"

                    logger.info(
                        f"[AgentRuntime.run] Graph execution complete for run {run_id_str}: "
                        f"status={final_status}, termination_reason={termination_reason}"
                    )

                    # Update authoritative task/run status in PostgreSQL
                    try:
                        await self._update_run_status(
                            run_id_str,
                            final_status,
                            termination_reason=termination_reason,
                        )
                    except Exception as exc:
                        logger.error(
                            f"[AgentRuntime.run] Failed to update run status for {run_id_str}: {exc}",
                            exc_info=True,
                        )

                    return final_state
            finally:
                await dispose_engine(node_engine)

    async def _update_run_status(
        self,
        run_id: str,
        status: Union[TaskStatus, str],
        *,
        termination_reason: Optional[str] = None,
        final_response: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update the authoritative task_runs status in PostgreSQL.

        Source: BLUEPRINT.md §1, §9: AgentState.status is execution-local;
        the authoritative status for execution is task_runs.status in PostgreSQL.
        """
        from sqlalchemy import select, update
        from backend.db.models import Task, TaskRun

        run_uuid = uuid.UUID(run_id)
        if isinstance(status, TaskStatus):
            status_value = status.value
        else:
            status_value = str(status)

        async with self.session_factory() as session:
            try:
                # Update the run status
                run_stmt = (
                    update(TaskRun)
                    .where(TaskRun.id == run_uuid)
                    .values(
                        status=status_value,
                        termination_reason=termination_reason,
                    )
                )
                await session.execute(run_stmt)

                # Find and update the parent task status
                task_id_result = await session.execute(
                    select(TaskRun.task_id).where(TaskRun.id == run_uuid)
                )
                task_id_row = task_id_result.scalar_one_or_none()
                if task_id_row is not None:
                    task_stmt = (
                        update(Task)
                        .where(Task.id == task_id_row)
                        .values(status=status_value)
                    )
                    await session.execute(task_stmt)

                await session.commit()
                logger.debug(
                    f"[_update_run_status] Updated run {run_id} to status={status_value}"
                )
            except Exception:
                await session.rollback()
                raise

    async def close(self) -> None:
        """Close any open publisher or runtime resources."""
        if hasattr(self.event_service, "publisher") and hasattr(
            self.event_service.publisher, "close"
        ):
            await self.event_service.publisher.close()


__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "FixtureProvider",
    "get_llm_provider",
    "AgentRuntime",
]
