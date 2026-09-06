"""
Memory subsystem for episodic experiences, vector embeddings, and trusted recipe retrieval.

Source of truth: BLUEPRINT.md §3, §10, §11, §18.
"""

from backend.memory.embeddings import (
    EMBEDDING_DIM,
    cosine_similarity,
    generate_deterministic_embedding,
    generate_embedding,
)
from backend.memory.experiences import (
    create_experience,
    get_experience_by_id,
    get_experiences_for_run,
    get_experiences_for_task,
    get_experiences_for_user,
)
from backend.memory.retriever import (
    format_recipe_context,
    increment_recipe_usage,
    retrieve_recipes,
    serialize_recipe_for_state,
)

__all__ = [
    "EMBEDDING_DIM",
    "generate_embedding",
    "generate_deterministic_embedding",
    "cosine_similarity",
    "create_experience",
    "get_experience_by_id",
    "get_experiences_for_run",
    "get_experiences_for_task",
    "get_experiences_for_user",
    "format_recipe_context",
    "increment_recipe_usage",
    "retrieve_recipes",
    "serialize_recipe_for_state",
]
