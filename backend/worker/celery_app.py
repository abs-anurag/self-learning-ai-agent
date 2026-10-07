"""
Celery application configuration for METIS background tasks.

Source of truth: BLUEPRINT.md §8, §16, §23.
Broker: Redis (REDIS_URL)
Result Backend: Redis (REDIS_URL)
"""

from __future__ import annotations

from celery import Celery

from backend.core.config import settings

celery_app = Celery(
    "metis_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["backend.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Alias for celery CLI invocation: celery -A backend.worker.celery_app:app
app = celery_app
