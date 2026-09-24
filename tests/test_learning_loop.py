"""
Tests for the learning loop functionality.
Source of truth: BLUEPRINT.md sections 8, 12, 13.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agent.nodes.learn import learn_node
from backend.agent.state import AgentState
from backend.core.config import Settings
from backend.db.models import CandidateStatus, RecipeCandidate, RecipeStatus, TaskType


@pytest.fixture
def settings():
    """Application settings for testing."""
    settings = MagicMock(spec=Settings)
    settings.RECIPE_PROMOTION_THRESHOLD = 8.5
    settings.RECIPE_DUPLICATE_THRESHOLD = 0.90
    settings.TASK_SUCCESS_THRESHOLD = 7.0
    return settings


@pytest.fixture
def mock_runtime():
    """Mock AgentRuntime for testing."""
    return AsyncMock()


@pytest.fixture
def mock_db_session():
    """Mock AsyncSession for testing."""
    return AsyncMock()


@pytest.fixture
def base_state():
    """Base AgentState for testing."""
    return {
        "task_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "task_type": TaskType.CODE,
        "goal": "Test task goal",
        "plan": ["step1", "step2"],
        "observations": ["observation1", "observation2"],
        "tool_calls": [{"tool_name": "tool1"}, {"tool_name": "tool2"}],
        "reflection": "Test reflection",
        "understood_task": "Test understood task",
        "evaluation": {
            "task_success": True,
            "deterministic_pass": True,
            "tool_success": True,
            "judge_score": 8.5,
            "final_answer_present": True,
            "generalizable": True,
        },
        "final_response": "Test final response",
    }


@pytest.mark.asyncio
async def test_learn_node_trivial_success(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node with trivial success (no candidate extracted)."""
    # Mock extract_candidate_recipe to return None (trivial success)
    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=None):
        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return skip decision
    assert result["learning_decision"] == "skip"

    # Should not emit any events
    mock_runtime.emit_event.assert_not_called()

    # Should not call quality gate or recipe creation
    # (extract_candidate_recipe was mocked to return None)


@pytest.mark.asyncio
async def test_learn_node_non_trivial_success_promoted(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node with non-trivial success leading to promotion."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()
    mock_candidate.user_id = base_state["user_id"]
    mock_candidate.source_task_id = base_state["task_id"]
    mock_candidate.task_type = base_state["task_type"]
    mock_candidate.problem_pattern = "Test problem pattern"
    mock_candidate.context = "Test context"
    mock_candidate.recommended_strategy = "Test strategy"
    mock_candidate.successful_steps = ["step1", "step2"]
    mock_candidate.tools_used = ["tool1", "tool2"]
    mock_candidate.lesson = "Test lesson"
    mock_candidate.evidence = "Test evidence"
    mock_candidate.evaluation_score = 8.5
    mock_candidate.deterministic_pass = True
    mock_candidate.generalizable = True

    # Mock quality gate result for promotion
    mock_quality_gate_result = {
        "decision": "promoted",
        "embedding": [0.1] * 384,  # 384-dim embedding
    }

    # Mock trusted recipe creation
    mock_trusted_recipe = MagicMock()
    mock_trusted_recipe.id = uuid.uuid4()

    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate), \
         patch("backend.agent.nodes.learn.evaluate_for_promotion", return_value=mock_quality_gate_result), \
         patch("backend.agent.nodes.learn.create_trusted_recipe", return_value=mock_trusted_recipe):

        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return promoted decision
    assert result["learning_decision"] == "promoted"

    # Should emit learning_candidate_created event
    mock_runtime.emit_event.assert_any_call(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_candidate_created",
        status="running",
        metadata={"candidate_id": str(mock_candidate.id)},
    )

    # Should emit learning_saved event
    mock_runtime.emit_event.assert_any_call(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_saved",
        status="success",
        metadata={"recipe_id": str(mock_trusted_recipe.id)},
    )

    # Verify calls were made
    assert mock_runtime.emit_event.call_count == 2


@pytest.mark.asyncio
async def test_learn_node_non_trivial_success_candidate_only(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node with non-trivial success leading to candidate_only decision."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()

    # Mock quality gate result for candidate_only
    mock_quality_gate_result = {
        "decision": "candidate_only",
        "embedding": None,
    }

    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate), \
         patch("backend.agent.nodes.learn.evaluate_for_promotion", return_value=mock_quality_gate_result):

        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return candidate_only decision
    assert result["learning_decision"] == "candidate_only"

    # Should emit learning_candidate_created event
    mock_runtime.emit_event.assert_called_once_with(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_candidate_created",
        status="running",
        metadata={"candidate_id": str(mock_candidate.id)},
    )

    # Should NOT emit learning_saved event
    # Check that learning_saved was not called
    emit_calls = mock_runtime.emit_event.call_args_list
    learning_saved_calls = [
        call for call in emit_calls
        if call[1]["event_type"] == "learning_saved"
    ]
    assert len(learning_saved_calls) == 0


