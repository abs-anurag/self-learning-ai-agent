"""
Celery application definition for the Self-Learning AI Agent.

Source of truth: BLUEPRINT.md §1, §4, §8.

Uses Redis as both broker and result backend.
"""

from __future__ import annotations

from celery import Celery

from backend.core.config import settings

app = Celery(
    "self_learning_ai_agent",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Auto-discover tasks in the worker package
app.autodiscover_tasks(["backend.worker"])

__all__ = ["app"]
