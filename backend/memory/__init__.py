"""
Memory package for METIS agent.

Provides embedding generation, episodic experience logging, and recipe retrieval.
"""

from backend.memory.embeddings import (
    EmbeddingProvider,
    ExternalEmbeddingProvider,
    LightweightEmbeddingProvider,
    cosine_similarity,
    generate_embedding,
    get_embedding_provider,
    set_embedding_provider,
)
from backend.memory.experiences import record_experience
from backend.memory.retriever import retrieve_trusted_recipes

__all__ = [
    "EmbeddingProvider",
    "LightweightEmbeddingProvider",
    "ExternalEmbeddingProvider",
    "get_embedding_provider",
    "set_embedding_provider",
    "cosine_similarity",
    "generate_embedding",
    "record_experience",
    "retrieve_trusted_recipes",
]
