"""Ownership tests for trusted recipe ID lookups."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

from backend.db.models import RecipeStatus, TaskRecipe
from backend.learning.recipes import get_recipe_by_id


class LookupResult:
    def __init__(self, recipe: TaskRecipe | None) -> None:
        self.recipe = recipe

    def scalar_one_or_none(self) -> TaskRecipe | None:
        return self.recipe


class LookupSession:
    def __init__(self, recipe: TaskRecipe | None) -> None:
        self.recipe = recipe
        self.statement: object | None = None

    async def execute(self, statement: object) -> LookupResult:
        self.statement = statement
        compiled = statement.compile(dialect=postgresql.dialect())
        params = compiled.params
        recipe_id = next(value for key, value in params.items() if key.startswith("id"))
        user_id = next(value for key, value in params.items() if "user_id" in key)
        if self.recipe is not None and self.recipe.id == recipe_id and self.recipe.user_id == user_id:
            return LookupResult(self.recipe)
        return LookupResult(None)


def make_recipe(user_id: uuid.UUID) -> TaskRecipe:
    return TaskRecipe(
        id=uuid.uuid4(),
        source_task_id=uuid.uuid4(),
        user_id=user_id,
        status=RecipeStatus.TRUSTED.value,
        task_type="math",
        problem_pattern="Arithmetic",
        context="Test context",
        recommended_strategy="Use the calculator",
        successful_steps=["Calculate"],
        failed_steps=[],
        tools_used=["calculator"],
        lesson="Verify the result",
        evidence="Test evidence",
        evaluation_score=9.0,
        deterministic_pass=True,
        generalizable=True,
        embedding=[0.0] * 384,
    )


@pytest.mark.asyncio
async def test_owner_can_retrieve_recipe_by_id() -> None:
    user_id = uuid.uuid4()
    recipe = make_recipe(user_id)
    session = LookupSession(recipe)

    result = await get_recipe_by_id(session, recipe.id, user_id=user_id)

    assert result is recipe


@pytest.mark.asyncio
async def test_different_user_cannot_retrieve_recipe() -> None:
    recipe = make_recipe(uuid.uuid4())
    session = LookupSession(recipe)

    result = await get_recipe_by_id(session, recipe.id, user_id=uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_missing_recipe_preserves_not_found_behavior() -> None:
    session = LookupSession(None)

    result = await get_recipe_by_id(session, uuid.uuid4(), user_id=uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_lookup_query_keeps_id_and_owner_filters() -> None:
    user_id = uuid.uuid4()
    recipe = make_recipe(user_id)
    session = LookupSession(recipe)

    await get_recipe_by_id(session, recipe.id, user_id=user_id)

    sql = str(session.statement.compile(dialect=postgresql.dialect())).lower()
    assert "task_recipes.id" in sql
    assert "task_recipes.user_id" in sql