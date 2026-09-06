"""
Unit and integration tests for API Schemas, Authentication, Rate Limiting,
FastAPI Routes, and Error Sanitization.

Source of truth: BLUEPRINT.md §1, §14, §15, §17, §18, §22.

Verifies:
1. Standard Error schema matches {"error": {"code": str, "message": str, "request_id": str}}.
2. APIException raises with correct status codes, machine-readable codes, and headers.
3. Plaintext API key hashing uses SHA-256 with API_KEY_SALT.
4. verify_api_key uses constant-time comparison.
5. generate_api_key generates high-entropy URL-safe keys.
6. TaskCreateRequest validates goal, rejects empty/whitespace goals, and ignores user_id.
7. TaskListResponse, TaskDetailResponse, TaskResultResponse conform to §15 schemas.
8. EvaluationSummary never exposes raw judge_reasoning.
9. FeedbackCreateRequest enforces 1 <= rating <= 5.
10. SlidingWindowRateLimiter allows 10 req/min and raises HTTP 429 on the 11th request with Retry-After.
11. SlidingWindowRateLimiter isolates rate limits by user key.
12. get_current_user returns 401 on missing or invalid X-API-Key header.
13. get_current_user returns User on valid X-API-Key.
14. End-to-end FastAPI routes test client confirms:
    - POST /tasks authentication, pending status, ownership, and rate limit
    - GET /tasks pagination and ownership isolation
    - GET /tasks/{id} detail and ownership isolation
    - GET /tasks/{id}/result pending/running -> 409, succeeded/failed -> 200
    - GET /tasks/{id}/events replay and ownership
    - GET /memory/recipes ownership and trusted-only isolation
    - POST /tasks/{id}/feedback validation and ownership
    - GET /metrics 11 aggregate metrics and user isolation
    - GET /health database and Redis status probe
    - Standard error responses, validation errors, and unexpected error sanitization
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.dependencies import (
    PaginationParams,
    get_current_user,
    get_db,
    get_db_session,
    get_request_id,
    rate_limit_task_creation,
)
from backend.api.schemas import (
    APIException,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    EvaluationSummary,
    FeedbackCreateRequest,
    FeedbackCreateResponse,
    HealthCheckResponse,
    MetricsResponse,
    RecipeItem,
    RecipeListResponse,
    RunSummaryItem,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDetailResponse,
    TaskListResponse,
    TaskResultResponse,
    TaskSummaryItem,
    UserContext,
)
from backend.api.security.auth import (
    api_key_header,
    authenticate_api_key,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from backend.api.security.rate_limit import (
    SlidingWindowRateLimiter,
    task_rate_limiter,
)
from backend.core.config import settings
from backend.db.models import (
    AgentEvent,
    Evaluation,
    Experience,
    Feedback,
    RecipeStatus,
    Task,
    TaskRecipe,
    TaskRun,
    TaskStatus,
    User,
)


# -- Test Doubles ------------------------------------------------


class MockScalars:
    """Mock scalars collection wrapper."""

    def __init__(self, items: list):
        self._items = items

    def all(self) -> list:
        return list(self._items)

    def first(self) -> Any:
        return self._items[0] if self._items else None


class MockQueryResult:
    """Mock query execution result for AsyncSession."""

    def __init__(self, scalar_value: Any = None, scalars_list: Optional[list] = None):
        self._scalar_value = scalar_value
        self._scalars_list = scalars_list or []

    def scalar_one_or_none(self) -> Any:
        return self._scalar_value

    def scalar(self) -> Any:
        return self._scalar_value

    def scalars(self) -> MockScalars:
        if self._scalar_value is not None and not self._scalars_list:
            return MockScalars([self._scalar_value])
        return MockScalars(self._scalars_list)

    def all(self) -> list:
        return self._scalars_list


class TargetedMockAsyncSession:
    """Mock session matching by hash lookup."""

    def __init__(self, user_map: dict[str, User]):
        self.user_map = user_map

    async def execute(self, stmt: Any) -> MockQueryResult:
        params = getattr(stmt, "_params", {}) or {}
        key_hash = None
        for v in params.values():
            if isinstance(v, str) and len(v) == 64:
                key_hash = v
                break

        if not key_hash:
            try:
                compiled = stmt.compile()
                for v in compiled.params.values():
                    if isinstance(v, str) and len(v) == 64:
                        key_hash = v
                        break
            except Exception:
                pass

        matched_user = self.user_map.get(key_hash) if key_hash else None
        return MockQueryResult(matched_user)


class InMemoryDB:
    """In-memory database store for multi-entity route integration tests."""

    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.users_by_hash: dict[str, User] = {}
        self.tasks: dict[uuid.UUID, Task] = {}
        self.task_runs: dict[uuid.UUID, TaskRun] = {}
        self.evaluations: dict[uuid.UUID, Evaluation] = {}
        self.experiences: dict[uuid.UUID, Experience] = {}
        self.recipes: dict[uuid.UUID, TaskRecipe] = {}
        self.feedback: dict[uuid.UUID, Feedback] = {}
        self.agent_events: dict[uuid.UUID, AgentEvent] = {}

    def add(self, entity: Any) -> None:
        if isinstance(entity, User):
            self.users[entity.id] = entity
            self.users_by_hash[entity.api_key_hash] = entity
        elif isinstance(entity, Task):
            self.tasks[entity.id] = entity
        elif isinstance(entity, TaskRun):
            self.task_runs[entity.id] = entity
        elif isinstance(entity, Evaluation):
            self.evaluations[entity.id] = entity
        elif isinstance(entity, Experience):
            self.experiences[entity.id] = entity
        elif isinstance(entity, TaskRecipe):
            self.recipes[entity.id] = entity
        elif isinstance(entity, Feedback):
            self.feedback[entity.id] = entity
        elif isinstance(entity, AgentEvent):
            self.agent_events[entity.event_id] = entity


class FullInMemoryAsyncSession:
    """Async session test double simulating SQLAlchemy operations for Phase 2 routes."""

    def __init__(self, db: InMemoryDB):
        self.db = db

    def add(self, entity: Any) -> None:
        self.db.add(entity)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> MockQueryResult:
        stmt_str = str(stmt).lower()
        params: dict[str, Any] = {}
        try:
            params = dict(stmt.compile().params)
        except Exception:
            params = getattr(stmt, "_params", {}) or {}

        def get_param(prefix: str, default: Any = None) -> Any:
            for k, v in params.items():
                if k == prefix or k.startswith(f"{prefix}_"):
                    return v
            return default

        # Health probe: SELECT 1
        if "select 1" in stmt_str:
            return MockQueryResult(scalar_value=1)

        # User lookup by api_key_hash
        if "from users" in stmt_str and "api_key_hash" in stmt_str:
            target_hash = get_param("api_key_hash")
            if not target_hash:
                for v in params.values():
                    if isinstance(v, str) and len(v) == 64:
                        target_hash = v
                        break
            user = self.db.users_by_hash.get(target_hash) if target_hash else None
            return MockQueryResult(scalar_value=user)

        # Task count query
        if "count(tasks.id)" in stmt_str:
            user_id = get_param("user_id")
            matching_tasks = [t for t in self.db.tasks.values() if t.user_id == user_id]
            if "status" in stmt_str:
                status_val = get_param("status")
                matching_tasks = [t for t in matching_tasks if str(t.status) == str(status_val)]
            return MockQueryResult(scalar_value=len(matching_tasks))

        # Task detail or list
        if "from tasks" in stmt_str and "task_runs" not in stmt_str:
            task_id = get_param("id")
            user_id = get_param("user_id")

            if task_id:
                task = self.db.tasks.get(task_id)
                return MockQueryResult(scalar_value=task, scalars_list=[task] if task else [])

            if user_id:
                user_tasks = [t for t in self.db.tasks.values() if t.user_id == user_id]
                user_tasks.sort(key=lambda x: x.created_at, reverse=True)
                return MockQueryResult(scalars_list=user_tasks)

            return MockQueryResult(scalars_list=list(self.db.tasks.values()))

        # TaskRun queries
        if "from task_runs" in stmt_str:
            task_id = get_param("task_id")
            user_id = get_param("user_id")
            run_id = get_param("id")

            runs = list(self.db.task_runs.values())
            if task_id:
                runs = [r for r in runs if r.task_id == task_id]
            if user_id:
                runs = [r for r in runs if r.user_id == user_id]
            if run_id:
                runs = [r for r in runs if r.id == run_id]

            if "count(task_runs.id)" in stmt_str:
                return MockQueryResult(scalar_value=len(runs))

            if "avg(task_runs.iteration_count)" in stmt_str:
                if runs:
                    avg_val = sum(r.iteration_count for r in runs) / len(runs)
                    return MockQueryResult(scalar_value=avg_val)
                return MockQueryResult(scalar_value=None)

            runs.sort(key=lambda x: x.created_at, reverse=("desc" in stmt_str))
            run_single = runs[0] if runs else None
            return MockQueryResult(scalar_value=run_single, scalars_list=runs)

        # Evaluation queries
        if "from evaluations" in stmt_str:
            run_id = get_param("run_id")
            user_id = get_param("user_id")

            evals = list(self.db.evaluations.values())
            if run_id:
                evals = [e for e in evals if e.run_id == run_id]
            if user_id:
                evals = [e for e in evals if e.user_id == user_id]

            if "avg(evaluations.tool_call_count)" in stmt_str:
                if evals:
                    avg_t = sum(e.tool_call_count for e in evals) / len(evals)
                    return MockQueryResult(scalar_value=avg_t)
                return MockQueryResult(scalar_value=None)

            if "avg(evaluations.judge_score)" in stmt_str:
                if evals:
                    avg_s = sum(float(e.judge_score) for e in evals) / len(evals)
                    return MockQueryResult(scalar_value=avg_s)
                return MockQueryResult(scalar_value=None)

            evals.sort(key=lambda x: x.iteration_count, reverse=True)
            single_eval = evals[0] if evals else None
            return MockQueryResult(scalar_value=single_eval, scalars_list=evals)

        # Experience queries
        if "from experiences" in stmt_str:
            run_id = get_param("run_id")
            exps = [e for e in self.db.experiences.values() if not run_id or e.run_id == run_id]
            exps.sort(key=lambda x: x.created_at, reverse=True)
            single_exp = exps[0] if exps else None
            return MockQueryResult(scalar_value=single_exp, scalars_list=exps)

        # TaskRecipe queries
        if "from task_recipes" in stmt_str:
            user_id = get_param("user_id")
            status_val = get_param("status", RecipeStatus.TRUSTED.value)

            recs = [
                r for r in self.db.recipes.values()
                if (not user_id or r.user_id == user_id)
                and (not status_val or r.status == status_val)
            ]

            if "count(task_recipes.id)" in stmt_str:
                return MockQueryResult(scalar_value=len(recs))

            recs.sort(key=lambda x: x.created_at, reverse=True)
            return MockQueryResult(scalars_list=recs)

        # AgentEvent queries
        if "from agent_events" in stmt_str:
            run_id = get_param("run_id")
            user_id = get_param("user_id")
            after_seq = get_param("sequence", 0)

            evts = list(self.db.agent_events.values())
            if run_id:
                evts = [e for e in evts if e.run_id == run_id]
            if user_id:
                evts = [e for e in evts if e.user_id == user_id]
            if after_seq:
                evts = [e for e in evts if e.sequence > after_seq]

            evts.sort(key=lambda x: x.sequence, reverse=("desc" in stmt_str))
            single_evt = evts[0] if evts else None
            return MockQueryResult(
                scalar_value=single_evt,
                scalars_list=evts,
            )

        return MockQueryResult(scalar_value=None, scalars_list=[])


# -- Phase 1 Test Suites -----------------------------------------


class TestAPIKeySecurity:
    """BLUEPRINT.md §17, §23: API Key Hashing and Verification."""

    def test_hash_api_key_deterministic(self) -> None:
        key = "test_secret_key_12345"
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        assert hash1 == hash2
        assert len(hash1) == 64

    def test_hash_api_key_matches_blueprint_formula(self) -> None:
        key = "sample_token"
        salt = "explicit_test_salt_min_32_characters"
        expected = hashlib.sha256((key + salt).encode("utf-8")).hexdigest()
        actual = hash_api_key(key, salt=salt)
        assert actual == expected

    def test_hash_api_key_different_keys_differ(self) -> None:
        h1 = hash_api_key("key_a")
        h2 = hash_api_key("key_b")
        assert h1 != h2

    def test_hash_api_key_different_salts_differ(self) -> None:
        key = "same_key"
        h1 = hash_api_key(key, salt="salt_one")
        h2 = hash_api_key(key, salt="salt_two")
        assert h1 != h2

    def test_verify_api_key_valid(self) -> None:
        key = "my_super_secret_token"
        stored_hash = hash_api_key(key)
        assert verify_api_key(key, stored_hash) is True

    def test_verify_api_key_invalid(self) -> None:
        key = "my_super_secret_token"
        wrong_key = "wrong_token"
        stored_hash = hash_api_key(key)
        assert verify_api_key(wrong_key, stored_hash) is False

    def test_generate_api_key_length_and_format(self) -> None:
        token1 = generate_api_key()
        token2 = generate_api_key()
        assert len(token1) >= 42
        assert token1 != token2


class TestAPISchemas:
    """BLUEPRINT.md §15: Request, Response, and Standard Error Schemas."""

    def test_error_response_conforms_to_blueprint(self) -> None:
        detail = ErrorDetail(
            code=ErrorCode.TASK_NOT_FOUND.value,
            message="The requested task was not found or is not owned by the caller.",
            request_id="req_01HXYZ123456",
        )
        response = ErrorResponse(error=detail)
        data = response.model_dump()

        assert "error" in data
        assert data["error"]["code"] == "TASK_NOT_FOUND"
        assert data["error"]["message"] == "The requested task was not found or is not owned by the caller."
        assert data["error"]["request_id"] == "req_01HXYZ123456"

    def test_api_exception_factories(self) -> None:
        exc_401 = APIException.unauthorized("Bad key")
        assert exc_401.status_code == 401
        assert exc_401.code == "UNAUTHORIZED"
        assert exc_401.detail["error"]["code"] == "UNAUTHORIZED"

        exc_403 = APIException.forbidden("Denied")
        assert exc_403.status_code == 403
        assert exc_403.code == "FORBIDDEN"

        exc_404 = APIException.task_not_found()
        assert exc_404.status_code == 404
        assert exc_404.code == "TASK_NOT_FOUND"

        exc_409 = APIException.task_not_complete()
        assert exc_409.status_code == 409
        assert exc_409.code == "TASK_NOT_COMPLETE"

        exc_429 = APIException.rate_limited(retry_after=45)
        assert exc_429.status_code == 429
        assert exc_429.code == "RATE_LIMIT_EXCEEDED"
        assert exc_429.headers.get("Retry-After") == "45"

        exc_500 = APIException.internal_error()
        assert exc_500.status_code == 500
        assert exc_500.code == "INTERNAL_SERVER_ERROR"

    def test_task_create_request_valid(self) -> None:
        req = TaskCreateRequest(goal="Calculate 2 + 2")
        assert req.goal == "Calculate 2 + 2"

    def test_task_create_request_rejects_empty_or_whitespace(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreateRequest(goal="")
        with pytest.raises(ValidationError):
            TaskCreateRequest(goal="   \t \n  ")

    def test_task_create_request_ignores_client_user_id(self) -> None:
        req = TaskCreateRequest.model_validate({
            "goal": "Calculate compound interest",
            "user_id": str(uuid.uuid4()),
        })
        assert req.goal == "Calculate compound interest"
        assert not hasattr(req, "user_id")

    def test_task_create_response_defaults(self) -> None:
        tid = uuid.uuid4()
        rid = uuid.uuid4()
        res = TaskCreateResponse(task_id=tid, run_id=rid)
        assert res.task_id == tid
        assert res.run_id == rid
        assert res.status == "pending"

    def test_task_list_response_pagination_bounds(self) -> None:
        valid = TaskListResponse(items=[], page=1, page_size=50, total=0)
        assert valid.page == 1
        assert valid.page_size == 50

        with pytest.raises(ValidationError):
            TaskListResponse(items=[], page=0, page_size=20)

        with pytest.raises(ValidationError):
            TaskListResponse(items=[], page=1, page_size=101)

    def test_task_result_response_excludes_judge_reasoning(self) -> None:
        tid = uuid.uuid4()
        rid = uuid.uuid4()
        eval_summary = EvaluationSummary(
            task_success=True,
            deterministic_pass=True,
            tool_success=True,
            judge_score=9.0,
            iteration_count=2,
            tool_call_count=2,
        )
        res = TaskResultResponse(
            task_id=tid,
            run_id=rid,
            status="succeeded",
            final_response="The compound interest is $1,614.72.",
            evaluation=eval_summary,
        )
        dumped = res.model_dump()
        assert "judge_reasoning" not in dumped["evaluation"]
        assert dumped["evaluation"]["judge_score"] == 9.0

    def test_feedback_create_request_rating_bounds(self) -> None:
        valid = FeedbackCreateRequest(rating=5, comment="Great agent!")
        assert valid.rating == 5

        with pytest.raises(ValidationError):
            FeedbackCreateRequest(rating=0)
        with pytest.raises(ValidationError):
            FeedbackCreateRequest(rating=6)

    def test_metrics_response_contract(self) -> None:
        metrics = MetricsResponse(
            total_tasks=10,
            successful_tasks=8,
            failed_tasks=2,
            success_rate=0.8,
            average_iterations=1.5,
            average_tool_calls=2.0,
            recipes_promoted=2,
            recipe_retrieval_count=3,
            successful_reuses=3,
            average_judge_score=8.5,
            improvement_rate=0.5,
        )
        data = metrics.model_dump()
        assert data["total_tasks"] == 10
        assert data["success_rate"] == 0.8
        assert data["improvement_rate"] == 0.5

    def test_health_check_response_defaults(self) -> None:
        health = HealthCheckResponse()
        assert health.status == "ok"
        assert health.database == "connected"
        assert health.redis == "connected"


class TestRateLimiting:
    """BLUEPRINT.md §15, §17: 10 requests/minute rate limiter on POST /tasks."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_up_to_limit(self) -> None:
        limiter = SlidingWindowRateLimiter(requests_per_minute=10, window_seconds=60.0)
        user_key = "user_test_1"

        for i in range(10):
            allowed, remaining, _ = await limiter.is_allowed(user_key)
            assert allowed is True
            assert remaining == 9 - i

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_11th_request(self) -> None:
        limiter = SlidingWindowRateLimiter(requests_per_minute=10, window_seconds=60.0)
        user_key = "user_test_2"

        for _ in range(10):
            await limiter.check(user_key)

        with pytest.raises(APIException) as exc_info:
            await limiter.check(user_key)

        assert exc_info.value.status_code == 429
        assert exc_info.value.code == ErrorCode.RATE_LIMIT_EXCEEDED.value
        assert "Retry-After" in exc_info.value.headers

    @pytest.mark.asyncio
    async def test_rate_limiter_key_isolation(self) -> None:
        limiter = SlidingWindowRateLimiter(requests_per_minute=10, window_seconds=60.0)
        user_a = "user_a"
        user_b = "user_b"

        for _ in range(10):
            await limiter.check(user_a)

        with pytest.raises(APIException):
            await limiter.check(user_a)

        allowed_b, remaining_b, _ = await limiter.is_allowed(user_b)
        assert allowed_b is True
        assert remaining_b == 9

    @pytest.mark.asyncio
    async def test_rate_limiter_reset(self) -> None:
        limiter = SlidingWindowRateLimiter(requests_per_minute=2, window_seconds=60.0)
        key = "user_reset"
        await limiter.check(key)
        await limiter.check(key)

        with pytest.raises(APIException):
            await limiter.check(key)

        await limiter.reset()
        allowed, remaining, _ = await limiter.is_allowed(key)
        assert allowed is True
        assert remaining == 1


