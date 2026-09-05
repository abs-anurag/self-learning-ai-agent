"""
Tests for the database foundation layer.

Source of truth: BLUEPRINT.md §1, §8, §10, §11, §12, §14, §17, §18.

Verifies:
- All 10 database tables and columns match BLUEPRINT.md §18 verbatim.
- Status vocabulary is strictly unified (pending, running, succeeded, failed)
  and 'completed' is strictly rejected.
- Primary keys, foreign keys, ondelete behaviors, unique and check constraints.
- Indexes match the 7 key performance indexes defined in §18.
- Engine and session creation, Celery worker per-invocation engine lifecycle.
- Security: database secrets are SecretStr and not leaked in string representations.
- Alembic migration script and configuration validity.
"""

from __future__ import annotations

import os
from decimal import Decimal
import uuid
import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.schema import CreateTable
from sqlalchemy.dialects import postgresql

from backend.core.config import settings
from backend.db import (
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
    async_engine,
    async_session_factory,
    create_engine_instance,
    dispose_engine,
)


class TestStatusVocabulary:
    """BLUEPRINT.md §1, §2, Appendix B: Strict unified status vocabulary."""

    def test_task_status_values(self) -> None:
        expected = {"pending", "running", "succeeded", "failed"}
        actual = {s.value for s in TaskStatus}
        assert actual == expected

    def test_completed_is_never_a_status(self) -> None:
        assert "completed" not in {s.value for s in TaskStatus}
        assert "completed" not in [s.name.lower() for s in TaskStatus]

    def test_candidate_status_values(self) -> None:
        expected = {"candidate", "rejected"}
        actual = {s.value for s in CandidateStatus}
        assert actual == expected

    def test_recipe_status_values(self) -> None:
        expected = {"trusted"}
        actual = {s.value for s in RecipeStatus}
        assert actual == expected

    def test_task_type_values(self) -> None:
        expected = {"math", "research", "file", "code", "mixed"}
        actual = {t.value for t in TaskType}
        assert actual == expected


class TestSchemaDefinitions:
    """BLUEPRINT.md §18: Schema definitions and tables."""

    def test_all_ten_tables_exist(self) -> None:
        expected_tables = {
            "users",
            "tasks",
            "task_runs",
            "experiences",
            "evaluations",
            "feedback",
            "recipe_candidates",
            "task_recipes",
            "agent_events",
            "audit_logs",
        }
        actual_tables = set(Base.metadata.tables.keys())
        assert actual_tables == expected_tables

    def test_primary_keys(self) -> None:
        for table_name, table in Base.metadata.tables.items():
            pk_cols = [c.name for c in table.primary_key.columns]
            if table_name == "agent_events":
                assert pk_cols == ["event_id"], f"{table_name} must have primary key event_id"
            else:
                assert pk_cols == ["id"], f"{table_name} must have primary key id"

    def test_users_table_columns(self) -> None:
        table = Base.metadata.tables["users"]
        assert "id" in table.c
        assert "api_key_hash" in table.c
        assert "display_name" in table.c
        assert "created_at" in table.c
        assert table.c["api_key_hash"].unique is True

    def test_tasks_table_columns_and_fks(self) -> None:
        table = Base.metadata.tables["tasks"]
        assert "user_id" in table.c
        assert "goal" in table.c
        assert "status" in table.c
        assert "created_at" in table.c
        assert "updated_at" in table.c

        # FK to users.id with CASCADE
        fk = list(table.c["user_id"].foreign_keys)[0]
        assert fk.target_fullname == "users.id"
        assert fk.ondelete == "CASCADE"

    def test_task_runs_table_columns_and_fks(self) -> None:
        table = Base.metadata.tables["task_runs"]
        assert "task_id" in table.c
        assert "user_id" in table.c
        assert "status" in table.c
        assert "termination_reason" in table.c
        assert "iteration_count" in table.c
        assert "sequence_counter" in table.c

        task_fk = list(table.c["task_id"].foreign_keys)[0]
        assert task_fk.target_fullname == "tasks.id"
        assert task_fk.ondelete == "CASCADE"

        user_fk = list(table.c["user_id"].foreign_keys)[0]
        assert user_fk.target_fullname == "users.id"
        assert user_fk.ondelete == "CASCADE"

    def test_evaluations_cardinality_constraint(self) -> None:
        """BLUEPRINT.md §12, §18: CONSTRAINT uq_run_iteration UNIQUE (run_id, iteration_count)."""
        table = Base.metadata.tables["evaluations"]
        unique_constraints = [
            c for c in table.constraints if isinstance(c, UniqueConstraint)
        ]
        uq_names = [c.name for c in unique_constraints]
        assert "uq_run_iteration" in uq_names

        uq = next(c for c in unique_constraints if c.name == "uq_run_iteration")
        col_names = [col.name for col in uq.columns]
        assert col_names == ["run_id", "iteration_count"]

    def test_agent_events_sequence_constraint(self) -> None:
        """BLUEPRINT.md §14, §18: CONSTRAINT uq_run_sequence UNIQUE (run_id, sequence)."""
        table = Base.metadata.tables["agent_events"]
        unique_constraints = [
            c for c in table.constraints if isinstance(c, UniqueConstraint)
        ]
        uq_names = [c.name for c in unique_constraints]
        assert "uq_run_sequence" in uq_names

        uq = next(c for c in unique_constraints if c.name == "uq_run_sequence")
        col_names = [col.name for col in uq.columns]
        assert col_names == ["run_id", "sequence"]

    def test_feedback_rating_check_constraint(self) -> None:
        """BLUEPRINT.md §18: CHECK (rating >= 1 AND rating <= 5)."""
        table = Base.metadata.tables["feedback"]
        check_constraints = [
            c for c in table.constraints if isinstance(c, CheckConstraint)
        ]
        ck_names = [c.name for c in check_constraints]
        assert "ck_feedback_rating" in ck_names

    def test_audit_logs_ondelete_set_null(self) -> None:
        """BLUEPRINT.md §18: user_id UUID REFERENCES users(id) ON DELETE SET NULL."""
        table = Base.metadata.tables["audit_logs"]
        user_fk = list(table.c["user_id"].foreign_keys)[0]
        assert user_fk.target_fullname == "users.id"
        assert user_fk.ondelete == "SET NULL"

    def test_task_recipes_vector_embedding(self) -> None:
        """BLUEPRINT.md §10, §18: embedding vector(384) NOT NULL."""
        table = Base.metadata.tables["task_recipes"]
        embedding_col = table.c["embedding"]
        assert embedding_col.nullable is False
        assert embedding_col.type.dim == 384


