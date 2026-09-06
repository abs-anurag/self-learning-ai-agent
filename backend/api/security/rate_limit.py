"""
Rate Limiting Implementation for API Endpoints.

Source of truth: BLUEPRINT.md §15, §17, §22.

Design rules:
- `POST /tasks` is strictly rate-limited to 10 requests/minute per API key.
- Rejection returns HTTP 429 Too Many Requests with standard API error envelope:
  {"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "...", "request_id": "..."}}
- Includes `Retry-After` HTTP header indicating seconds until next available slot.
- Implemented as an in-memory sliding window rate limiter per user/API key.
- Concurrency-safe via asyncio lock.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from typing import DefaultDict, Dict, List, Optional, Tuple

from fastapi import Depends

from backend.api.schemas import APIException, ErrorCode
from backend.api.security.auth import get_current_user
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import User

logger = get_logger(__name__)


class SlidingWindowRateLimiter:
    """
    In-memory sliding window rate limiter.
    Source: BLUEPRINT.md §15, §17.

    Tracks request timestamps within a sliding time window (default: 60.0 seconds).
    """

    def __init__(
        self,
        requests_per_minute: Optional[int] = None,
        window_seconds: float = 60.0,
    ) -> None:
        self.requests_per_minute = (
            requests_per_minute
            if requests_per_minute is not None
            else settings.RATE_LIMIT_TASKS_PER_MINUTE
        )
        self.window_seconds = window_seconds
        self._history: DefaultDict[str, List[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def is_allowed(self, key: str) -> Tuple[bool, int, float]:
        """
        Check whether an operation is allowed under the rate limit.

        Returns:
            (allowed, remaining_slots, retry_after_seconds)
        """
        now = time.monotonic()
        cutoff = now - self.window_seconds

        async with self._lock:
            # Filter timestamps outside the sliding window
            timestamps = [t for t in self._history[key] if t > cutoff]
            self._history[key] = timestamps

            if len(timestamps) < self.requests_per_minute:
                # Operation permitted: record timestamp
                timestamps.append(now)
                remaining = self.requests_per_minute - len(timestamps)
                return True, remaining, 0.0
            else:
                # Rate limit exceeded: calculate seconds until earliest request rolls out
                earliest = timestamps[0]
                retry_after = max(1.0, earliest + self.window_seconds - now)
                return False, 0, retry_after

    async def check(self, key: str) -> None:
        """
        Enforce the rate limit. Raises APIException(429, RATE_LIMIT_EXCEEDED) if violated.
        """
        allowed, _, retry_after = await self.is_allowed(key)
        if not allowed:
            retry_int = math.ceil(retry_after)
            logger.warning(
                "Rate limit exceeded for key %s. Retry after %d seconds.",
                key[:8] + "...",
                retry_int,
            )
            raise APIException.rate_limited(
                message=(
                    f"Rate limit exceeded: maximum {self.requests_per_minute} "
                    f"requests per minute on POST /tasks."
                ),
                retry_after=retry_int,
            )

    async def reset(self) -> None:
        """Clear all rate limiting history. Useful for testing."""
        async with self._lock:
            self._history.clear()


# Module-level singleton for task creation rate limiting
task_rate_limiter = SlidingWindowRateLimiter(
    requests_per_minute=settings.RATE_LIMIT_TASKS_PER_MINUTE
)


async def rate_limit_task_creation(
    current_user: User = Depends(get_current_user),
) -> None:
    """
    FastAPI dependency enforcing the 10 req/min rate limit on POST /tasks per user.
    Source: BLUEPRINT.md §15, §17.
    """
    user_key = str(current_user.id)
    await task_rate_limiter.check(user_key)


__all__ = [
    "SlidingWindowRateLimiter",
    "task_rate_limiter",
    "rate_limit_task_creation",
]