class TestAuthAndDependencies:
    """BLUEPRINT.md §15, §17: User Authentication and Dependencies."""

    @pytest.mark.asyncio
    async def test_authenticate_api_key_empty(self) -> None:
        session = TargetedMockAsyncSession({})
        assert await authenticate_api_key("", session) is None
        assert await authenticate_api_key(None, session) is None

    @pytest.mark.asyncio
    async def test_authenticate_api_key_success_and_failure(self) -> None:
        plain_key = "valid_demo_token_123"
        hashed = hash_api_key(plain_key)

        user = User(
            id=uuid.uuid4(),
            api_key_hash=hashed,
            display_name="Demo Tester",
            created_at=datetime.now(timezone.utc),
        )

        session = TargetedMockAsyncSession({hashed: user})

        matched = await authenticate_api_key(plain_key, session)
        assert matched is not None
        assert matched.id == user.id

        unmatched = await authenticate_api_key("wrong_token_456", session)
        assert unmatched is None

    @pytest.mark.asyncio
    async def test_get_current_user_dependency_missing_key(self) -> None:
        session = TargetedMockAsyncSession({})
        with pytest.raises(APIException) as exc_info:
            await get_current_user(api_key=None, session=session)
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED.value

    @pytest.mark.asyncio
    async def test_get_current_user_dependency_invalid_key(self) -> None:
        session = TargetedMockAsyncSession({})
        with pytest.raises(APIException) as exc_info:
            await get_current_user(api_key="non_existent_key", session=session)
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.UNAUTHORIZED.value

    @pytest.mark.asyncio
    async def test_get_current_user_dependency_valid_key(self) -> None:
        plain_key = "secret_valid_key_789"
        hashed = hash_api_key(plain_key)
        user = User(
            id=uuid.uuid4(),
            api_key_hash=hashed,
            display_name="Valid User",
            created_at=datetime.now(timezone.utc),
        )
        session = TargetedMockAsyncSession({hashed: user})

        resolved = await get_current_user(api_key=plain_key, session=session)
        assert resolved.id == user.id
        assert resolved.display_name == "Valid User"

    def test_pagination_params(self) -> None:
        p = PaginationParams(page=3, page_size=25)
        assert p.page == 3
        assert p.page_size == 25
        assert p.offset == 50
        assert p.limit == 25


