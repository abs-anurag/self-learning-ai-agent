"""
Database models and declarative base for PostgreSQL + pgvector.

Source of truth: BLUEPRINT.md §1, §4, §8, §10, §11, §14, §17, §18.

Design rules:
- Strictly follows the PostgreSQL 15 schema defined in BLUEPRINT.md §18.
- Status vocabulary is strictly unified: 'pending', 'running', 'succeeded', 'failed'.
  The value 'completed' is never used as a status value (§1, §21, Appendix B).
- All 10 domain entities implemented with typed SQLAlchemy 2.0 mappings.
- PostgreSQL JSONB, UUID, and pgvector Vector(384) types are explicitly used.
- Keys and sensitive values are never logged or stored in plaintext.
- Table names and column names match BLUEPRINT.md §18 verbatim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# -- Status & Type Enums -----------------------------------------


class TaskStatus(str, Enum):
    """
    Unified task and run status vocabulary.
    Source: BLUEPRINT.md §1, §2, §18.
    'completed' is strictly forbidden as a status value.
    """
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CandidateStatus(str, Enum):
    """Recipe candidate status per BLUEPRINT.md §11, §18."""
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class RecipeStatus(str, Enum):
    """Trusted recipe status per BLUEPRINT.md §10, §18."""
    TRUSTED = "trusted"


class TaskType(str, Enum):
    """Supported task types per BLUEPRINT.md §9, §18."""
    MATH = "math"
    RESEARCH = "research"
    FILE = "file"
    CODE = "code"
    MIXED = "mixed"


# -- Declarative Base --------------------------------------------


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


# -- Models ------------------------------------------------------


class User(Base):
    """
    Users table.
    Source: BLUEPRINT.md §18.
    Stores user identities and API key hashes. Plaintext keys are never stored.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    api_key_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    tasks: Mapped[List[Task]] = relationship(
        "Task",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    task_runs: Mapped[List[TaskRun]] = relationship(
        "TaskRun",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    experiences: Mapped[List[Experience]] = relationship(
        "Experience",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    evaluations: Mapped[List[Evaluation]] = relationship(
        "Evaluation",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    feedback: Mapped[List[Feedback]] = relationship(
        "Feedback",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    recipe_candidates: Mapped[List[RecipeCandidate]] = relationship(
        "RecipeCandidate",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    task_recipes: Mapped[List[TaskRecipe]] = relationship(
        "TaskRecipe",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    agent_events: Mapped[List[AgentEvent]] = relationship(
        "AgentEvent",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[List[AuditLog]] = relationship(
        "AuditLog",
        back_populates="user",
    )


class Task(Base):
    """
    Tasks table (user-facing aggregate task state).
    Source: BLUEPRINT.md §18.
    """
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    goal: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TaskStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_tasks_user", "user_id", text("created_at DESC")),
    )

    # Relationships
    user: Mapped[User] = relationship("User", back_populates="tasks")
    runs: Mapped[List[TaskRun]] = relationship(
        "TaskRun",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    experiences: Mapped[List[Experience]] = relationship(
        "Experience",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    feedback: Mapped[List[Feedback]] = relationship(
        "Feedback",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    agent_events: Mapped[List[AgentEvent]] = relationship(
        "AgentEvent",
        back_populates="task",
        cascade="all, delete-orphan",
    )


class TaskRun(Base):
    """
    Task runs table (authoritative execution state).
    Source: BLUEPRINT.md §1, §14, §18.
    `task_runs.status` is the single source of truth for execution.
    `sequence_counter` tracks monotonic event ordering for the run (§14).
    """
    __tablename__ = "task_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TaskStatus.PENDING.value,
        server_default=text("'pending'"),
    )
    termination_reason: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    iteration_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    sequence_counter: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_task_runs_lookup", "task_id", text("created_at DESC")),
        Index("idx_task_runs_status", "status"),
    )

    # Relationships
    task: Mapped[Task] = relationship("Task", back_populates="runs")
    user: Mapped[User] = relationship("User", back_populates="task_runs")
    evaluations: Mapped[List[Evaluation]] = relationship(
        "Evaluation",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    experiences: Mapped[List[Experience]] = relationship(
        "Experience",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    agent_events: Mapped[List[AgentEvent]] = relationship(
        "AgentEvent",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    recipe_candidates: Mapped[List[RecipeCandidate]] = relationship(
        "RecipeCandidate",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class Experience(Base):
    """
    Episodic experiences table (audit and provenance).
    Source: BLUEPRINT.md §10, §18.
    Raw execution records stored for provenance, not retrieved for future strategy.
    """
    __tablename__ = "experiences"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    tools_used: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    outcome_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    task: Mapped[Task] = relationship("Task", back_populates="experiences")
    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="experiences")
    user: Mapped[User] = relationship("User", back_populates="experiences")


class Evaluation(Base):
    """
    Composite evaluations table (one row per completed iteration).
    Source: BLUEPRINT.md §12, §18.
    CONSTRAINT uq_run_iteration UNIQUE (run_id, iteration_count)
    `payload` stores private judge_reasoning (never exposed in APIs/telemetry).
    """
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    iteration_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    task_success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    deterministic_pass: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    tool_success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    judge_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 1),
        nullable=False,
    )
    tool_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "iteration_count", name="uq_run_iteration"),
        Index("idx_evaluations_run", "run_id", "iteration_count"),
    )

    # Relationships
    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="evaluations")
    user: Mapped[User] = relationship("User", back_populates="evaluations")


class Feedback(Base):
    """
    User feedback table.
    Source: BLUEPRINT.md §18.
    Optional rating (1-5) and user comments.
    """
    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    comment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),
    )

    # Relationships
    task: Mapped[Task] = relationship("Task", back_populates="feedback")
    user: Mapped[User] = relationship("User", back_populates="feedback")


class RecipeCandidate(Base):
    """
    Recipe candidates table (pre-gate structured lessons).
    Source: BLUEPRINT.md §10, §11, §18.
    Stores pre-gate candidate strategies extracted on non-trivial success.
    """
    __tablename__ = "recipe_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    source_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    problem_pattern: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    context: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    recommended_strategy: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    successful_steps: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    failed_steps: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    tools_used: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    lesson: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    evidence: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    evaluation_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 1),
        nullable=False,
    )
    deterministic_pass: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    generalizable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=CandidateStatus.CANDIDATE.value,
        server_default=text("'candidate'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    source_task: Mapped[Task] = relationship("Task")
    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="recipe_candidates")
    user: Mapped[User] = relationship("User", back_populates="recipe_candidates")


class TaskRecipe(Base):
    """
    Trusted recipes table (pgvector vector indexed).
    Source: BLUEPRINT.md §10, §11, §18.
    The ONLY layer retrieved for future strategy alteration.
    Vector dimensions: 384 (sentence-transformers MiniLM-L6-v2).
    """
    __tablename__ = "task_recipes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    source_task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RecipeStatus.TRUSTED.value,
        server_default=text("'trusted'"),
    )
    task_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    problem_pattern: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    context: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    recommended_strategy: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    successful_steps: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    failed_steps: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    tools_used: Mapped[Any] = mapped_column(
        JSONB,
        nullable=False,
    )
    lesson: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    evidence: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    evaluation_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 1),
        nullable=False,
    )
    deterministic_pass: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    generalizable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        nullable=False,
        default=Decimal("1.0"),
        server_default=text("1.0"),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    usage_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    success_after_reuse: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(384),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("idx_task_recipes_user", "user_id", "task_type"),
        Index(
            "idx_task_recipes_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    # Relationships
    source_task: Mapped[Task] = relationship("Task")
    user: Mapped[User] = relationship("User", back_populates="task_recipes")


class AgentEvent(Base):
    """
    Durable telemetry events table.
    Source: BLUEPRINT.md §14, §18.
    Durable append-only audit log written by Event Service prior to Redis broadcast.
    CONSTRAINT uq_run_sequence UNIQUE (run_id, sequence)
    """
    __tablename__ = "agent_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    schema_version: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="1.0",
        server_default=text("'1.0'"),
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    # Map the database column 'metadata' avoiding conflict with DeclarativeBase.metadata
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_sequence"),
        Index("idx_agent_events_replay", "run_id", text("sequence ASC")),
    )

    # Relationships
    task: Mapped[Task] = relationship("Task", back_populates="agent_events")
    run: Mapped[TaskRun] = relationship("TaskRun", back_populates="agent_events")
    user: Mapped[User] = relationship("User", back_populates="agent_events")

    @property
    def event_metadata(self) -> dict[str, Any]:
        """Accessor for event payload metadata."""
        return self.metadata_

    @event_metadata.setter
    def event_metadata(self, val: dict[str, Any]) -> None:
        self.metadata_ = val


class AuditLog(Base):
    """
    Audit logs table.
    Source: BLUEPRINT.md §17, §18.
    Records administrative, authentication, and security-relevant actions.
    `user_id` is set to NULL if the referenced user is deleted.
    """
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    resource: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    redacted_detail: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    # Relationships
    user: Mapped[Optional[User]] = relationship("User", back_populates="audit_logs")
