"""
FastAPI Application Entry Point.

Source of truth: BLUEPRINT.md §1, §14, §15, §17.

Responsibilities:
- Application initialization with metadata and OpenAPI documentation.
- CORS configuration allowing frontend origins.
- Router registration for all blueprint endpoints:
  - GET /health
  - POST /tasks, GET /tasks, GET /tasks/{id}, GET /tasks/{id}/result
  - GET /tasks/{id}/events (HTTP replay fallback)
  - GET /memory/recipes
  - POST /tasks/{id}/feedback
  - GET /metrics
- Global exception handlers strictly enforcing the standard error format:
  {"error": {"code": str, "message": str, "request_id": str}}
- Security sanitization: stack traces, SQL errors, secrets, and judge reasoning
  are NEVER returned to clients.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.routes.events import router as events_router
from backend.api.routes.feedback import router as feedback_router
from backend.api.routes.health import router as health_router
from backend.api.routes.memory import router as memory_router
from backend.api.routes.metrics import router as metrics_router
from backend.api.routes.tasks import router as tasks_router
from backend.api.schemas import APIException, ErrorCode
from backend.api.ws.manager import ws_manager
from backend.core.logging import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """Application factory for the FastAPI backend."""
    app = FastAPI(
        title="Self-Learning AI Agent API",
        version="1.0.0",
        description="Experience-based self-learning agent API with atomic sequence streaming.",
    )

    # -- CORS Middleware (BLUEPRINT.md §15, §16, §23) ------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Permits localhost Vite dev server and containerized Nginx
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -- Helper to resolve request_id -----------------------------
    def get_req_id(request: Request) -> str:
        req_id = request.headers.get("X-Request-ID")
        if req_id and req_id.strip():
            return req_id.strip()
        return f"req_{uuid.uuid4().hex[:16]}"

    # -- Global Exception Handlers (BLUEPRINT.md §15) -------------

    @app.exception_handler(APIException)
    async def handle_api_exception(request: Request, exc: APIException) -> JSONResponse:
        """Handles custom APIException, ensuring blueprint error JSON format."""
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """
        Handles Pydantic validation errors (HTTP 422).
        Formats errors cleanly without leaking internal structures.
        """
        req_id = get_req_id(request)
        error_msgs = []
        for err in exc.errors():
            loc = ".".join(str(l) for l in err.get("loc", []))
            msg = err.get("msg", "Validation error")
            error_msgs.append(f"{loc}: {msg}" if loc else msg)

        formatted_message = (
            "Request validation failed: " + "; ".join(error_msgs)
            if error_msgs
            else "Request validation failed."
        )

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": formatted_message,
                    "request_id": req_id,
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        """
        Handles generic FastAPI/Starlette HTTPExceptions, mapping them
        to the standard error format.
        """
        req_id = get_req_id(request)

        # If detail is already formatted with an "error" dictionary
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            content = exc.detail
        else:
            # Map common status codes to standard error codes
            code_map = {
                401: ErrorCode.UNAUTHORIZED.value,
                403: ErrorCode.FORBIDDEN.value,
                404: ErrorCode.NOT_FOUND.value,
                409: ErrorCode.CONFLICT.value,
                429: ErrorCode.RATE_LIMIT_EXCEEDED.value,
            }
            code = code_map.get(exc.status_code, "HTTP_ERROR")
            content = {
                "error": {
                    "code": code,
                    "message": str(exc.detail),
                    "request_id": req_id,
                }
            }

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """
        Catches unhandled server errors (HTTP 500).
        CRITICAL: Never leaks stack traces, SQL errors, credentials,
        or internal telemetry to the client.
        """
        req_id = get_req_id(request)
        logger.error(
            "Unhandled server exception on %s %s [request_id=%s]: %s",
            request.method,
            request.url.path,
            req_id,
            exc,
            exc_info=True,
        )

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_SERVER_ERROR.value,
                    "message": "An unexpected server error occurred.",
                    "request_id": req_id,
                }
            },
        )

    # -- Router Inclusions ----------------------------------------
    app.include_router(health_router)
    app.include_router(tasks_router)
    app.include_router(events_router)
    app.include_router(memory_router)
    app.include_router(feedback_router)
    app.include_router(metrics_router)

    # Register WebSocket endpoint
    app.add_api_websocket_route("/ws/tasks/{task_id}", ws_manager.handle)

    return app


# Default module instance for uvicorn (uvicorn backend.api.main:app)
app = create_app()
