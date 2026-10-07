"""
Memory package for METIS agent.

Provides embedding generation, episodic experience logging, and recipe retrieval.
"""

from backend.memory.embeddings import cosine_similarity, generate_embedding
from backend.memory.experiences import record_experience
from backend.memory.retriever import retrieve_trusted_recipes

__all__ = [
    "cosine_similarity",
    "generate_embedding",
    "record_experience",
    "retrieve_trusted_recipes",
]
