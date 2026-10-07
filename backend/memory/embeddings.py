"""
Lightweight and provider-based embedding generation for memory recipes.

Source of truth: BLUEPRINT.md §10, §18.
Architecture:
    EmbeddingProvider (ABC)
        ├── LightweightEmbeddingProvider (default/demo; zero heavy dependencies; 384-d normalized vector)
        └── ExternalEmbeddingProvider (HTTP/API provider when configured)
            └── fallback to LightweightEmbeddingProvider

Maintains the exact canonical interface:
- generate_embedding(text: str) -> list[float]
- cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float
- EMBEDDING_DIM = 384
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from abc import ABC, abstractmethod
from typing import List, Optional

from backend.core.config import ExecutionMode, settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

EMBEDDING_DIM = 384


class EmbeddingProvider(ABC):
    """Abstract interface for generating vector embeddings."""

    @abstractmethod
    def generate(self, text: str) -> list[float]:
        """Generate a unit-normalized vector of length EMBEDDING_DIM."""
        pass


class LightweightEmbeddingProvider(EmbeddingProvider):
    """
    Lightweight, deterministic semantic feature-hashing embedding provider.
    Zero external ML dependencies (no PyTorch, no transformers, no scipy/sklearn).
    Builds a normalized 384-dimensional vector preserving semantic word and n-gram overlap.
    """

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim

    def generate(self, text: str) -> list[float]:
        if not text or not text.strip():
            return [0.0] * self.dim

        vec = [0.0] * self.dim
        clean_text = text.lower().strip()
        words = re.findall(r"\w+", clean_text)

        # 1. Word-level hashing with semantic sign
        for word in words:
            h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dim
            sign = 1.0 if ((h >> 8) & 1) else -1.0
            vec[idx] += sign * 1.5

            # Bigram dispersion for word pairs
            h2 = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx2 = (h2 >> 4) % self.dim
            sign2 = 1.0 if (h2 & 1) else -1.0
            vec[idx2] += sign2 * 0.75

        # 2. Word-bigram hashing for word order semantics
        for i in range(len(words) - 1):
            bigram = f"{words[i]}_{words[i+1]}"
            h_bi = int(hashlib.sha256(bigram.encode("utf-8")).hexdigest(), 16)
            idx_bi = h_bi % self.dim
            sign_bi = 1.0 if ((h_bi >> 8) & 1) else -1.0
            vec[idx_bi] += sign_bi * 2.0

        # 3. Character n-gram hashing for subword/typo robustness
        for i in range(len(clean_text) - 2):
            tri = clean_text[i:i+3]
            h_tri = (ord(tri[0]) * 31 + ord(tri[1]) * 17 + ord(tri[2])) % self.dim
            vec[h_tri] += 0.3

        # 4. L2 normalization to unit hypersphere
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 1e-9:
            return [round(v / norm, 6) for v in vec]
        return [0.0] * self.dim


class ExternalEmbeddingProvider(EmbeddingProvider):
    """
    Provider-based embeddings calling an external HTTP API when configured.
    Falls back gracefully to LightweightEmbeddingProvider if no API key is set
    or if the remote endpoint fails.
    """

    def __init__(self, fallback: Optional[EmbeddingProvider] = None) -> None:
        self.fallback = fallback or LightweightEmbeddingProvider()
        self.api_key = os.getenv("EMBEDDING_API_KEY", "")

    def generate(self, text: str) -> list[float]:
        if not self.api_key or "placeholder" in self.api_key:
            return self.fallback.generate(text)

        # External embedding endpoint hook (e.g., Voyage/OpenAI compatible)
        try:
            import httpx
            endpoint = os.getenv("EMBEDDING_API_URL", "https://api.openai.com/v1/embeddings")
            model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"input": text, "model": model, "dimensions": EMBEDDING_DIM},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data["data"][0]["embedding"]
                    # Ensure dimensions and normalize
                    if len(emb) >= EMBEDDING_DIM:
                        emb = emb[:EMBEDDING_DIM]
                    else:
                        emb = emb + [0.0] * (EMBEDDING_DIM - len(emb))
                    norm = math.sqrt(sum(v * v for v in emb))
                    if norm > 1e-9:
                        return [round(v / norm, 6) for v in emb]
                    return emb
        except Exception as exc:
            logger.warning("External embedding provider call failed: %s; falling back to lightweight.", exc)

        return self.fallback.generate(text)


# Default singleton provider
_active_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the active embedding provider instance based on environment configuration."""
    global _active_provider
    if _active_provider is None:
        if settings.EXECUTION_MODE == ExecutionMode.LIVE and os.getenv("EMBEDDING_API_KEY"):
            _active_provider = ExternalEmbeddingProvider()
        else:
            _active_provider = LightweightEmbeddingProvider()
    return _active_provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """Set the active embedding provider."""
    global _active_provider
    _active_provider = provider


def generate_embedding(text: str) -> list[float]:
    """
    Canonical interface: Generate a 384-dimensional unit-normalized embedding.
    Preserves exact function signature across memory and learning modules.
    """
    return get_embedding_provider().generate(text)


def deterministic_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Backward-compatible helper for deterministic embeddings."""
    return LightweightEmbeddingProvider(dim=dim).generate(text)


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
