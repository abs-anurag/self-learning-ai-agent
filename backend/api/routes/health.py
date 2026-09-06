"""
Health check route verifying PostgreSQL and Redis connectivity.

Source of truth: BLUEPRINT.md §15.

Response:
{
  "status": "ok",
  "database": "connected",
  "redis": "connected"
}
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.dependencies import get_db
from backend.api.schemas import HealthCheckResponse
from backend.core.config import settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthCheckResponse)
async def health_check(
    session: Optional[AsyncSession] = Depends(get_db),
) -> HealthCheckResponse:
    """
    GET /health
    Verifies PostgreSQL and Redis connectivity.
    Never exposes credentials, connection strings, or internal errors.
    Source: BLUEPRINT.md §15.
    """
    database_status = "disconnected"
    redis_status = "disconnected"

    # 1. Probe PostgreSQL
    if session is not None:
        try:
            res = await session.execute(text("SELECT 1"))
            if res.scalar() == 1:
                database_status = "connected"
        except Exception as exc:
            logger.warning("Health check: PostgreSQL probe failed (%s)", type(exc).__name__)

    # 2. Probe Redis
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
        ping_result = await redis_client.ping()
        if ping_result:
            redis_status = "connected"
        await redis_client.aclose()
    except Exception as exc:
        logger.warning("Health check: Redis probe failed (%s)", type(exc).__name__)

    overall_status = "ok" if (database_status == "connected" and redis_status == "connected") else "degraded"

    return HealthCheckResponse(
        status=overall_status,
        database=database_status,
        redis=redis_status,
    )
