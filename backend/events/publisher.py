"""
Redis event publisher for ephemeral live broadcast.

Source of truth: BLUEPRINT.md §1, §4, §14, §17.

Design rules:
- Redis Pub/Sub is ephemeral, live fan-out only, NOT the durable source of truth.
- Channel convention: agent.events.{run_id} (§14).
- Publishes serialized safe EventEnvelope.
- PostgreSQL transaction commit MUST happen before Redis publish.
- If Redis publish fails:
  - PostgreSQL event remains durable.
  - Failure must not roll back or lose the database event.
  - Failure is logged safely without secrets or sensitive contents.
  - Returns False indicating publication failure.
- LangGraph nodes never publish to Redis directly; they interact only with EventService.
"""

from __future__ import annotations

import abc
import uuid
from typing import Optional, Union

import redis.asyncio as aioredis

from backend.core.config import settings
from backend.core.logging import get_logger
from backend.events.schema import EventEnvelope

logger = get_logger(__name__)


class EventPublisher(abc.ABC):
    """Abstract interface for event publication to live channels."""

    @abc.abstractmethod
    async def publish_event(self, event: EventEnvelope) -> bool:
        """
        Publish an event envelope to the appropriate channel.
        Returns True if publication succeeded, False otherwise.
        """
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        """Close any open connections or resources."""
        pass


class RedisEventPublisher(EventPublisher):
    """
    Redis Pub/Sub event publisher for live fan-out.
    Source: BLUEPRINT.md §14.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        client: Optional[aioredis.Redis] = None,
    ) -> None:
        self.redis_url = redis_url or settings.REDIS_URL
        self._client = client
        self._owns_client = client is None

    @staticmethod
    def get_channel(run_id: Union[uuid.UUID, str]) -> str:
        """
        Required Redis channel convention per BLUEPRINT.md §14:
        agent.events.{run_id}
        """
        return f"agent.events.{run_id}"

    async def get_client(self) -> aioredis.Redis:
        """Return existing client or create a new lazy async connection."""
        if self._client is None:
            self._client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    async def publish_event(self, event: EventEnvelope) -> bool:
        """
        Publish the serialized safe event envelope to Redis Pub/Sub.

        Must be called ONLY after the PostgreSQL transaction commits.
        If Redis publication fails, logs safely and returns False without raising.
        """
        channel = self.get_channel(event.run_id)
        payload = event.model_dump_json()

        try:
            client = await self.get_client()
            await client.publish(channel, payload)
            logger.info(
                "Published event %s (sequence %s) to channel %s",
                event.event_id,
                event.sequence,
                channel,
            )
            return True
        except Exception as exc:
            # PostgreSQL is already committed; log safely without leaking sensitive data
            logger.warning(
                "Redis publication failed for event %s on channel %s: %s",
                event.event_id,
                channel,
                type(exc).__name__,
            )
            return False

    async def close(self) -> None:
        """Close the Redis client if owned."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
