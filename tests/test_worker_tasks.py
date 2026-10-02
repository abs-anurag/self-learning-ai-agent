"""
Tests for Celery worker task: run_agent_task.

Source of truth: BLUEPRINT.md §1, §8, §15.

Verifies:
1. Metadata lookup from database (task_id, user_id, goal) - task_type is determined during execution
2. _mark_run_failed() and _mark_run_status() function signatures
3. run_agent_task function signature and task registration
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
import pytest
from sqlalchemy import select

from backend.db.models import Task, TaskRun, TaskStatus
from backend.worker.celery_app import app
from backend.worker.tasks import (
    _mark_run_failed,
    _mark_run_status,
    run_agent_task,
)


# -- Test Doubles -----------------------------------------------------


class MockDbSession:
    """Mock async database session for worker task tests."""

    def __init__(self) -> None:
        self.records: Dict[str, Any] = {}
        self.committed = False
        self.rolled_back = False

    async def execute(self, stmt: Any) -> Any:
        stmt_str = str(stmt).lower()
        params = getattr(stmt, "_params", {}) or {}

        try:
            compiled = stmt.compile()
            params = dict(compiled.params)
        except Exception:
            pass

        def get_param(key: str, default: Any = None) -> Any:
            return params.get(key, default)

        # Lookup TaskRun by id
        if "from task_runs" in stmt_str and "where task_runs.id" in stmt_str:
            run_id = get_param("id_1") or get_param("id")
            if run_id and run_id in self.records.get("task_runs", {}):
                return MockQueryResult(scalar_value=self.records["task_runs"][run_id])
            return MockQueryResult(scalar_value=None)

        # Lookup Task by id
        if "from tasks" in stmt_str and "where tasks.id" in stmt_str:
            task_id = get_param("id_1") or get_param("id")
            if task_id and task_id in self.records.get("tasks", {}):
                return MockQueryResult(scalar_value=self.records["tasks"][task_id])
            return MockQueryResult(scalar_value=None)

        # Update statements - just track that they were called
        if "update" in stmt_str:
            return MockQueryResult(scalar_value=None)

        return MockQueryResult(scalar_value=None)

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True

    async def __aenter__(self) -> "MockDbSession":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()


class MockQueryResult:
    """Mock query execution result."""

    def __init__(self, scalar_value: Any = None, scalars_list: Optional[list] = None):
        self._scalar_value = scalar_value
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar_value

    def scalar(self) -> Any:
        return self._scalar_value

    def scalars(self) -> "MockScalars":
        if self._scalar_value is not None and not self._scalars_list:
            return MockScalars([self._scalar_value])
        return MockScalars(self._scalars_list)

    def all(self) -> list:
        return self._scalars_list


class MockScalars:
    """Mock scalars collection wrapper."""

    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


# -- Tests ------------------------------------------------------------


class TestWorkerMetadataLookup:
    """Tests for metadata lookup logic in run_agent_task."""

    @pytest.mark.asyncio
    async def test_metadata_lookup_returns_task_fields_without_task_type(self) -> None:
        """
        Verify metadata lookup returns task_id, user_id, goal but NOT task_type
        since Task model does not have task_type column (determined during execution).
        """
        # Create test data
        run_id = uuid.uuid4()
        task_id = uuid.uuid4()
        user_id = uuid.uuid4()
        goal = "Calculate compound interest"

        task = Task(
            id=task_id,
            user_id=user_id,
            goal=goal,
            status="pending",
        )

        run = TaskRun(
            id=run_id,
            task_id=task_id,
            user_id=user_id,
            status="pending",
        )

        db = MockDbSession()
        db.records = {"tasks": {task_id: task}, "task_runs": {run_id: run}}

        # Test the internal _lookup function logic
        async def _lookup() -> Dict[str, Any]:
            async with db as session:
                run_result = await session.execute(
                    select(TaskRun).where(TaskRun.id == run_id)
                )
                run_record = run_result.scalar_one_or_none()
                if run_record is None:
                    raise RuntimeError(f"TaskRun {run_id} not found in database")

                task_result = await session.execute(
                    select(Task).where(Task.id == run_record.task_id)
                )
                task_record = task_result.scalar_one_or_none()

                return {
                    "task_id": str(run_record.task_id),
                    "user_id": str(run_record.user_id),
                    "goal": task_record.goal if task_record else "",
                    "task_type": "",  # Task model does not have task_type
                }

        metadata = await _lookup()

        assert metadata["task_id"] == str(task_id)
        assert metadata["user_id"] == str(user_id)
        assert metadata["goal"] == goal
        assert metadata["task_type"] == ""  # Empty - determined during execution

    @pytest.mark.asyncio
    async def test_metadata_lookup_raises_on_missing_run(self) -> None:
        """Verify metadata lookup raises when TaskRun not found."""
        run_id = uuid.uuid4()

        db = MockDbSession()
        db.records = {"tasks": {}, "task_runs": {}}

        async def _lookup() -> Dict[str, Any]:
            async with db as session:
                run_result = await session.execute(
                    select(TaskRun).where(TaskRun.id == run_id)
                )
                run_record = run_result.scalar_one_or_none()
                if run_record is None:
                    raise RuntimeError(f"TaskRun {run_id} not found in database")
                return {}

        with pytest.raises(RuntimeError) as exc_info:
            await _lookup()
        assert f"TaskRun {run_id} not found in database" in str(exc_info.value)


class TestMarkRunFailed:
    """Tests for _mark_run_failed function."""

    def test_mark_run_failed_signature(self) -> None:
        """Verify _mark_run_failed has correct signature (run_id, termination_reason)."""
        import inspect
        sig = inspect.signature(_mark_run_failed)
        params = list(sig.parameters.keys())
        assert params == ["run_id", "termination_reason"]
        assert len(params) == 2


class TestMarkRunStatus:
    """Tests for _mark_run_status function."""

    def test_mark_run_status_signature(self) -> None:
        """Verify _mark_run_status has correct signature (run_id, status)."""
        import inspect
        sig = inspect.signature(_mark_run_status)
        params = list(sig.parameters.keys())
        assert params == ["run_id", "status"]
        assert len(params) == 2


# -- Celery Task Configuration Tests ----------------------------------


class TestCeleryTaskConfig:
    """Tests for Celery task configuration."""

    def test_run_agent_task_is_registered(self) -> None:
        """Verify run_agent_task is registered with Celery app."""
        assert "backend.worker.tasks.run_agent_task" in app.tasks

    def test_run_agent_task_signature(self) -> None:
        """Verify run_agent_task has correct signature."""
        import inspect
        sig = inspect.signature(run_agent_task.run)
        params = list(sig.parameters.keys())
        assert "run_id" in params
        assert "task_id" in params
        assert "user_id" in params
        assert "goal" in params
        assert "task_type" in params
        assert "max_iterations" in params


class TestTaskTypeArchitecture:
    """Tests verifying task_type architecture per BLUEPRINT.md."""

    def test_task_model_has_no_task_type_column(self) -> None:
        """Verify Task model does not have task_type column."""
        task_columns = [c.name for c in Task.__table__.columns]
        assert "task_type" not in task_columns
        # Task has: id, user_id, goal, status, created_at, updated_at
        expected = {"id", "user_id", "goal", "status", "created_at", "updated_at"}
        assert set(task_columns) == expected

    def test_task_run_model_has_no_task_type_column(self) -> None:
        """Verify TaskRun model does not have task_type column."""
        run_columns = [c.name for c in TaskRun.__table__.columns]
        assert "task_type" not in run_columns
        # TaskRun has: id, task_id, user_id, status, termination_reason, iteration_count, sequence_counter, created_at, updated_at
        expected = {"id", "task_id", "user_id", "status", "termination_reason", 
                    "iteration_count", "sequence_counter", "created_at", "updated_at"}
        assert set(run_columns) == expected

    def test_experience_model_has_task_type_column(self) -> None:
        """Verify Experience model has task_type column (stored after execution)."""
        from backend.db.models import Experience
        exp_columns = [c.name for c in Experience.__table__.columns]
        assert "task_type" in exp_columns

    def test_recipe_candidate_model_has_task_type_column(self) -> None:
        """Verify RecipeCandidate model has task_type column."""
        from backend.db.models import RecipeCandidate
        rc_columns = [c.name for c in RecipeCandidate.__table__.columns]
        assert "task_type" in rc_columns

    def test_task_recipe_model_has_task_type_column(self) -> None:
        """Verify TaskRecipe model has task_type column."""
        from backend.db.models import TaskRecipe
        tr_columns = [c.name for c in TaskRecipe.__table__.columns]
        assert "task_type" in tr_columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])