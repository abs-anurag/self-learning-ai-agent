"""
Common FastAPI Dependencies.

Source of truth: BLUEPRINT.md §14, §15, §17.

Provides:
- Database session injection (`get_db_session`).
- Authenticated user dependency (`get_current_user`).
- Task creation rate limiting (`rate_limit_task_creation`).
- Pagination parameters (`PaginationParams`).
- Request tracing identifier (`get_request_id`).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.security.auth import get_current_user
from backend.api.security.rate_limit import rate_limit_task_creation
from backend.db.models import User
from backend.db.session import get_db_session

# Alias for convenience in route handlers
get_db = get_db_session


class PaginationParams:
    """
    Common query parameters for paginated endpoints.
    Source: BLUEPRINT.md §15 (page default 1, page_size default 20, max 100).
    """

    def __init__(
        self,
        page: int = Query(
            default=1,
            ge=1,
            description="Page number (1-indexed, minimum 1).",
        ),
        page_size: int = Query(
            default=20,
            ge=1,
            le=100,
            description="Items per page (minimum 1, maximum 100).",
        ),
    ) -> None:
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        """Calculate SQL OFFSET."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """Calculate SQL LIMIT."""
        return self.page_size


async def get_request_id(request: Request) -> str:
    """
    Extract or generate a request correlation ID.
    Source: BLUEPRINT.md §15 (req_01HXYZ...).
    """
    req_id = request.headers.get("X-Request-ID")
    if req_id and req_id.strip():
        return req_id.strip()
    return f"req_{uuid.uuid4().hex[:16]}"


__all__ = [
    "get_db",
    "get_db_session",
    "get_current_user",
    "rate_limit_task_creation",
    "PaginationParams",
    "get_request_id",
    "User",
    "AsyncSession",
]