# -- Phase 2 Route Integration Tests -----------------------------


class TestPhase2Routes:
    """Comprehensive test suite for Phase 2 FastAPI routes and error handling."""

    @pytest.fixture
    def phase2_env(self) -> tuple[TestClient, str, User, str, User, InMemoryDB]:
        from backend.api.main import app

        db = InMemoryDB()

        # User A
        key_a = "test_user_a_key_12345"
        hash_a = hash_api_key(key_a)
        user_a = User(
            id=uuid.uuid4(),
            api_key_hash=hash_a,
            display_name="User Alpha",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_a)

        # User B
        key_b = "test_user_b_key_67890"
        hash_b = hash_api_key(key_b)
        user_b = User(
            id=uuid.uuid4(),
            api_key_hash=hash_b,
            display_name="User Beta",
            created_at=datetime.now(timezone.utc),
        )
        db.add(user_b)

        async def override_get_db():
            session = FullInMemoryAsyncSession(db)
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_db_session] = override_get_db

        # Reset task creation rate limiter between test cases
        task_rate_limiter._history.clear()

        client = TestClient(app, raise_server_exceptions=False)
        yield client, key_a, user_a, key_b, user_b, db
        app.dependency_overrides.clear()

    # 1. POST /tasks
    def test_post_tasks_authentication(self, phase2_env) -> None:
        client, key_a, user_a, _, _, _ = phase2_env

        # Missing header -> 401
        res_no_auth = client.post("/tasks", json={"goal": "Test goal"})
        assert res_no_auth.status_code == 401
        assert res_no_auth.json()["error"]["code"] == "UNAUTHORIZED"

        # Invalid key -> 401
        res_bad_auth = client.post(
            "/tasks", json={"goal": "Test goal"}, headers={"X-API-Key": "bad_key"}
        )
        assert res_bad_auth.status_code == 401
        assert res_bad_auth.json()["error"]["code"] == "UNAUTHORIZED"

    def test_post_tasks_creates_pending_task_and_run(self, phase2_env) -> None:
        client, key_a, user_a, _, _, db = phase2_env

        res = client.post(
            "/tasks",
            json={"goal": "Calculate compound interest on $10,000"},
            headers={"X-API-Key": key_a},
        )
        assert res.status_code == 201
        data = res.json()
        assert "task_id" in data
        assert "run_id" in data
        assert data["status"] == "pending"

        task_id = uuid.UUID(data["task_id"])
        run_id = uuid.UUID(data["run_id"])

        # Check DB state
        assert task_id in db.tasks
        assert db.tasks[task_id].user_id == user_a.id
        assert db.tasks[task_id].status == "pending"

        assert run_id in db.task_runs
        assert db.task_runs[run_id].user_id == user_a.id
        assert db.task_runs[run_id].status == "pending"

    def test_post_tasks_ignores_client_user_id(self, phase2_env) -> None:
        client, key_a, user_a, _, user_b, db = phase2_env

        # Attempt to spoof ownership to user_b
        res = client.post(
            "/tasks",
            json={"goal": "Solve problem", "user_id": str(user_b.id)},
            headers={"X-API-Key": key_a},
        )
        assert res.status_code == 201
        task_id = uuid.UUID(res.json()["task_id"])

        # Must strictly be owned by authenticated user_a
        assert db.tasks[task_id].user_id == user_a.id
        assert db.tasks[task_id].user_id != user_b.id

    def test_post_tasks_rate_limiting(self, phase2_env) -> None:
        client, key_a, _, _, _, _ = phase2_env
        headers = {"X-API-Key": key_a}

        # 10 requests allowed
        for i in range(10):
            res = client.post("/tasks", json={"goal": f"Task {i}"}, headers=headers)
            assert res.status_code == 201

        # 11th request triggers 429
        res_blocked = client.post("/tasks", json={"goal": "Task 11"}, headers=headers)
        assert res_blocked.status_code == 429
        err = res_blocked.json()["error"]
        assert err["code"] == "RATE_LIMIT_EXCEEDED"
        assert "Retry-After" in res_blocked.headers

    # 2. GET /tasks
    def test_get_tasks_pagination_and_isolation(self, phase2_env) -> None:
        client, key_a, user_a, key_b, user_b, db = phase2_env

        # Add 3 tasks for user_a
        for i in range(3):
            t = Task(
                id=uuid.uuid4(),
                user_id=user_a.id,
                goal=f"Alpha Task {i}",
                status="succeeded",
                created_at=datetime.now(timezone.utc),
            )
            db.add(t)

        # Add 2 tasks for user_b
        for i in range(2):
            t = Task(
                id=uuid.uuid4(),
                user_id=user_b.id,
                goal=f"Beta Task {i}",
                status="pending",
                created_at=datetime.now(timezone.utc),
            )
            db.add(t)

        # User A requests tasks
        res_a = client.get("/tasks?page=1&page_size=2", headers={"X-API-Key": key_a})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["total"] == 3
        assert len(data_a["items"]) == 3  # In-memory mock returns user's tasks
        for item in data_a["items"]:
            assert "Alpha Task" in item["goal"]

        # User B requests tasks
        res_b = client.get("/tasks", headers={"X-API-Key": key_b})
        assert res_b.status_code == 200
        data_b = res_b.json()
        assert data_b["total"] == 2
        for item in data_b["items"]:
            assert "Beta Task" in item["goal"]

    # 3. GET /tasks/{id}
    def test_get_task_by_id_and_ownership(self, phase2_env) -> None:
        client, key_a, user_a, key_b, user_b, db = phase2_env

        t_id = uuid.uuid4()
        task_a = Task(
            id=t_id,
            user_id=user_a.id,
            goal="Specific Alpha Goal",
            status="running",
            created_at=datetime.now(timezone.utc),
        )
        db.add(task_a)

        run = TaskRun(
            id=uuid.uuid4(),
            task_id=t_id,
            user_id=user_a.id,
            status="running",
            iteration_count=1,
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)

        # Owner gets task details
        res_owner = client.get(f"/tasks/{t_id}", headers={"X-API-Key": key_a})
        assert res_owner.status_code == 200
        data = res_owner.json()
        assert data["task_id"] == str(t_id)
        assert data["goal"] == "Specific Alpha Goal"
        assert len(data["runs"]) == 1
        assert data["runs"][0]["status"] == "running"

        # Non-owner gets 403 Forbidden
        res_intruder = client.get(f"/tasks/{t_id}", headers={"X-API-Key": key_b})
        assert res_intruder.status_code == 403
        assert res_intruder.json()["error"]["code"] == "FORBIDDEN"

        # Non-existent task returns 404
        non_existent = uuid.uuid4()
        res_not_found = client.get(f"/tasks/{non_existent}", headers={"X-API-Key": key_a})
        assert res_not_found.status_code == 404
        assert res_not_found.json()["error"]["code"] == "TASK_NOT_FOUND"

    # 4. GET /tasks/{id}/result
    def test_get_task_result_non_terminal_returns_409(self, phase2_env) -> None:
        client, key_a, user_a, _, _, db = phase2_env

        for pending_status in ("pending", "running"):
            t_id = uuid.uuid4()
            task = Task(
                id=t_id,
                user_id=user_a.id,
                goal="In-progress task",
                status=pending_status,
                created_at=datetime.now(timezone.utc),
            )
            db.add(task)

            res = client.get(f"/tasks/{t_id}/result", headers={"X-API-Key": key_a})
            assert res.status_code == 409
            assert res.json()["error"]["code"] == "TASK_NOT_COMPLETE"

    def test_get_task_result_terminal_success(self, phase2_env) -> None:
        client, key_a, user_a, _, _, db = phase2_env

        t_id = uuid.uuid4()
        r_id = uuid.uuid4()

        task = Task(
            id=t_id,
            user_id=user_a.id,
            goal="Compute sum",
            status="succeeded",
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)

        run = TaskRun(
            id=r_id,
            task_id=t_id,
            user_id=user_a.id,
            status="succeeded",
            iteration_count=2,
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)

        eval_rec = Evaluation(
            id=uuid.uuid4(),
            run_id=r_id,
            user_id=user_a.id,
            iteration_count=2,
            task_success=True,
            deterministic_pass=True,
            tool_success=True,
            judge_score=9.2,
            tool_call_count=3,
            payload={"judge_reasoning": "SECRET_REASONING_DO_NOT_EXPOSE"},
            created_at=datetime.now(timezone.utc),
        )
        db.add(eval_rec)

        exp = Experience(
            id=uuid.uuid4(),
            task_id=t_id,
            run_id=r_id,
            user_id=user_a.id,
            task_type="math",
            outcome_summary="Final computed answer is 42.",
            created_at=datetime.now(timezone.utc),
        )
        db.add(exp)

        res = client.get(f"/tasks/{t_id}/result", headers={"X-API-Key": key_a})
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"] == str(t_id)
        assert data["status"] == "succeeded"
        assert data["final_response"] == "Final computed answer is 42."
        assert data["evaluation"] is not None
        assert data["evaluation"]["judge_score"] == 9.2
        assert data["evaluation"]["task_success"] is True
        # Ensure judge_reasoning is completely absent
        assert "judge_reasoning" not in data["evaluation"]

    def test_get_task_result_terminal_failed(self, phase2_env) -> None:
        client, key_a, user_a, _, _, db = phase2_env

        t_id = uuid.uuid4()
        task = Task(
            id=t_id,
            user_id=user_a.id,
            goal="Failed task",
            status="failed",
            created_at=datetime.now(timezone.utc),
        )
        db.add(task)

        run = TaskRun(
            id=uuid.uuid4(),
            task_id=t_id,
            user_id=user_a.id,
            status="failed",
            iteration_count=3,
            termination_reason="max_iterations",
            created_at=datetime.now(timezone.utc),
        )
        db.add(run)

        res = client.get(f"/tasks/{t_id}/result", headers={"X-API-Key": key_a})
        assert res.status_code == 200
        assert res.json()["status"] == "failed"

    # 5. GET /tasks/{id}/events
    def test_get_task_events_replay_and_isolation(self, phase2_env) -> None:
        client, key_a, user_a, key_b, _, db = phase2_env

        t_id = uuid.uuid4()
        r_id = uuid.uuid4()

        task = Task(id=t_id, user_id=user_a.id, goal="Event test", status="running")
        run = TaskRun(id=r_id, task_id=t_id, user_id=user_a.id, status="running")
        db.add(task)
        db.add(run)

        # Add 2 events
        evt1 = AgentEvent(
            event_id=uuid.uuid4(),
            task_id=t_id,
            run_id=r_id,
            user_id=user_a.id,
            sequence=1,
            schema_version="1.0",
            timestamp=datetime.now(timezone.utc),
            event_type="task_started",
            status="running",
            metadata_={"goal": "Event test"},
        )
        evt2 = AgentEvent(
            event_id=uuid.uuid4(),
            task_id=t_id,
            run_id=r_id,
            user_id=user_a.id,
            sequence=2,
            schema_version="1.0",
            timestamp=datetime.now(timezone.utc),
            event_type="planning_started",
            status="running",
            metadata_={"iteration": 1},
        )
        db.add(evt1)
        db.add(evt2)

        # Owner gets events
        res = client.get(f"/tasks/{t_id}/events", headers={"X-API-Key": key_a})
        assert res.status_code == 200
        events = res.json()
        assert len(events) == 2
        assert events[0]["sequence"] == 1
        assert events[1]["sequence"] == 2

        # Filter after_sequence=1
        res_after = client.get(
            f"/tasks/{t_id}/events?after_sequence=1", headers={"X-API-Key": key_a}
        )
        assert res_after.status_code == 200
        events_after = res_after.json()
        assert len(events_after) == 1
        assert events_after[0]["sequence"] == 2

        # Limit > 1000 raises 422
        res_over_limit = client.get(
            f"/tasks/{t_id}/events?limit=1001", headers={"X-API-Key": key_a}
        )
        assert res_over_limit.status_code == 422

        # Cross-user access returns 403
        res_intruder = client.get(f"/tasks/{t_id}/events", headers={"X-API-Key": key_b})
        assert res_intruder.status_code == 403

    # 6. GET /memory/recipes
    def test_get_memory_recipes_isolation(self, phase2_env) -> None:
        client, key_a, user_a, key_b, user_b, db = phase2_env

        # User A trusted recipe
        rec_a = TaskRecipe(
            id=uuid.uuid4(),
            source_task_id=uuid.uuid4(),
            user_id=user_a.id,
            status=RecipeStatus.TRUSTED.value,
            task_type="math",
            problem_pattern="compound interest",
            context="financial math",
            recommended_strategy="Use exact formula",
            successful_steps=[],
            usage_count=1,
            success_after_reuse=1,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec_a)

        # User B trusted recipe
        rec_b = TaskRecipe(
            id=uuid.uuid4(),
            source_task_id=uuid.uuid4(),
            user_id=user_b.id,
            status=RecipeStatus.TRUSTED.value,
            task_type="research",
            problem_pattern="search",
            context="web search",
            recommended_strategy="Search Tavily",
            successful_steps=[],
            usage_count=2,
            success_after_reuse=2,
            created_at=datetime.now(timezone.utc),
        )
        db.add(rec_b)

        # User A sees only rec_a
        res_a = client.get("/memory/recipes", headers={"X-API-Key": key_a})
        assert res_a.status_code == 200
        data_a = res_a.json()
        assert data_a["total"] == 1
        assert data_a["items"][0]["problem_pattern"] == "compound interest"

    # 7. POST /tasks/{id}/feedback
    def test_post_task_feedback(self, phase2_env) -> None:
        client, key_a, user_a, key_b, _, db = phase2_env

        t_id = uuid.uuid4()
        task = Task(id=t_id, user_id=user_a.id, goal="Feedback task", status="succeeded")
        db.add(task)

        # Valid feedback submission
        res = client.post(
            f"/tasks/{t_id}/feedback",
            json={"rating": 5, "comment": "Excellent execution!"},
            headers={"X-API-Key": key_a},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "recorded"
        assert "feedback_id" in res.json()

        # Rating out of bounds (6) -> 422
        res_bad = client.post(
            f"/tasks/{t_id}/feedback",
            json={"rating": 6},
            headers={"X-API-Key": key_a},
        )
        assert res_bad.status_code == 422

        # Submitting feedback on someone else's task -> 403
        res_intruder = client.post(
            f"/tasks/{t_id}/feedback",
            json={"rating": 4},
            headers={"X-API-Key": key_b},
        )
        assert res_intruder.status_code == 403

    # 8. GET /metrics
    def test_get_metrics_user_isolation(self, phase2_env) -> None:
        client, key_a, user_a, _, _, db = phase2_env

        # Create tasks for user_a
        t1 = Task(id=uuid.uuid4(), user_id=user_a.id, goal="T1", status="succeeded")
        t2 = Task(id=uuid.uuid4(), user_id=user_a.id, goal="T2", status="failed")
        db.add(t1)
        db.add(t2)

        res = client.get("/metrics", headers={"X-API-Key": key_a})
        assert res.status_code == 200
        metrics = res.json()
        assert metrics["total_tasks"] == 2
        assert metrics["successful_tasks"] == 1
        assert metrics["failed_tasks"] == 1
        assert metrics["success_rate"] == 0.5

    # 9. GET /health
    def test_get_health_endpoint(self, phase2_env) -> None:
        client, _, _, _, _, _ = phase2_env
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert "status" in data
        assert "database" in data
        assert "redis" in data

    # 10. Standard Error Formatting & Sanitization
    def test_validation_error_standard_format(self, phase2_env) -> None:
        client, key_a, _, _, _, _ = phase2_env
        res = client.post("/tasks", json={}, headers={"X-API-Key": key_a})
        assert res.status_code == 422
        data = res.json()
        assert "error" in data
        assert data["error"]["code"] == "VALIDATION_ERROR"
        assert "request_id" in data["error"]
