"""
Embedding generation and cosine similarity calculation for semantic memory.

Source of truth: BLUEPRINT.md §10, §18, Appendix A.

Design rules:
- Embeddings use 384 dimensions matching sentence-transformers all-MiniLM-L6-v2 and pgvector vector(384).
- Dual mode support (§10):
  - In live mode (EXECUTION_MODE=live), uses sentence-transformers all-MiniLM-L6-v2 when available.
  - In demo mode (EXECUTION_MODE=demo) or when sentence-transformers is unavailable,
    uses a deterministic token-hashed unit embedding generator so tests and demo runs
    remain completely deterministic, reproducible, and fast without external model downloads.
- Vectors are always L2-normalized to unit length (norm == 1.0).
- Cosine similarity handles zero-vectors safely and returns values bounded in [-1.0, 1.0].
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Optional, Sequence

from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_DIM: int = 384

# Cached sentence-transformers model instance
_model_instance = None
_model_load_attempted: bool = False


def _get_sentence_transformer():
    """Lazily load sentence-transformers model if in live mode and library is available."""
    global _model_instance, _model_load_attempted
    if _model_load_attempted:
        return _model_instance

    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer
        _model_instance = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Loaded sentence-transformers all-MiniLM-L6-v2 embedding model")
    except Exception as exc:
        logger.warning(
            "Could not load sentence-transformers (%s); falling back to deterministic embedding generator",
            exc,
        )
        _model_instance = None

    return _model_instance


def _deterministic_word_vector(word: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Derive a pseudo-random pseudo-orthogonal unit vector for a single word."""
    h = hashlib.sha256(word.lower().encode("utf-8")).digest()
    vec = [0.0] * dim
    for i in range(dim):
        byte_idx = (i * 4) % len(h)
        val = int.from_bytes(h[byte_idx:byte_idx + 4], byteorder="big", signed=True)
        if (i * 4) >= len(h) and i % (len(h) // 4) == 0:
            h = hashlib.sha256(h + i.to_bytes(4, byteorder="big")).digest()
        vec[i] = float(val) / (2**31)

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0.0:
        return [x / norm for x in vec]
    return [0.0] * dim


def generate_deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """
    Generate a deterministic 384-dimensional unit vector from text tokens.
    Tokens are hashed and averaged, yielding high cosine similarity for similar vocabularies
    and low similarity for orthogonal vocabularies.
    """
    cleaned = re.sub(r"[^\w\s]", " ", text.lower()).strip()
    tokens = [t for t in cleaned.split() if t]

    if not tokens:
        val = 1.0 / math.sqrt(dim)
        return [val] * dim

    accum = [0.0] * dim
    for token in tokens:
        w_vec = _deterministic_word_vector(token, dim=dim)
        for i in range(dim):
            accum[i] += w_vec[i]

    norm = math.sqrt(sum(x * x for x in accum))
    if norm > 0.0:
        return [x / norm for x in accum]

    val = 1.0 / math.sqrt(dim)
    return [val] * dim


def generate_embedding(text: str) -> list[float]:
    """
    Generate a 384-dimensional embedding vector for the given text.

    Uses sentence-transformers if EXECUTION_MODE=live and available;
    otherwise falls back to deterministic token-hashed embeddings.
    """
    if settings.EXECUTION_MODE == ExecutionMode.LIVE:
        model = _get_sentence_transformer()
        if model is not None:
            try:
                raw = model.encode(text, normalize_embeddings=True)
                return [float(x) for x in raw]
            except Exception as exc:
                logger.error("Live embedding inference failed: %s; falling back to deterministic", exc)

    return generate_deterministic_embedding(text, dim=EMBEDDING_DIM)


def cosine_similarity(
    vec_a: Sequence[float],
    vec_b: Sequence[float],
) -> float:
    """
    Compute cosine similarity between two numeric vectors.
    Returns float in range [-1.0, 1.0].
    Returns 0.0 if either vector has zero magnitude.
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(
            f"Vector dimensions must match for cosine similarity: {len(vec_a)} != {len(vec_b)}"
        )

    dot_product = 0.0
    norm_a_sq = 0.0
    norm_b_sq = 0.0

    for a, b in zip(vec_a, vec_b):
        dot_product += a * b
        norm_a_sq += a * a
        norm_b_sq += b * b

    if norm_a_sq <= 0.0 or norm_b_sq <= 0.0:
        return 0.0

    sim = dot_product / (math.sqrt(norm_a_sq) * math.sqrt(norm_b_sq))
    return max(-1.0, min(1.0, float(sim)))
