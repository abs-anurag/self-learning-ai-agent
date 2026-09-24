"""
Tests for the quality gate functionality.

Source of truth: BLUEPRINT.md S10, S11 (quality criteria and thresholds).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.config import Settings
from backend.db.models import RecipeCandidate, CandidateStatus, TaskType
from backend.learning.quality_gate import (
    check_all_quality_criteria,
    evaluate_for_promotion,
)


@pytest.fixture
def settings():
    """Application settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.RECIPE_PROMOTION_THRESHOLD = 8.5
    settings.RECIPE_DUPLICATE_THRESHOLD = 0.90
    return settings


@pytest.fixture
def candidate():
    """A valid RecipeCandidate instance."""
    return RecipeCandidate(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        task_type=TaskType.CODE,
        problem_pattern="Test problem pattern",
        context={"key": "value"},
        recommended_strategy="Test strategy",
        successful_steps=["step1", "step2"],
        tools_used=["tool1", "tool2"],
        lesson="Test lesson",
        evaluation_score=Decimal("9.0"),
        deterministic_pass=True,
        generalizable=True,
        status=CandidateStatus.CANDIDATE,
    )


@pytest.fixture
def task_data():
    """Task data for testing."""
    return {
        "canonical_task_success": True,
        "tool_success": True,
    }


class TestCheckAllQualityCriteria:
    """Tests for the check_all_quality_criteria function."""

    def test_all_checks_pass(self, candidate, task_data, settings):
        """Test when all quality checks pass."""
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is True
        assert failed_checks == []

    def test_canonical_task_success_fails(self, candidate, task_data, settings):
        """Test when canonical_task_success is False."""
        task_data["canonical_task_success"] = False
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert "canonical_task_success=False" in failed_checks

    def test_evaluation_score_fails(self, candidate, task_data, settings):
        """Test when evaluation_score is below threshold."""
        candidate.evaluation_score = Decimal("8.0")
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert any(
            "evaluation_score=" in check and "< 8.5" in check
            for check in failed_checks
        )

    def test_deterministic_pass_fails(self, candidate, task_data, settings):
        """Test when deterministic_pass is False."""
        candidate.deterministic_pass = False
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert "deterministic_pass=False" in failed_checks

    def test_tool_success_fails(self, candidate, task_data, settings):
        """Test when tool_success is False."""
        task_data["tool_success"] = False
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert "tool_success=False" in failed_checks

    def test_generalizable_fails(self, candidate, task_data, settings):
        """Test when generalizable is False."""
        candidate.generalizable = False
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert "generalizable=False" in failed_checks

    @pytest.mark.parametrize(
        "field_name,field_value",
        [
            ("problem_pattern", ""),
            ("problem_pattern", None),
            ("recommended_strategy", ""),
            ("recommended_strategy", None),
            ("successful_steps", []),
            ("successful_steps", None),
            ("lesson", ""),
            ("lesson", None),
        ],
    )
    def test_required_fields_empty(
        self, candidate, task_data, settings, field_name, field_value
    ):
        """Test when required fields are empty or None."""
        setattr(candidate, field_name, field_value)
        all_passed, failed_checks = check_all_quality_criteria(
            candidate, task_data, settings
        )
        assert all_passed is False
        assert any(f"{field_name} is empty" in check or f"{field_name} is None" in check
                   for check in failed_checks)


