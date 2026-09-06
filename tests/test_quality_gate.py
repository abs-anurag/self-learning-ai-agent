"""
Unit tests for Quality Gate validation and candidate promotion criteria.

Source of truth: BLUEPRINT.md §3, §7, §11, §12, §22.

Verifies:
1. Score 8.4 -> rejected ('candidate_only').
2. Score 8.5 with task_success = False -> rejected ('candidate_only').
3. Score 8.5 with duplicate recipe (similarity >= 0.90) -> skipped ('skip').
4. Score 8.5 with all checks passing -> promoted ('promoted').
5. Trivial experiences skip promotion ('skip').
6. Edge cases: deterministic_pass=False, tool_success=False, generalizable=False.
7. Schema validation: empty lesson, strategy, or problem_pattern rejected.
"""

from __future__ import annotations

from decimal import Decimal
import uuid
import pytest

from backend.core.config import settings
from backend.db.models import RecipeCandidate, RecipeStatus, TaskRecipe
from backend.learning.candidate import is_trivial_run
from backend.learning.quality_gate import (
    PROMOTION_SCORE_THRESHOLD,
    evaluate_quality_gate,
)
from backend.memory.embeddings import generate_embedding


class TestQualityGateCriteria:
    """Test suite matching BLUEPRINT.md §22 Quality Gate test requirements."""

    def test_score_8_4_is_rejected_as_candidate_only(self) -> None:
        """BLUEPRINT.md §22: Score 8.4 -> rejected (candidate_only)."""
        candidate = {
            "problem_pattern": "Compound interest calculation",
            "recommended_strategy": "Use compound interest formula A = P*(1+r/n)**(n*t)",
            "lesson": "Always account for compounding frequency",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=8.4,
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="The compound interest is $1,614.72",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert any("below promotion threshold" in r for r in res.rejection_reasons)

    def test_score_8_5_with_task_success_false_is_rejected(self) -> None:
        """BLUEPRINT.md §22: Score 8.5 with task_success = False -> rejected."""
        candidate = {
            "problem_pattern": "Compound interest calculation",
            "recommended_strategy": "Use compound interest formula",
            "lesson": "Formula needed",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=False,
            judge_score=8.5,
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="11614.72",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert "task_success is False" in res.rejection_reasons

    def test_score_8_5_with_duplicate_recipe_is_skipped(self) -> None:
        """BLUEPRINT.md §22: Score 8.5 with duplicate recipe -> skipped."""
        user_id = uuid.uuid4()
        existing_embedding = generate_embedding(
            "Compound interest calculation with monthly compounding"
        )
        candidate_embedding = generate_embedding(
            "Compound interest calculation with monthly compounding"
        )

        existing_recipe = TaskRecipe(
            id=uuid.uuid4(),
            source_task_id=uuid.uuid4(),
            user_id=user_id,
            status=RecipeStatus.TRUSTED.value,
            task_type="math",
            problem_pattern="Compound interest calculation",
            context="Monthly compounding",
            recommended_strategy="Use formula A = P*(1+r/n)**(n*t)",
            successful_steps=["step 1"],
            failed_steps=[],
            tools_used=["calculator"],
            lesson="Apply frequency formula",
            evidence="Exact match",
            evaluation_score=Decimal("9.0"),
            deterministic_pass=True,
            generalizable=True,
            embedding=existing_embedding,
        )

        candidate = {
            "problem_pattern": "Compound interest calculation",
            "recommended_strategy": "Use formula A = P*(1+r/n)**(n*t)",
            "lesson": "Apply frequency formula",
        }

        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=8.5,
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="11614.72",
            candidate_embedding=candidate_embedding,
            existing_recipes=[existing_recipe],
            duplicate_threshold=0.90,
        )
        assert res.passed is True
        assert res.is_duplicate is True
        assert res.learning_decision == "skip"
        assert res.duplicate_recipe_id == str(existing_recipe.id)

    def test_score_8_5_all_checks_passing_is_promoted(self) -> None:
        """BLUEPRINT.md §22: Score 8.5 with all checks passing -> promoted."""
        candidate = {
            "problem_pattern": "Compound interest calculation",
            "recommended_strategy": "Use formula A = P*(1+r/n)**(n*t)",
            "lesson": "Apply frequency formula",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=8.5,
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="11614.72",
            existing_recipes=[],
        )
        assert res.passed is True
        assert res.is_duplicate is False
        assert res.learning_decision == "promoted"
        assert len(res.rejection_reasons) == 0

    def test_high_score_promoted(self) -> None:
        """Score 9.5 passes promotion gate cleanly."""
        candidate = {
            "problem_pattern": "Multi-step research analysis",
            "recommended_strategy": "Search web then cross-check facts",
            "lesson": "Two independent sources required",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=Decimal("9.5"),
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="Detailed research report",
        )
        assert res.passed is True
        assert res.learning_decision == "promoted"


class TestDefenseInDepthChecks:
    """Intentional defense-in-depth gate checks per BLUEPRINT.md §7."""

    def test_deterministic_pass_false_rejected(self) -> None:
        candidate = {
            "problem_pattern": "Arithmetic",
            "recommended_strategy": "Calculator",
            "lesson": "Verify answers",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=9.0,
            deterministic_pass=False,
            tool_success=True,
            generalizable=True,
            final_answer="42",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert "deterministic_pass is False" in res.rejection_reasons

    def test_tool_success_false_rejected(self) -> None:
        candidate = {
            "problem_pattern": "File processing",
            "recommended_strategy": "Read file",
            "lesson": "Handle errors",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=9.0,
            deterministic_pass=True,
            tool_success=False,
            generalizable=True,
            final_answer="Processed",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert "tool_success is False" in res.rejection_reasons

    def test_generalizable_false_rejected(self) -> None:
        candidate = {
            "problem_pattern": "One-off task",
            "recommended_strategy": "Hardcode answer",
            "lesson": "Not reusable",
        }
        res = evaluate_quality_gate(
            candidate,
            task_success=True,
            judge_score=9.0,
            deterministic_pass=True,
            tool_success=True,
            generalizable=False,
            final_answer="Answer",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert "generalizable is False" in res.rejection_reasons

    def test_empty_schema_fields_rejected(self) -> None:
        """Candidate with empty lesson or strategy is rejected."""
        empty_lesson = {
            "problem_pattern": "Valid pattern",
            "recommended_strategy": "Valid strategy",
            "lesson": "",
        }
        res = evaluate_quality_gate(
            empty_lesson,
            task_success=True,
            judge_score=9.0,
            deterministic_pass=True,
            tool_success=True,
            generalizable=True,
            final_answer="Answer",
        )
        assert res.passed is False
        assert res.learning_decision == "candidate_only"
        assert any("lesson is empty" in r for r in res.rejection_reasons)


class TestTrivialRunDetection:
    """BLUEPRINT.md §7, §11, §22: Trivial experiences skip promotion."""

    def test_trivial_run_with_no_tools_is_skipped(self) -> None:
        assert is_trivial_run(goal="Hello world", tool_calls=[]) is True

    def test_trivial_run_flagged_in_evaluation(self) -> None:
        assert (
            is_trivial_run(
                goal="Calculate 2+2",
                tool_calls=[{"tool": "calc"}],
                evaluation={"is_trivial": True},
            )
            is True
        )

    def test_non_trivial_run_with_tools_is_not_trivial(self) -> None:
        assert (
            is_trivial_run(
                goal="Calculate the compound interest on $10,000 at 5% for 3 years",
                tool_calls=[{"name": "calculator", "input": "10000 * (1 + 0.05/12)**36"}],
                evaluation={"tool_call_count": 1, "is_trivial": False},
            )
            is False
        )
