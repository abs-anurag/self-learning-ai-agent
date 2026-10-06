"""
Database engine and session management.

Source of truth: BLUEPRINT.md §4, §8, §18, §23.

Design rules:
- Reuses existing configuration from `backend.core.config.settings`.
- Database credentials and secrets are kept strictly out of source code and logs.
- SQLAlchemy 2.0 async engine and sessionmaker (`AsyncSession`).
- Supports the per-invocation engine lifecycle required for Celery workers (§8):
  engines can be dynamically instantiated and disposed per task execution.
- Provides FastAPI dependency `get_db_session()` with safe commit/rollback semantics.
- Global engine/session_factory are LAZY - created on first access to avoid
  creating asyncpg pools at import time (which would be forked to Celery workers).
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)


# --- Module-level singletons (lazy initialization) ---
_async_engine: Optional[AsyncEngine] = None
_async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _get_async_engine() -> AsyncEngine:
    """Get or create the global async engine (lazy initialization)."""
    global _async_engine
    if _async_engine is None:
        _async_engine = create_engine_instance()
        logger.debug("Created global async engine (lazy initialization)")
    return _async_engine


def _get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the global async session factory (lazy initialization)."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=_get_async_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        logger.debug("Created global async session factory (lazy initialization)")
    return _async_session_factory


def create_engine_instance(
    url: Optional[str] = None,
    *,
    pool_pre_ping: bool = True,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
) -> AsyncEngine:
    """
    Create a new AsyncEngine instance.

    Per BLUEPRINT.md §8:
    Celery workers must instantiate a fresh async engine inside each task
    invocation and dispose it before exiting asyncio.run() to avoid sharing
    connections across prefork worker processes.
    """
    target_url = url or settings.POSTGRES_URL.get_secret_value()
    return create_async_engine(
        target_url,
        pool_pre_ping=pool_pre_ping,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
    )


async def dispose_engine(engine: AsyncEngine) -> None:
    """
    Safely close and dispose an AsyncEngine instance.
    Source: BLUEPRINT.md §8 Checkpointer Lifecycle.

    AsyncPG pool shutdown can block when PostgreSQL is unavailable or the
    connection pool is already stale. In those cases we fail closed by skipping
    disposal rather than blocking the worker lifecycle indefinitely.
    """
    if engine is None:
        return

    try:
        host = engine.url.host
        port = engine.url.port or 5432
        if host is not None:
            with socket.create_connection((host, port), timeout=0.25):
                pass
    except OSError:
        logger.warning(
            "Skipping async engine disposal because Postgres endpoint %s:%s is unavailable.",
            engine.url.host,
            engine.url.port or 5432,
        )
        return
    except Exception:
        logger.exception("Unexpected error checking database endpoint for engine disposal.")
        return

    try:
        await asyncio.wait_for(engine.dispose(), timeout=2.0)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        logger.warning("Timed out while disposing async database engine; continuing without blocking the worker.")
    except Exception:
        logger.exception("Unexpected error while disposing async database engine.")


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding an AsyncSession with automated transaction management.
    Commits on successful completion, rolls back on exception.
    """
    session_factory = _get_async_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
) -> AsyncIterator[AsyncSession]:
    """
    Async context manager for standalone / worker session management.
    """
    factory = session_factory or _get_async_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# --- Backwards-compatible property access (for existing imports) ---
# These allow `from backend.db.session import async_engine, async_session_factory`
# to work, but they trigger lazy initialization on first access.

def __getattr__(name: str):
    if name == "async_engine":
        return _get_async_engine()
    if name == "async_session_factory":
        return _get_async_session_factory()
    raise AttributeError(f"module 'backend.db.session' has no attribute '{name}'")


__all__ = [
    "create_engine_instance",
    "dispose_engine",
    "get_db_session",
    "session_scope",
    "async_engine",
    "async_session_factory",
]