class TestEvaluateForPromotion:
    """Tests for the evaluate_for_promotion function."""

    @pytest.mark.asyncio
    async def test_promoted_when_all_checks_pass_and_no_duplicate(
        self, candidate, task_data, settings
    ):
        """Test promotion decision when all checks pass and no duplicate found."""
        with patch(
            "backend.learning.quality_gate.build_recipe_embedding_text"
        ) as mock_build, patch(
            "backend.learning.quality_gate.generate_embedding"
        ) as mock_generate, patch(
            "backend.learning.quality_gate.find_similar_recipes"
        ) as mock_find:
            mock_build.return_value = "test embedding text"
            mock_generate.return_value = [0.1] * 384  # 384-dim embedding
            mock_find.return_value = []  # No duplicates

            result = await evaluate_for_promotion(
                MagicMock(), candidate, task_data, settings
            )

            assert result["decision"] == "promoted"
            assert result["embedding"] == [0.1] * 384
            assert result["duplicate_of"] is None
            assert "All quality checks passed" in result["reason"]

    @pytest.mark.asyncio
    async def test_candidate_only_when_quality_check_fails(
        self, candidate, task_data, settings
    ):
        """Test candidate_only decision when a quality check fails."""
        task_data["canonical_task_success"] = False  # Cause a failure

        result = await evaluate_for_promotion(
            MagicMock(), candidate, task_data, settings
        )

        assert result["decision"] == "candidate_only"
        assert result["embedding"] is None
        assert result["duplicate_of"] is None
        assert "Quality checks failed" in result["reason"]
        assert "canonical_task_success=False" in result["reason"]

    @pytest.mark.asyncio
    async def test_skip_when_duplicate_found(
        self, candidate, task_data, settings
    ):
        """Test skip decision when a duplicate recipe is found."""
        duplicate_recipe_id = uuid.uuid4()
        duplicate_recipe = MagicMock(id=duplicate_recipe_id)

        with patch(
            "backend.learning.quality_gate.build_recipe_embedding_text"
        ) as mock_build, patch(
            "backend.learning.quality_gate.generate_embedding"
        ) as mock_generate, patch(
            "backend.learning.quality_gate.find_similar_recipes"
        ) as mock_find:
            mock_build.return_value = "test embedding text"
            mock_generate.return_value = [0.1] * 384
            mock_find.return_value = [duplicate_recipe]  # Duplicate found

            result = await evaluate_for_promotion(
                MagicMock(), candidate, task_data, settings
            )

            assert result["decision"] == "skip"
            assert result["embedding"] is None
            assert result["duplicate_of"] == duplicate_recipe_id
            assert "Duplicate of existing recipe" in result["reason"]

    @pytest.mark.asyncio
    async def test_candidate_only_when_invalid_embedding_dimensions(
        self, candidate, task_data, settings
    ):
        """Test candidate_only when embedding dimensions are invalid."""
        with patch(
            "backend.learning.quality_gate.build_recipe_embedding_text"
        ) as mock_build, patch(
            "backend.learning.quality_gate.generate_embedding"
        ) as mock_generate:
            mock_build.return_value = "test embedding text"
            mock_generate.return_value = [0.1] * 100  # Invalid dimensions

            result = await evaluate_for_promotion(
                MagicMock(), candidate, task_data, settings
            )

            assert result["decision"] == "candidate_only"
            assert result["embedding"] is None
            assert result["duplicate_of"] is None
            assert "Invalid embedding dimensions" in result["reason"]

    @pytest.mark.asyncio
    async def test_candidate_only_when_embedding_generation_fails(
        self, candidate, task_data, settings
    ):
        """Test candidate_only when embedding generation fails."""
        with patch(
            "backend.learning.quality_gate.build_recipe_embedding_text"
        ) as mock_build, patch(
            "backend.learning.quality_gate.generate_embedding"
        ) as mock_generate:
            mock_build.return_value = "test embedding text"
            mock_generate.side_effect = Exception("Embedding error")

            result = await evaluate_for_promotion(
                MagicMock(), candidate, task_data, settings
            )

            assert result["decision"] == "candidate_only"
            assert result["embedding"] is None
            assert result["duplicate_of"] is None
            assert "Embedding generation failed" in result["reason"]

    @pytest.mark.asyncio
    async def test_candidate_only_when_duplicate_check_fails(
        self, candidate, task_data, settings
    ):
        """Test candidate_only when duplicate check fails."""
        with patch(
            "backend.learning.quality_gate.build_recipe_embedding_text"
        ) as mock_build, patch(
            "backend.learning.quality_gate.generate_embedding"
        ) as mock_generate, patch(
            "backend.learning.quality_gate.find_similar_recipes"
        ) as mock_find:
            mock_build.return_value = "test embedding text"
            mock_generate.return_value = [0.1] * 384
            mock_find.side_effect = Exception("Duplicate check error")

            result = await evaluate_for_promotion(
                MagicMock(), candidate, task_data, settings
            )

            assert result["decision"] == "candidate_only"
            assert result["embedding"] is None
            assert result["duplicate_of"] is None
            assert "Duplicate check failed" in result["reason"]

    @pytest.mark.asyncio
    async def test_candidate_only_when_missing_required_fields(
        self, candidate, task_data, settings
    ):
        """Test candidate_only when required fields are missing."""
        candidate.problem_pattern = ""  # Empty string

        result = await evaluate_for_promotion(
            MagicMock(), candidate, task_data, settings
        )

        assert result["decision"] == "candidate_only"
        assert result["embedding"] is None
        assert result["duplicate_of"] is None
        assert "Quality checks failed" in result["reason"]
        assert "problem_pattern is empty" in result["reason"]


if __name__ == "__main__":
    pytest.main([__file__])
