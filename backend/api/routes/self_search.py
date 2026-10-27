"""
Self Search API router.

Endpoint:
- POST /self-search/ask: Answers question grounded in user-provided document.
Protected by get_current_user (X-API-Key).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.api.dependencies import get_current_user
from backend.api.schemas import APIException
from backend.api.schemas_self_search import (
    SelfSearchRequest,
    SelfSearchResponse,
)
from backend.core.logging import get_logger
from backend.db.models import User
from backend.self_search.service import SelfSearchService

logger = get_logger(__name__)

router = APIRouter(prefix="/self-search", tags=["Self Search"])


@router.post(
    "/ask",
    response_model=SelfSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Answer a question grounded in user-supplied document",
)
async def ask_self_search(
    payload: SelfSearchRequest,
    current_user: User = Depends(get_current_user),
) -> SelfSearchResponse:
    """
    POST /self-search/ask

    Executes document-grounded question answering:
    - Enforces API key authentication via X-API-Key.
    - Validates document and question lengths and rejects whitespace-only inputs.
    - Logs metadata only (never logs document or question text).
    - Verifies returned source quotations against document text.
    - Returns structured answer and citation metadata.
    """
    doc_len = len(payload.document)
    q_len = len(payload.question)

    logger.info(
        "Self Search query received for user_id=%s (doc_len=%d, q_len=%d)",
        str(current_user.id),
        doc_len,
        q_len,
    )

    service = SelfSearchService()

    try:
        response = await service.answer(
            document=payload.document,
            question=payload.question,
        )
        return response
    except RuntimeError as exc:
        logger.error(
            "Self Search provider execution error for user_id=%s: %s",
            str(current_user.id),
            exc,
        )
        raise APIException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="LLM_PROVIDER_ERROR",
            message=f"LLM provider failed to generate a response: {exc}",
        )
    except Exception as exc:
        logger.error(
            "Self Search unexpected failure for user_id=%s: %s",
            str(current_user.id),
            type(exc).__name__,
        )
        raise APIException.internal_error(
            message="An unexpected server error occurred during Self Search."
        )
