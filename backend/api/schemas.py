"""
API Request, Response, and Standard Error Schemas.

Source of truth: BLUEPRINT.md §1, §14, §15, §17, §18.

Design rules:
- All error responses conform to BLUEPRINT.md §15:
  {"error": {"code": str, "message": str, "request_id": str}}
- Status vocabulary is strictly: 'pending', 'running', 'succeeded', 'failed'.
  The value 'completed' is strictly forbidden.
- Client never supplies user_id; server derives ownership from the API key.
- Pydantic models validate input bounds, pagination ranges, and types.
- Telemetry/Judge security: raw judge_reasoning, CoT, and secrets are NEVER
  exposed in API response models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator


# -- Standard Error Codes (BLUEPRINT.md §15) ---------------------


class ErrorCode(str, Enum):
    """
    Standard machine-readable error codes per BLUEPRINT.md §15.
    """
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_NOT_COMPLETE = "TASK_NOT_COMPLETE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    CONFLICT = "CONFLICT"


# -- Standard Error Models & Exception (BLUEPRINT.md §15) --------


class ErrorDetail(BaseModel):
    """
    Standard inner error payload.
    Source: BLUEPRINT.md §15 Standard API Error Response Format.
    """
    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., description="Standard machine-readable error code.")
    message: str = Field(..., description="Human-readable explanation of the error.")
    request_id: str = Field(..., description="Unique request tracing identifier.")


class ErrorResponse(BaseModel):
    """
    Standard API error envelope returned on all 4xx/5xx responses.
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(extra="ignore")

    error: ErrorDetail


class APIException(HTTPException):
    """
    Custom exception class conforming to the BLUEPRINT.md §15 standard error contract.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        request_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.code = code
        self.message_detail = message
        self.request_id = request_id or f"req_{uuid.uuid4().hex[:16]}"
        detail = {
            "error": {
                "code": self.code,
                "message": self.message_detail,
                "request_id": self.request_id,
            }
        }
        super().__init__(status_code=status_code, detail=detail, headers=headers)

    @classmethod
    def unauthorized(
        cls,
        message: str = "Missing or invalid API key.",
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=401,
            code=ErrorCode.UNAUTHORIZED.value,
            message=message,
            request_id=request_id,
        )

    @classmethod
    def forbidden(
        cls,
        message: str = "The authenticated user does not own this resource.",
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=403,
            code=ErrorCode.FORBIDDEN.value,
            message=message,
            request_id=request_id,
        )

    @classmethod
    def not_found(
        cls,
        message: str = "The requested resource was not found.",
        code: str = ErrorCode.NOT_FOUND.value,
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=404,
            code=code,
            message=message,
            request_id=request_id,
        )

    @classmethod
    def task_not_found(
        cls,
        message: str = "The requested task was not found or is not owned by the caller.",
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=404,
            code=ErrorCode.TASK_NOT_FOUND.value,
            message=message,
            request_id=request_id,
        )

    @classmethod
    def task_not_complete(
        cls,
        message: str = "The task has not reached a terminal state.",
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=409,
            code=ErrorCode.TASK_NOT_COMPLETE.value,
            message=message,
            request_id=request_id,
        )

    @classmethod
    def rate_limited(
        cls,
        message: str = "Rate limit exceeded: maximum 10 requests per minute on POST /tasks.",
        retry_after: int = 60,
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=429,
            code=ErrorCode.RATE_LIMIT_EXCEEDED.value,
            message=message,
            request_id=request_id,
            headers={"Retry-After": str(retry_after)},
        )

    @classmethod
    def internal_error(
        cls,
        message: str = "An unexpected server error occurred.",
        request_id: Optional[str] = None,
    ) -> APIException:
        return cls(
            status_code=500,
            code=ErrorCode.INTERNAL_SERVER_ERROR.value,
            message=message,
            request_id=request_id,
        )


# -- User Context Schema (Internal Auth Dependency) ---------------


class UserContext(BaseModel):
    """
    Authenticated user context derived server-side from the API key.
    Source: BLUEPRINT.md §17.
    """
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    display_name: str
    api_key_hash: str


# -- Task Schemas (BLUEPRINT.md §15) ------------------------------


class TaskCreateRequest(BaseModel):
    """
    POST /tasks request body.
    Source: BLUEPRINT.md §15.
    Client never supplies user_id; server derives it from API key.
    """
    model_config = ConfigDict(extra="ignore")

    goal: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Goal description for the agent run.",
    )

    @field_validator("goal")
    @classmethod
    def validate_goal_not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Task goal cannot be empty or whitespace only.")
        return stripped


class TaskCreateResponse(BaseModel):
    """
    POST /tasks response (HTTP 201 Created).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID = Field(..., description="Unique task identifier.")
    run_id: uuid.UUID = Field(..., description="Unique run identifier.")
    status: str = Field(default="pending", description="Initial lifecycle status.")


class TaskSummaryItem(BaseModel):
    """
    Single task summary item in GET /tasks.
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    goal: str
    status: str
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """
    GET /tasks paginated response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    items: List[TaskSummaryItem] = Field(default_factory=list)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    total: int = Field(default=0, ge=0)


