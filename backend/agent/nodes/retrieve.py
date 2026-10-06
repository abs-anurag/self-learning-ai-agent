"""
Recipe retrieval node for LangGraph agent.

Source of truth: BLUEPRINT.md §8, §10, §11.

This node retrieves relevant prior recipes from the trusted recipe layer
to inform agent strategy for the current task.

FLOW:
1. Extract goal, understood_task, task_type from AgentState
2. Build query embedding text using build_query_embedding_text
3. Generate query embedding
4. Retrieve similar recipes using retrieve_similar_recipes
5. Format retrieved recipes with safety framing
6. Update state with retrieved_recipes and retrieval_count
7. Increment usage_count for each retrieved recipe

Design rules:
- Zero retrieval results are valid - never fabricate results
- Retrieved recipes are formatted with safety framing (prompt injection mitigation)
- usage_count increments when recipes are retrieved for actual use
- Errors are logged but do not halt execution (fallback to empty retrieval)
- Operates asynchronously for database and embedding operations
"""

from __future__ import annotations

import logging
from typing import Any

from backend.agent.state import AgentState
from backend.agent.runtime import get_db_session, get_runtime
from backend.core.config import settings
from backend.learning.recipes import increment_recipe_usage
from backend.memory.embeddings import build_query_embedding_text, generate_embedding
from backend.memory.retriever import (
    format_retrieved_recipes,
    retrieve_similar_recipes,
)

logger = logging.getLogger(__name__)


async def retrieve_node(state: AgentState, config: dict) -> dict:
    """
    LangGraph node: retrieve relevant prior recipes to inform agent strategy.

    Source: BLUEPRINT.md §8, §10, §11.

    Args:
        state: Current AgentState with goal, understood_task, task_type, user_id.
        config: Configuration dict containing:
            - settings: Application settings (optional, uses global if not provided)

    Returns:
        dict: State update with retrieved_recipes (list of dict) and retrieval_count (int).
              retrieved_recipes contains formatted recipe data with safety framing.

    State fields used:
        - Input: goal, understood_task, task_type, user_id
        - Output: retrieved_recipes (list[dict]), retrieval_count (int)

    Notes:
        - Zero retrieval results are valid and expected for novel tasks
        - Errors during retrieval do not halt execution (fallback to empty results)
        - Retrieved recipes have usage_count incremented in database
        - Uses RECIPE_SIMILARITY_THRESHOLD from config (default: 0.80)
    """
    task_id = state.get("task_id", "")
    task_type = state.get("task_type", "")
    logger.info(
        f"[retrieve_node] Starting recipe retrieval for task {task_id}, "
        f"task_type={task_type}"
    )

    # Extract required state fields
    goal = state.get("goal", "")
    understood_task = state.get("understood_task", "")
    user_id = state.get("user_id", "")

    # Validate required fields
    if not goal or not goal.strip():
        logger.warning("[retrieve_node] Goal is empty, skipping retrieval")
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }

    if not task_type or not task_type.strip():
        logger.warning("[retrieve_node] Task type is empty, skipping retrieval")
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }

    if not user_id or not user_id.strip():
        logger.warning("[retrieve_node] User ID is empty, skipping retrieval")
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }

    # Get database session from context variable or config
    db_session = get_db_session(config)
    if not db_session:
        logger.error("[retrieve_node] No db_session in context, skipping retrieval")
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }

    try:
        # Step 1: Build query embedding text
        query_text = build_query_embedding_text(
            goal=goal,
            understood_task=understood_task,
            task_type=task_type,
        )
        logger.debug(f"[retrieve_node] Query text built: {query_text[:100]}...")

        # Step 2: Generate query embedding
        query_embedding = generate_embedding(query_text)
        logger.debug(
            f"[retrieve_node] Query embedding generated, dimension={len(query_embedding)}"
        )

        # Step 3: Retrieve similar recipes
        # Use RECIPE_SIMILARITY_THRESHOLD from settings (default 0.80)
        threshold = settings.RECIPE_SIMILARITY_THRESHOLD
        limit = 5  # Default limit per retriever.py design

        recipes = await retrieve_similar_recipes(
            db_session=db_session,
            user_id=user_id,
            task_type=task_type,
            query_embedding=query_embedding,
            threshold=threshold,
            limit=limit,
        )

        retrieval_count = len(recipes)
        logger.info(
            f"[retrieve_node] Retrieved {retrieval_count} recipes "
            f"(threshold={threshold}, limit={limit})"
        )

        # Step 4: Format retrieved recipes with safety framing
        formatted_recipes = format_retrieved_recipes(recipes)

        # Step 5: Convert recipes to dict representation for state storage
        # Store essential fields only (exclude full model objects)
        recipe_dicts = []
        for recipe in recipes:
            recipe_dict = {
                "id": str(recipe.id),
                "task_type": recipe.task_type,
                "problem_pattern": recipe.problem_pattern,
                "context": recipe.context,
                "recommended_strategy": recipe.recommended_strategy,
                "lesson": recipe.lesson,
                "evidence": recipe.evidence,
                "tools_used": recipe.tools_used,
                "successful_steps": recipe.successful_steps,
                "failed_steps": recipe.failed_steps,
                "evaluation_score": float(recipe.evaluation_score),
                "deterministic_pass": recipe.deterministic_pass,
                "generalizable": recipe.generalizable,
                "confidence": float(recipe.confidence),
                "usage_count": recipe.usage_count,
                "success_after_reuse": recipe.success_after_reuse,
            }
            recipe_dicts.append(recipe_dict)

        # Step 6: Increment usage_count for each retrieved recipe
        # This signals that the recipe is being used to inform agent strategy
        for recipe in recipes:
            try:
                await increment_recipe_usage(
                    db_session=db_session,
                    recipe_id=recipe.id,
                )
                logger.debug(
                    f"[retrieve_node] Incremented usage_count for recipe {recipe.id}"
                )
            except Exception as e:
                # Log but don'"'"'t halt - usage counter is non-critical
                logger.warning(
                    f"[retrieve_node] Failed to increment usage_count for recipe {recipe.id}: {e}"
                )

        # Commit usage count updates
        try:
            await db_session.commit()
        except Exception as e:
            logger.warning(f"[retrieve_node] Failed to commit usage count updates: {e}")
            # Non-fatal - retrieval itself succeeded

        # Emit memory_retrieved event per BLUEPRINT.md §14
        runtime = get_runtime(config)
        if runtime:
            try:
                await runtime.emit_event(
                    task_id=state["task_id"],
                    run_id=state["run_id"],
                    user_id=state["user_id"],
                    event_type="memory_retrieved",
                    status="running",
                    metadata={
                        "retrieval_count": retrieval_count,
                        "task_type": task_type,
                    },
                    session=db_session,
                )
                logger.debug("[retrieve_node] Emitted memory_retrieved event")
            except Exception as e:
                logger.warning(f"[retrieve_node] Failed to emit memory_retrieved event: {e}")

        # Return state update with formatted string and metadata
        return {
            "retrieved_recipes": recipe_dicts,
            "retrieval_count": retrieval_count,
        }

    except ValueError as e:
        # Validation errors (empty text, invalid dimensions, etc.)
        logger.error(f"[retrieve_node] Validation error during retrieval: {e}")
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }

    except Exception as e:
        # Unexpected errors - log but don'"'"'t halt execution
        # Zero retrieval is a valid fallback for novel tasks
        logger.error(
            f"[retrieve_node] Unexpected error during recipe retrieval: {e}",
            exc_info=True,
        )
        return {
            "retrieved_recipes": [],
            "retrieval_count": 0,
        }
