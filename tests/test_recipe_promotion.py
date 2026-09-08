"""Focused tests for database-enforced trusted recipe promotion."""

from __future__ import annotations

from decimal import Decimal
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from backend.db.models import RecipeCandidate, RecipeStatus, TaskRecipe
from backend.learning.recipes import promote_candidate
from backend.memory.embeddings import generate_embedding


class PromotionResult:
    def __init__(self, duplicate: tuple[TaskRecipe, float] | None) -> None:
        self.duplicate = duplicate

    def first(self) -> tuple[TaskRecipe, float] | None:
        return self.duplicate


class PromotionSession:
    def __init__(self, trusted_recipes: list[TaskRecipe]) -> None:
        self.trusted_recipes = trusted_recipes
        self.added: list[object] = []
        self.statements: list[object] = []

    async def execute(self, statement: object) -> PromotionResult:
        self.statements.append(statement)
        compiled = statement.compile(dialect=postgresql.dialect())
        params = compiled.params
        user_id = next(value for key, value in params.items() if "user_id" in key)
        task_type = next(value for key, value in params.items() if "task_type" in key)
        for recipe in self.trusted_recipes:
            if recipe.user_id == user_id and recipe.task_type == task_type:
                return PromotionResult((recipe, 1.0))
        return PromotionResult(None)

    def add(self, item: object) -> None:
        self.added.append(item)

    async def flush(self) -> None:
        return None


def make_candidate(user_id: uuid.UUID, task_type: str = "math") -> RecipeCandidate:
    return RecipeCandidate(
        id=uuid.uuid4(),
        source_task_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        user_id=user_id,
        task_type=task_type,
        problem_pattern="Compound interest calculation",
        context="Financial calculation",
        recommended_strategy="Use the compound interest formula",
        successful_steps=["Calculate"],
        failed_steps=[],
        tools_used=["calculator"],
        lesson="Account for compounding frequency",
        evidence="Verified result",
        evaluation_score=Decimal("9.0"),
        deterministic_pass=True,
        generalizable=True,
    )


def make_recipe(user_id: uuid.UUID, task_type: str = "math") -> TaskRecipe:
    return TaskRecipe(
        id=uuid.uuid4(),
        source_task_id=uuid.uuid4(),
        user_id=user_id,
        status=RecipeStatus.TRUSTED.value,
        task_type=task_type,
        problem_pattern="Compound interest calculation",
        context="Financial calculation",
        recommended_strategy="Use the compound interest formula",
        successful_steps=["Calculate"],
        failed_steps=[],
        tools_used=["calculator"],
        lesson="Account for compounding frequency",
        evidence="Verified result",
        evaluation_score=Decimal("9.0"),
        deterministic_pass=True,
        generalizable=True,
        embedding=generate_embedding("Compound interest calculation Use the compound interest formula"),
    )


@pytest.mark.asyncio
async def test_duplicate_candidate_is_skipped_and_remains_recorded() -> None:
    user_id = uuid.uuid4()
    candidate = make_candidate(user_id)
    existing = make_recipe(user_id)
    session = PromotionSession([existing])
    session.add(candidate)

    promoted = await promote_candidate(session, candidate=candidate)

    assert promoted is None
    assert session.added == [candidate]
    sql = str(session.statements[0].compile(dialect=postgresql.dialect())).lower()
    assert "task_recipes.user_id" in sql
    assert "task_recipes.task_type" in sql
    assert "task_recipes.status" in sql
    assert "embedding <=>" in sql


@pytest.mark.asyncio
async def test_different_user_does_not_suppress_promotion() -> None:
    candidate_user = uuid.uuid4()
    session = PromotionSession([make_recipe(uuid.uuid4())])
    candidate = make_candidate(candidate_user)

    promoted = await promote_candidate(session, candidate=candidate)

    assert promoted is not None
    assert promoted.user_id == candidate_user
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_different_task_type_does_not_suppress_promotion() -> None:
    user_id = uuid.uuid4()
    session = PromotionSession([make_recipe(user_id, task_type="research")])
    candidate = make_candidate(user_id, task_type="math")

    promoted = await promote_candidate(session, candidate=candidate)

    assert promoted is not None
    assert promoted.task_type == "math"
    assert len(session.added) == 1


@pytest.mark.asyncio
async def test_unique_promotion_inserts_one_trusted_recipe() -> None:
    user_id = uuid.uuid4()
    candidate = make_candidate(user_id)
    session = PromotionSession([])

    promoted = await promote_candidate(session, candidate=candidate)

    assert promoted is not None
    assert promoted.status == RecipeStatus.TRUSTED.value
    assert session.added == [promoted]