@pytest.mark.asyncio
async def test_learn_node_non_trivial_success_skip(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node with non-trivial success leading to skip decision (duplicate)."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()

    # Mock quality gate result for skip (duplicate)
    mock_quality_gate_result = {
        "decision": "skip",
        "embedding": None,
        "duplicate_of": uuid.uuid4(),
    }

    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate), \
         patch("backend.agent.nodes.learn.evaluate_for_promotion", return_value=mock_quality_gate_result):

        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return skip decision
    assert result["learning_decision"] == "skip"

    # Should emit learning_candidate_created event
    mock_runtime.emit_event.assert_called_once_with(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_candidate_created",
        status="running",
        metadata={"candidate_id": str(mock_candidate.id)},
    )


@pytest.mark.asyncio
async def test_learn_node_success_after_reuse_increment(base_state, mock_runtime, mock_db_session, settings):
    """Test that success_after_reuse is incremented for retrieved recipes when task succeeds after reuse."""
    # Set up retrieved recipes in state
    recipe_id_1 = uuid.uuid4()
    recipe_id_2 = uuid.uuid4()
    base_state["retrieved_recipes"] = [
        {"id": str(recipe_id_1)},
        {"id": str(recipe_id_2)},
        {"id": "invalid-id"},  # Should be skipped
    ]

    # Mock extract_candidate_recipe to return None (trivial success to avoid complexity)
    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=None), \
         patch("backend.agent.nodes.learn.increment_recipe_success") as mock_increment:

        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return skip decision (trivial success)
    assert result["learning_decision"] == "skip"

    # Should call increment_recipe_success for valid recipe IDs
    assert mock_increment.call_count == 2
    mock_increment.assert_any_call(db_session=mock_db_session, recipe_id=recipe_id_1)
    mock_increment.assert_any_call(db_session=mock_db_session, recipe_id=recipe_id_2)

    # Should commit the session
    mock_db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_learn_node_error_in_candidate_extraction(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node handles errors in candidate extraction gracefully."""
    # Mock extract_candidate_recipe to raise an exception
    with patch("backend.agent.nodes.learn.extract_candidate_recipe", side_effect=Exception("Extraction error")):
        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return skip decision on error
    assert result["learning_decision"] == "skip"

    # Should not emit events due to early return
    mock_runtime.emit_event.assert_not_called()


@pytest.mark.asyncio
async def test_learn_node_error_in_quality_gate(base_state, mock_runtime, mock_db_session, settings):
    """Test learn_node handles errors in quality gate evaluation."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()

    # Mock extract_candidate_recipe to return candidate
    # Mock evaluate_for_promotion to raise an exception
    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate), \
         patch("backend.agent.nodes.learn.evaluate_for_promotion", side_effect=Exception("Quality gate error")):

        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return skip decision on quality gate error
    assert result["learning_decision"] == "skip"

    # Should have emitted learning_candidate_created event before the error
    mock_runtime.emit_event.assert_called_once_with(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_candidate_created",
        status="running",
        metadata={"candidate_id": str(mock_candidate.id)},
    )


@pytest.mark.asyncio
async def test_learn_node_no_db_session_for_quality_gate(base_state, mock_runtime, settings):
    """Test learn_node handles missing db_session for quality gate."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()

    # Mock extract_candidate_recipe to return candidate
    # Provide config without db_session
    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate):
        result = await learn_node(
            state=base_state,
            config={
                "runtime": mock_runtime,
                # Intentionally omitting db_session
                "settings": settings,
            }
        )

    # Should return skip decision when no db_session for quality gate
    assert result["learning_decision"] == "skip"

    # Should have emitted learning_candidate_created event
    mock_runtime.emit_event.assert_called_once_with(
        task_id=base_state["task_id"],
        run_id=base_state["run_id"],
        user_id=base_state["user_id"],
        event_type="learning_candidate_created",
        status="running",
        metadata={"candidate_id": str(mock_candidate.id)},
    )


@pytest.mark.asyncio
async def test_learn_node_no_runtime_provided(base_state, mock_db_session, settings):
    """Test learn_node works when no runtime is provided (should not crash)."""
    # Mock candidate object
    mock_candidate = MagicMock(spec=RecipeCandidate)
    mock_candidate.id = uuid.uuid4()

    # Mock quality gate result for promotion
    mock_quality_gate_result = {
        "decision": "promoted",
        "embedding": [0.1] * 384,
    }

    # Mock trusted recipe creation
    mock_trusted_recipe = MagicMock()
    mock_trusted_recipe.id = uuid.uuid4()

    with patch("backend.agent.nodes.learn.extract_candidate_recipe", return_value=mock_candidate), \
         patch("backend.agent.nodes.learn.evaluate_for_promotion", return_value=mock_quality_gate_result), \
         patch("backend.agent.nodes.learn.create_trusted_recipe", return_value=mock_trusted_recipe):

        result = await learn_node(
            state=base_state,
            config={
                # Intentionally omitting runtime
                "db_session": mock_db_session,
                "settings": settings,
            }
        )

    # Should return promoted decision
    assert result["learning_decision"] == "promoted"

    # Should not attempt to emit events (no runtime)
    # No assertions needed - if it didn't crash, the test passes


if __name__ == "__main__":
    pytest.main([__file__])
