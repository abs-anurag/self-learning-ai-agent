"""
Sentence embedding generation for recipe retrieval.

Source of truth: BLUEPRINT.md S10, S11 (vector retrieval), S18 (Vector(384)).

Uses sentence-transformers with all-MiniLM-L6-v2 to generate 384-dimensional
embeddings for semantic recipe matching and duplicate detection.

Design rules:
- Embeddings are deterministic: identical input → identical output.
- Recipe embedding text excludes mutable metadata (usage_count, timestamps, IDs).
- Empty or whitespace-only input is rejected; no fake/zero/random embeddings.
- Model loading failures propagate as exceptions (no silent fallback).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from sentence_transformers import SentenceTransformer


# Model singleton cache
_MODEL_INSTANCE: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    """
    Load and cache the sentence-transformers model.

    Returns:
        SentenceTransformer: The all-MiniLM-L6-v2 model instance.

    Raises:
        Exception: If model loading fails for any reason (network, memory, etc.).

    Notes:
        - Model is cached after first load for performance.
        - Produces 384-dimensional embeddings.
        - Model: sentence-transformers/all-MiniLM-L6-v2
    """
    global _MODEL_INSTANCE

    if _MODEL_INSTANCE is None:
        try:
            # Load the model - will download on first use
            _MODEL_INSTANCE = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            # Propagate exact error - no silent fallback
            raise Exception(
                f"Failed to load sentence-transformers model 'all-MiniLM-L6-v2': {e}"
            ) from e

    return _MODEL_INSTANCE


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional embedding vector for the given text.

    Args:
        text: Input text to embed. Must not be empty or whitespace-only.

    Returns:
        list[float]: 384-dimensional embedding vector.

    Raises:
        ValueError: If text is empty or contains only whitespace.
        Exception: If model loading or encoding fails.

    Notes:
        - Embeddings are deterministic for identical input.
        - Returns a Python list (not numpy array) for SQLAlchemy pgvector.
    """
    # Reject empty or whitespace-only input
    if not text or not text.strip():
        raise ValueError(
            "Cannot generate embedding for empty or whitespace-only text. "
            "Do NOT create fake/zero/random embeddings."
        )

    try:
        model = get_embedding_model()
        # encode() returns numpy array; convert to list for pgvector
        embedding = model.encode(text, convert_to_tensor=False)
        return embedding.tolist()
    except ValueError:
        # Re-raise our own validation errors
        raise
    except Exception as e:
        # Propagate model/encoding failures with context
        raise Exception(f"Failed to generate embedding: {e}") from e


def build_recipe_embedding_text(recipe_dict: dict[str, Any]) -> str:
    """
    Build deterministic embedding text from a recipe dictionary.

    Args:
        recipe_dict: Recipe data (from RecipeCandidate or TaskRecipe model).
            Expected semantic fields: problem_pattern, context,
            recommended_strategy, successful_steps, tools_used, lesson.

    Returns:
        str: Normalized, deterministic text representation for embedding.

    Notes:
        - Field order is fixed: problem_pattern, context, recommended_strategy,
          successful_steps, tools_used, lesson.
        - Empty semantic fields are skipped.
        - Lists/dicts use stable JSON serialization (sorted keys).
        - Whitespace is normalized.
        - EXCLUDES: timestamps, UUIDs, database IDs, random values,
          usage_count, success_after_reuse, confidence, version, status.
        - Identical recipes → identical text → identical embeddings.
    """
    # Fixed field order for determinism
    semantic_fields = [
        "problem_pattern",
        "context",
        "recommended_strategy",
        "successful_steps",
        "tools_used",
        "lesson",
    ]

    parts = []

    for field in semantic_fields:
        value = recipe_dict.get(field)

        # Skip None, empty strings, empty lists, empty dicts
        if not value:
            continue

        # Fixed label for this field
        label = field.replace("_", " ").title()

        # Serialize complex types (lists, dicts) with stable JSON
        if isinstance(value, (list, dict)):
            # sort_keys=True ensures deterministic JSON output
            value_str = json.dumps(value, sort_keys=True, ensure_ascii=False)
        else:
            value_str = str(value)

        # Normalize whitespace: collapse multiple spaces/newlines to single space
        value_str = re.sub(r'\s+', ' ', value_str).strip()

        if value_str:  # Only add if not empty after normalization
            parts.append(f"{label}: {value_str}")

    # Join with newlines for readability (doesn't affect embedding quality)
    return "\n".join(parts)


def build_query_embedding_text(
    goal: str,
    understood_task: str = "",
    task_type: str = "",
) -> str:
    """
    Build embedding text for a live query (incoming task).

    Args:
        goal: User's original task goal (required).
        understood_task: Agent's interpretation of the task (optional).
        task_type: Classified task type (optional).

    Returns:
        str: Normalized text representation for query embedding.

    Raises:
        ValueError: If goal is empty or whitespace-only.

    Notes:
        - Goal is required; other fields are optional enrichment.
        - Whitespace is normalized for consistency with recipe embeddings.
        - Query embeddings can be compared to recipe embeddings via cosine similarity.
    """
    if not goal or not goal.strip():
        raise ValueError("Query goal cannot be empty or whitespace-only.")

    parts = []

    # Goal is always present
    goal_normalized = re.sub(r'\s+', ' ', goal).strip()
    parts.append(f"Goal: {goal_normalized}")

    # Optional fields
    if understood_task and understood_task.strip():
        understood_normalized = re.sub(r'\s+', ' ', understood_task).strip()
        parts.append(f"Understood Task: {understood_normalized}")

    if task_type and task_type.strip():
        task_type_normalized = re.sub(r'\s+', ' ', task_type).strip()
        parts.append(f"Task Type: {task_type_normalized}")

    return "\n".join(parts)