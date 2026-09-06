"""
FastAPI route modules.
Source of truth: BLUEPRINT.md §15.
"""

from backend.api.routes.events import router as events_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.health import router as health_router
from backend.api.routes.memory import router as memory_router
from backend.api.routes.metrics import router as metrics_router
from backend.api.routes.tasks import router as tasks_router

__all__ = [
    "health_router",
    "tasks_router",
    "events_router",
    "memory_router",
    "feedback_router",
    "metrics_router",
]