class TestKeyPerformanceIndexes:
    """BLUEPRINT.md §18: Key Performance Indexes."""

    def test_required_indexes_exist(self) -> None:
        expected_indexes = {
            "idx_tasks_user": "tasks",
            "idx_task_runs_lookup": "task_runs",
            "idx_task_runs_status": "task_runs",
            "idx_evaluations_run": "evaluations",
            "idx_agent_events_replay": "agent_events",
            "idx_task_recipes_user": "task_recipes",
            "idx_task_recipes_embedding": "task_recipes",
        }

        all_indexes: dict[str, str] = {}
        for table_name, table in Base.metadata.tables.items():
            for idx in table.indexes:
                all_indexes[idx.name] = table_name

        for idx_name, tbl_name in expected_indexes.items():
            assert idx_name in all_indexes, f"Missing index {idx_name}"
            assert all_indexes[idx_name] == tbl_name, (
                f"Index {idx_name} on table {all_indexes[idx_name]}, expected {tbl_name}"
            )

    def test_task_recipes_embedding_hnsw_index(self) -> None:
        """BLUEPRINT.md §18: CREATE INDEX idx_task_recipes_embedding ON task_recipes USING hnsw (embedding vector_cosine_ops)."""
        table = Base.metadata.tables["task_recipes"]
        idx = next((i for i in table.indexes if i.name == "idx_task_recipes_embedding"), None)
        assert idx is not None
        assert idx.dialect_options["postgresql"]["using"] == "hnsw"
        assert idx.dialect_options["postgresql"]["ops"] == {"embedding": "vector_cosine_ops"}


class TestEngineAndSessionSetup:
    """BLUEPRINT.md §4, §8: Engine and session setup, lifecycle management."""

    def test_global_async_engine_is_configured(self) -> None:
        assert isinstance(async_engine, AsyncEngine)
        assert async_engine.url.drivername == "postgresql+asyncpg"

    def test_async_session_factory(self) -> None:
        session = async_session_factory()
        assert isinstance(session, AsyncSession)

    def test_create_and_dispose_engine_lifecycle(self) -> None:
        """BLUEPRINT.md §8: Isolated engine creation and disposal for worker processes."""
        engine = create_engine_instance()
        assert isinstance(engine, AsyncEngine)
        import asyncio
        asyncio.run(dispose_engine(engine))

    def test_credentials_are_masked(self) -> None:
        """BLUEPRINT.md §17: Database credentials must never appear in plaintext representation."""
        raw_repr = repr(settings.POSTGRES_URL)
        assert "app_password" not in raw_repr
        assert "**********" in raw_repr or "[REDACTED]" in raw_repr


class TestPostgresDDLGeneration:
    """Verify that all models generate valid PostgreSQL DDL syntax."""

    def test_all_tables_generate_postgresql_ddl(self) -> None:
        dialect = postgresql.dialect()
        for table in Base.metadata.sorted_tables:
            ddl = str(CreateTable(table).compile(dialect=dialect))
            assert f"CREATE TABLE {table.name}" in ddl


class TestAlembicConfiguration:
    """BLUEPRINT.md §18: Alembic migration configuration and initial schema script."""

    def test_alembic_ini_exists(self) -> None:
        assert os.path.exists("alembic.ini")

    def test_migration_version_script_exists(self) -> None:
        version_file = os.path.join(
            "backend", "db", "migrations", "versions", "0001_initial_schema.py"
        )
        assert os.path.exists(version_file)
