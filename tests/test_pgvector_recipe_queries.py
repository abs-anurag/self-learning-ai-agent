"""SQL-shape tests for pgvector-backed recipe retrieval and deduplication."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from backend.core.config import ExecutionMode
from backend.learning.recipes import find_duplicate_recipe
from backend.memory.retriever import increment_recipe_usage, retrieve_recipes


class EmptyResult:
    def scalars(self) -> "EmptyResult":
        return self

    def all(self) -> list[object]:
        return []

    def first(self) -> None:
        return None


class CapturingSession:
    def __init__(self) -> None:
        self.statements = []
        self.rolled_back = False

    async def execute(self, statement: object) -> EmptyResult:
        self.statements.append(statement)
        return EmptyResult()

    async def flush(self) -> None:
        raise AssertionError("No recipe should be incremented when the query is empty")

    async def rollback(self) -> None:
        self.rolled_back = True


class CounterStore:
    def __init__(self) -> None:
        self.usage_count = 0
        self.task_rolled_back = False


class CounterSession:
    def __init__(self, store: CounterStore) -> None:
        self.store = store

    async def execute(self, statement: object) -> None:
        self.store.usage_count += 1


class CounterTransaction:
    def __init__(self, store: CounterStore) -> None:
        self.session = CounterSession(store)

    async def __aenter__(self) -> CounterSession:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class CounterSessionFactory:
    def __init__(self, store: CounterStore) -> None:
        self.store = store

    def begin(self) -> CounterTransaction:
        return CounterTransaction(self.store)


def compiled_sql(statement: object) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).lower()


@pytest.mark.asyncio
async def test_live_retrieval_uses_database_cosine_distance() -> None:
    session = CapturingSession()
    user_id = uuid.uuid4()

    recipes = await retrieve_recipes(
        session,
        user_id=user_id,
        task_type="math",
        goal="Calculate compound interest",
        limit=3,
        similarity_threshold=0.80,
        mode=ExecutionMode.LIVE,
    )

    assert recipes == []
    assert len(session.statements) == 1
    sql = compiled_sql(session.statements[0])
    assert "embedding <=>" in sql
    assert "order by task_recipes.embedding <=>" in sql
    assert "limit" in sql
    assert "task_recipes.user_id" in sql
    assert "task_recipes.status" in sql
    assert "task_recipes.task_type" in sql
    assert "<=" in sql


@pytest.mark.asyncio
async def test_duplicate_detection_uses_database_cosine_distance() -> None:
    session = CapturingSession()

    duplicate = await find_duplicate_recipe(
        session,
        user_id=uuid.uuid4(),
        task_type="math",
        candidate_embedding=[0.0] * 384,
        threshold=0.90,
    )

    assert duplicate is None
    assert len(session.statements) == 1
    sql = compiled_sql(session.statements[0])
    assert "embedding <=>" in sql
    assert "order by task_recipes.embedding <=>" in sql
    assert "limit" in sql
    assert "task_recipes.user_id" in sql
    assert "task_recipes.status" in sql
    assert "task_recipes.task_type" in sql
    assert "<=" in sql


@pytest.mark.asyncio
async def test_usage_increment_survives_later_task_rollback() -> None:
    store = CounterStore()
    counter_session_factory = CounterSessionFactory(store)
    task_session = CapturingSession()

    await increment_recipe_usage(
        task_session,
        uuid.uuid4(),
        counter_session_factory=counter_session_factory,
    )

    await task_session.rollback()
    store.task_rolled_back = task_session.rolled_back
    assert store.task_rolled_back is True
    assert store.usage_count == 1