class RunSummaryItem(BaseModel):
    """
    Run summary inside GET /tasks/{id}.
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    run_id: uuid.UUID
    status: str
    termination_reason: Optional[str] = None
    iteration_count: int = Field(default=0, ge=0)
    created_at: datetime


class TaskDetailResponse(BaseModel):
    """
    GET /tasks/{id} response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    goal: str
    status: str
    created_at: datetime
    updated_at: datetime
    runs: List[RunSummaryItem] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    """
    Safe evaluation metrics in GET /tasks/{id}/result.
    Source: BLUEPRINT.md §15.
    NOTE: raw judge_reasoning is strictly excluded for security/telemetry privacy (§17).
    """
    model_config = ConfigDict(from_attributes=True)

    task_success: bool = Field(..., description="Whether the task met the success threshold.")
    deterministic_pass: bool = Field(..., description="Whether deterministic validation passed.")
    tool_success: bool = Field(..., description="Whether tool executions succeeded.")
    judge_score: float = Field(..., ge=0.0, le=10.0, description="Judge score from 0.0 to 10.0.")
    iteration_count: int = Field(..., ge=1, description="Iteration at which evaluation ran.")
    tool_call_count: int = Field(default=0, ge=0, description="Tool invocations in this iteration.")


class TaskResultResponse(BaseModel):
    """
    GET /tasks/{id}/result response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    Only returned when task has reached terminal state ('succeeded' or 'failed').
    """
    model_config = ConfigDict(from_attributes=True)

    task_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    final_response: Optional[str] = None
    evaluation: Optional[EvaluationSummary] = None


# -- Memory / Recipe Schemas (BLUEPRINT.md §15) --------------------


class RecipeItem(BaseModel):
    """
    Single trusted recipe item in GET /memory/recipes.
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    recipe_id: uuid.UUID
    task_type: str
    problem_pattern: str
    recommended_strategy: str
    usage_count: int = Field(default=0, ge=0)
    success_after_reuse: int = Field(default=0, ge=0)
    created_at: datetime


class RecipeListResponse(BaseModel):
    """
    GET /memory/recipes paginated response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    items: List[RecipeItem] = Field(default_factory=list)
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    total: int = Field(default=0, ge=0)


# -- Feedback Schemas (BLUEPRINT.md §15) ---------------------------


class FeedbackCreateRequest(BaseModel):
    """
    POST /tasks/{id}/feedback request body.
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(extra="ignore")

    rating: int = Field(..., ge=1, le=5, description="User rating from 1 to 5.")
    comment: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional user feedback commentary.",
    )


class FeedbackCreateResponse(BaseModel):
    """
    POST /tasks/{id}/feedback response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    feedback_id: uuid.UUID
    status: str = Field(default="recorded")


# -- Metrics Schemas (BLUEPRINT.md §15) ----------------------------


class MetricsResponse(BaseModel):
    """
    GET /metrics response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    Computed via aggregate SQL queries in PostgreSQL.
    """
    model_config = ConfigDict(from_attributes=True)

    total_tasks: int = Field(default=0, ge=0, description="Total tasks created by user.")
    successful_tasks: int = Field(default=0, ge=0, description="Tasks with status 'succeeded'.")
    failed_tasks: int = Field(default=0, ge=0, description="Tasks with status 'failed'.")
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="successful_tasks / total_tasks.")
    average_iterations: float = Field(default=0.0, ge=0.0, description="Average iterations across completed runs.")
    average_tool_calls: float = Field(default=0.0, ge=0.0, description="Average tool calls per run.")
    recipes_promoted: int = Field(default=0, ge=0, description="Count of trusted recipes owned by user.")
    recipe_retrieval_count: int = Field(default=0, ge=0, description="Runs where at least 1 recipe was retrieved.")
    successful_reuses: int = Field(default=0, ge=0, description="Retrieved-recipe runs that succeeded.")
    average_judge_score: float = Field(default=0.0, ge=0.0, le=10.0, description="Average judge score.")
    improvement_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="Proportion of improved reused runs.")


# -- Health Check Schema (BLUEPRINT.md §15) ------------------------


class HealthCheckResponse(BaseModel):
    """
    GET /health response (HTTP 200 OK).
    Source: BLUEPRINT.md §15.
    """
    model_config = ConfigDict(from_attributes=True)

    status: str = Field(default="ok")
    database: str = Field(default="connected")
    redis: str = Field(default="connected")


__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "APIException",
    "UserContext",
    "TaskCreateRequest",
    "TaskCreateResponse",
    "TaskSummaryItem",
    "TaskListResponse",
    "RunSummaryItem",
    "TaskDetailResponse",
    "EvaluationSummary",
    "TaskResultResponse",
    "RecipeItem",
    "RecipeListResponse",
    "FeedbackCreateRequest",
    "FeedbackCreateResponse",
    "MetricsResponse",
    "HealthCheckResponse",
]
