"""
Application configuration loaded from environment variables / .env file.

Source of truth: BLUEPRINT.md S23 (.env.example specification),
S2 (max_iterations), S11 (evaluation thresholds), S14 (replay constants),
S17 (security), Appendix A (tech stack versions).

Uses pydantic-settings for type-safe parsing and validation.
Sensitive values use SecretStr so they are masked in repr/logs.
"""

from __future__ import annotations

from enum import Enum

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ExecutionMode(str, Enum):
    """BLUEPRINT.md S2: dual execution modes."""
    DEMO = "demo"
    LIVE = "live"


class LLMProviderName(str, Enum):
    """BLUEPRINT.md S15: LLM provider abstraction selection."""
    FIXTURE = "fixture"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"


class Settings(BaseSettings):
    """
    Central application settings.

    Every field maps to an environment variable defined in
    BLUEPRINT.md S23 .env.example specification.  Defaults match
    the canonical values from that section.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # -- Execution mode -------------------------------------------
    # BLUEPRINT.md S2: EXECUTION_MODE=demo | live
    EXECUTION_MODE: ExecutionMode = ExecutionMode.DEMO

    # BLUEPRINT.md S15: LLM_PROVIDER=fixture | gemini | anthropic
    LLM_PROVIDER: LLMProviderName = LLMProviderName.FIXTURE

    # -- Database -------------------------------------------------
    # BLUEPRINT.md S23: PostgreSQL 15 + pgvector async connection
    POSTGRES_URL: SecretStr = SecretStr(
        "postgresql+asyncpg://app_user:app_password@postgres:5432/agent_db"
    )

    # BLUEPRINT.md S23: Redis 7 broker + Pub/Sub
    REDIS_URL: str = "redis://redis:6379/0"

    # -- Google Gemini LLM Settings -------------------------------
    GEMINI_API_KEY: SecretStr = SecretStr(
        "gemini-placeholder-key-do-not-commit"
    )
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_MODELS: list[str] = Field(
        default_factory=lambda: [
            "gemini-3.5-flash",
            "gemini-flash-lite-latest",
            "gemini-flash-latest",
        ]
    )

    # -- External API keys & Model (legacy / alternate) -----------
    # BLUEPRINT.md S17, S23: never stored in plaintext in DB/logs
    ANTHROPIC_API_KEY: SecretStr = SecretStr(
        "sk-ant-placeholder-key-do-not-commit"
    )
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    TAVILY_API_KEY: SecretStr = SecretStr(
        "tvly-placeholder-key-do-not-commit"
    )

    # -- Tool constraints -----------------------------------------
    # BLUEPRINT.md S12, S17: file reader confined to this root
    FILE_READER_ROOT: str = "/app/sandbox_data"

    # -- Recipe retrieval & dedup thresholds ----------------------
    # BLUEPRINT.md S10, S11: cosine similarity thresholds
    RECIPE_SIMILARITY_THRESHOLD: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to retrieve a trusted recipe.",
    )
    RECIPE_DUPLICATE_THRESHOLD: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
        description="Similarity above which a new recipe is considered duplicate.",
    )

    # -- Security -------------------------------------------------
    # BLUEPRINT.md S17, S23: salt for SHA-256 API key hashing
    API_KEY_SALT: SecretStr = SecretStr(
        "change_this_to_a_secure_random_salt_min_32_chars"
    )

    # -- WebSocket streaming & replay -----------------------------
    # BLUEPRINT.md S14: subscribe-then-replay protocol constants
    REPLAY_BATCH_SIZE: int = Field(
        default=500,
        gt=0,
        description="Max events per PostgreSQL replay query batch.",
    )
    REPLAY_BUFFER_SIZE: int = Field(
        default=100,
        gt=0,
        description="Bounded asyncio.Queue capacity per WS connection.",
    )

    # -- Worker ---------------------------------------------------
    # BLUEPRINT.md S23: stale run recovery timeout in seconds
    RUN_STALE_TIMEOUT: int = Field(
        default=1800,
        gt=0,
        description="Seconds before an in-progress run is marked failed.",
    )

    # -- Agent graph limits (not in .env; hardcoded per S2, S8) ---
    # BLUEPRINT.md S2, S8: conditional LangGraph iteration cap
    MAX_ITERATIONS: int = 3

    # -- Evaluation thresholds (not in .env; hardcoded per S11) ---
    # BLUEPRINT.md S11: two-tier scoring thresholds
    TASK_SUCCESS_THRESHOLD: float = 6.0
    RECIPE_PROMOTION_THRESHOLD: float = 8.5

    # -- Rate limiting (not in .env; hardcoded per S17) -----------
    # BLUEPRINT.md S17: POST /tasks rate limit
    RATE_LIMIT_TASKS_PER_MINUTE: int = 10


# Module-level singleton -- import as `from backend.core.config import settings`
settings = Settings()
