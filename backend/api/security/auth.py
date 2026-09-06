"""
API Key Authentication and User Identity Derivation.

Source of truth: BLUEPRINT.md §1, §15, §17, §18, §23.

Design rules:
- Header `X-API-Key` on all authenticated HTTP requests.
- Plaintext API keys are never stored in the database, committed, or logged.
- The database stores only `api_key_hash` = SHA-256(plain_token + API_KEY_SALT).
- Constant-time comparison (`hmac.compare_digest`) prevents timing side-channels.
- Authentication dependency derives the authenticated `User` server-side.
  Client-supplied `user_id` values are strictly ignored.
- Failed authentication raises HTTP 401 with standard API error envelope.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Depends, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.schemas import APIException, ErrorCode
from backend.core.config import settings
from backend.core.logging import get_logger
from backend.db.models import User
from backend.db.session import get_db_session

logger = get_logger(__name__)

# Standard OpenAPI / HTTP header scheme for X-API-Key
api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Hex/token API key passed via X-API-Key header",
)


def hash_api_key(api_key: str, salt: Optional[str] = None) -> str:
    """
    Compute SHA-256 hash of API key with the configured salt.
    Source: BLUEPRINT.md §17, §23.

    Formula: sha256(token + API_KEY_SALT)
    """
    salt_value = (
        salt
        if salt is not None
        else settings.API_KEY_SALT.get_secret_value()
    )
    combined = (api_key + salt_value).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


def verify_api_key(
    plain_key: str,
    hashed_key: str,
    salt: Optional[str] = None,
) -> bool:
    """
    Verify a plaintext API key against a stored hash using constant-time comparison.
    """
    computed_hash = hash_api_key(plain_key, salt=salt)
    return hmac.compare_digest(computed_hash, hashed_key)


def generate_api_key() -> str:
    """
    Generate a cryptographically secure 32-byte URL-safe API key token.
    Source: BLUEPRINT.md §17, §23.
    """
    return secrets.token_urlsafe(32)


async def authenticate_api_key(
    api_key: Optional[str],
    session: AsyncSession,
) -> Optional[User]:
    """
    Authenticate an API key against the database.
    Returns the User model if valid, or None if missing/invalid.
    Source: BLUEPRINT.md §15, §17.
    """
    if not api_key or not api_key.strip():
        return None

    hashed = hash_api_key(api_key.strip())
    stmt = select(User).where(User.api_key_hash == hashed)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_current_user(
    api_key: Optional[str] = Security(api_key_header),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """
    FastAPI security dependency resolving the authenticated User from the X-API-Key header.
    Raises APIException(401, UNAUTHORIZED) if the header is missing or the key is invalid.

    Source: BLUEPRINT.md §15, §17.
    """
    if not api_key or not api_key.strip():
        logger.warning("Authentication failed: missing X-API-Key header.")
        raise APIException.unauthorized(
            message="Missing or invalid API key. Please provide a valid key in the 'X-API-Key' header."
        )

    user = await authenticate_api_key(api_key, session)
    if user is None:
        logger.warning("Authentication failed: invalid API key.")
        raise APIException.unauthorized(
            message="Missing or invalid API key. Please provide a valid key in the 'X-API-Key' header."
        )

    return user


__all__ = [
    "api_key_header",
    "hash_api_key",
    "verify_api_key",
    "generate_api_key",
    "authenticate_api_key",
    "get_current_user",
]
