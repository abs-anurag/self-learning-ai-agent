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
"""

from __future__ import annotations

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


def get_psycopg_postgres_url(url: Optional[str] = None) -> str:
    """
    Return a standard postgresql:// connection string compatible with psycopg/psycopg_pool.
    Strips SQLAlchemy async/sync driver prefixes (such as '+asyncpg' or '+psycopg').
    Source: BLUEPRINT.md §8 LangGraph Checkpointer.
    """
    target_url = url or settings.POSTGRES_URL.get_secret_value()
    if "://" in target_url:
        scheme, remainder = target_url.split("://" , 1)
        base_scheme = scheme.split("+")[0]
        return f"{base_scheme}://{remainder}"
    return target_url


async def dispose_engine(engine: AsyncEngine) -> None:
    """
    Safely close and dispose an AsyncEngine instance.
    Source: BLUEPRINT.md §8 Checkpointer Lifecycle.
    """
    if engine is not None:
        await engine.dispose()


# Global async engine and session factory for FastAPI / web application lifecycle
async_engine: AsyncEngine = create_engine_instance()

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding an AsyncSession with automated transaction management.
    Commits on successful completion, rolls back on exception.
    """
    async with async_session_factory() as session:
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
    factory = session_factory or async_session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
