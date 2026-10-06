"""
Database package providing models, session management, and migrations.

Source of truth: BLUEPRINT.md §18.
"""

from backend.db.models import (
    AgentEvent,
    AuditLog,
    Base,
    CandidateStatus,
    Evaluation,
    Experience,
    Feedback,
    RecipeCandidate,
    RecipeStatus,
    Task,
    TaskRecipe,
    TaskRun,
    TaskStatus,
    TaskType,
    User,
)
from backend.db.session import (
    create_engine_instance,
    dispose_engine,
    get_db_session,
    session_scope,
)

__all__ = [
    "Base",
    "User",
    "Task",
    "TaskRun",
    "Experience",
    "Evaluation",
    "Feedback",
    "RecipeCandidate",
    "TaskRecipe",
    "AgentEvent",
    "AuditLog",
    "TaskStatus",
    "CandidateStatus",
    "RecipeStatus",
    "TaskType",
    "create_engine_instance",
    "dispose_engine",
    "get_db_session",
    "session_scope",
]
