"""
Embedding generation and cosine similarity calculation for memory recipes.

Source of truth: BLUEPRINT.md §10, §18.
Uses 384-dimensional vector embeddings matching MiniLM (all-MiniLM-L6-v2).
Provides fallback deterministic embedding generation for demo mode and fast testing.
"""

from __future__ import annotations

import hashlib
import math
from typing import List, Optional

from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_DIM = 384
_model_instance = None


def _get_embedding_model():
    global _model_instance
    if _model_instance is None and settings.EXECUTION_MODE == ExecutionMode.LIVE:
        try:
            from sentence_transformers import SentenceTransformer
            _model_instance = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as exc:
            logger.warning("Could not load sentence-transformers model: %s. Using fallback.", exc)
            _model_instance = None
    return _model_instance


def deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Generate a deterministic, unit-normalized float vector of length `dim`.
    Used in demo mode and tests to guarantee reproducible similarity scores without PyTorch.
    """
    if not text:
        return [0.0] * dim

    # Use hash of words and character n-grams to distribute across dim
    vec = [0.0] * dim
    words = text.lower().split()
    for word in words:
        h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) else -1.0
        vec[idx] += sign

    # Add character-level distribution
    for i, ch in enumerate(text.lower()):
        idx = (ord(ch) * (i + 1)) % dim
        vec[idx] += 0.5

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 1e-9:
        return [round(v / norm, 6) for v in vec]
    return [0.0] * dim


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional embedding for text.
    In live mode with sentence-transformers available, uses all-MiniLM-L6-v2.
    Otherwise uses deterministic embedding.
    """
    model = _get_embedding_model()
    if model is not None:
        try:
            emb = model.encode(text, normalize_embeddings=True)
            return [round(float(x), 6) for x in emb]
        except Exception as exc:
            logger.warning("Error generating sentence embedding: %s", exc)

    return deterministic_embedding(text)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a <= 1e-9 or norm_b <= 1e-9:
        return 0.0

    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))
