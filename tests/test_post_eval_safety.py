"""
Focused regression tests for post-evaluation safety and task finalization.

Verifies:
1. evaluate -> maybe_learn -> respond -> END completes deterministically without deadlock.
2. Learning exception or failure does not block respond; task completes cleanly.
3. Duplicate evaluation persistence attempt for (run_id, iteration_count) does not violate uq_run_iteration.
4. Task finalization after successful graph execution marks task and run as succeeded in DB.
5. Task finalization after learning failure transitions out of 'running'.
6. Learning timeout does not hang the worker; execution continues to respond.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, Optional
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.agent.graph import create_agent_graph
from backend.agent.nodes.learn import learn_node
from backend.agent.nodes.respond import respond_node
from backend.agent.providers.base import LLMProvider
from backend.agent.runtime import AgentRuntime, set_current_runtime
from backend.agent.state import create_initial_state
from backend.db.models import Evaluation, RecipeCandidate, Task, TaskRun, TaskStatus, User
from backend.db.session import create_engine_instance, dispose_engine
from backend.evaluation.scorer import score_and_record_evaluation
from backend.worker.tasks import _execute_agent_run


class MockDeterministicSuccessProvider(LLMProvider):
    """Provider that produces a successful execution without calling external LLM."""

    async def understand(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"understood_task": "Calculate TCP checksum", "task_type": "math", "needs_tools": False}

    async def plan(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"plan": ["Compute checksum", "Verify result"], "current_step": "Compute checksum"}

    async def decide_step_action(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "call_tool": False,
            "tool_name": None,
            "parameters": {},
            "thought": "Checksum computation complete",
            "draft_answer": "TCP checksum is 0x4a2b",
        }

    async def reflect(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"reflection": "No adjustments needed."}

    async def judge(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "judge_score": 8.5,
            "judge_reasoning": "Output completely satisfies task criteria.",
            "task_success": True,
            "deterministic_pass": True,
            "tool_success": True,
        }

    async def respond(self, state: dict[str, Any]) -> dict[str, Any]:
        return {"final_response": "The computed TCP checksum is 0x4a2b."}


async def _create_test_user_and_task(session: AsyncSession) -> tuple[User, Task, TaskRun]:
    """Helper creating prerequisite User, Task, and TaskRun records in PostgreSQL."""
    user = User(
        id=uuid.uuid4(),
        display_name=f"test_{uuid.uuid4().hex[:8]}",
        api_key_hash=f"hash_{uuid.uuid4().hex}",
    )
    session.add(user)
    await session.flush()

    task = Task(
        id=uuid.uuid4(),
        user_id=user.id,
        goal="Calculate TCP checksum for network packet",
        status=TaskStatus.PENDING.value,
    )
    session.add(task)
    await session.flush()

    task_run = TaskRun(
        id=uuid.uuid4(),
        task_id=task.id,
        user_id=user.id,
        status=TaskStatus.PENDING.value,
        sequence_counter=0,
    )
    session.add(task_run)
    await session.commit()

    return user, task, task_run


@pytest.mark.asyncio
async def test_successful_evaluate_maybe_learn_respond_end() -> None:
    """
    1. evaluate -> maybe_learn -> respond -> END:
    Ensures that with an active session factory and real DB records,
    maybe_learn records candidate and emits events without deadlock,
    and the graph terminates deterministically at END.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)

        provider = MockDeterministicSuccessProvider()
        runtime = AgentRuntime(llm_provider=provider, session_factory=session_factory)
        set_current_runtime(runtime)

        state = create_initial_state(
            task_id=str(task.id),
            run_id=str(run.id),
            user_id=str(user.id),
            goal="Calculate TCP checksum for network packet",
        )

        app = create_agent_graph()
        thread_config = AgentRuntime.get_thread_config(run.id)

        # Must complete within 15 seconds without deadlocking on Postgres row locks
        final_state = await asyncio.wait_for(
            app.ainvoke(state, config=thread_config),
            timeout=15.0,
        )

        assert final_state["status"] == "succeeded"
        assert final_state["iteration_count"] == 1
        assert final_state["evaluation"]["task_success"] is True
        assert "0x4a2b" in final_state["final_response"]

        # Verify recipe candidate was persisted
        async with session_factory() as verify_session:
            stmt = select(RecipeCandidate).where(RecipeCandidate.run_id == run.id)
            res = await verify_session.execute(stmt)
            candidates = res.scalars().all()
            assert len(candidates) >= 1
            assert candidates[0].task_type == "math"

        await runtime.close()
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_learning_exception_still_reaches_respond() -> None:
    """
    2. Learning failure must never prevent task completion.
    Simulate a DB failure during maybe_learn; respond must still execute and reach END.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)

        provider = MockDeterministicSuccessProvider()
        runtime = AgentRuntime(llm_provider=provider, session_factory=session_factory)
        set_current_runtime(runtime)

        state = create_initial_state(
            task_id=str(task.id),
            run_id=str(run.id),
            user_id=str(user.id),
            goal="Calculate TCP checksum for network packet",
        )
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 8.5,
            "deterministic_pass": True,
            "tool_success": True,
        }
        state["plan"] = ["Step 1", "Step 2"]
        state["understood_task"] = "TCP checksum"
        state["task_type"] = "math"

        # Monkeypatch evaluate_quality_gate to raise an exception
        import backend.agent.nodes.learn as learn_module
        orig_qg = learn_module.evaluate_quality_gate

        async def _failing_quality_gate(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Simulated transient database connection failure during quality gate")

        learn_module.evaluate_quality_gate = _failing_quality_gate
        try:
            learn_result = await learn_node(state)
            assert learn_result["learning_decision"] == "skip"
            assert learn_result["current_step"] == "respond"

            state.update(learn_result)
            respond_result = await respond_node(state)
            assert respond_result["status"] == "succeeded"
            assert respond_result["final_response"] != ""
        finally:
            learn_module.evaluate_quality_gate = orig_qg

        await runtime.close()
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_duplicate_evaluation_attempt() -> None:
    """
    3. Duplicate evaluation persistence for (run_id, iteration_count) must be handled safely
    without violating uq_run_iteration or poisoning the session.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)

            state = create_initial_state(
                task_id=str(task.id),
                run_id=str(run.id),
                user_id=str(user.id),
                goal="Test duplicate evaluation",
            )
            state["iteration_count"] = 0  # score_and_record_evaluation computes iteration 0 + 1 = 1

            judge_1 = {
                "judge_score": 7.5,
                "judge_reasoning": "First pass reasoning",
            }
            judge_2 = {
                "judge_score": 8.5,
                "judge_reasoning": "Updated evaluation reasoning",
            }

            # First insert
            eval_dict_1 = await score_and_record_evaluation(state, session, judge_1)
            await session.commit()
            assert eval_dict_1["iteration_count"] == 1

            # Second insert attempt for the same iteration
            eval_dict_2 = await score_and_record_evaluation(state, session, judge_2)
            await session.commit()
            assert eval_dict_2["iteration_count"] == 1
            assert eval_dict_2["judge_score"] == 8.5

            # Verify exactly one evaluation row exists in DB and was updated in place
            stmt = select(Evaluation).where(Evaluation.run_id == run.id, Evaluation.iteration_count == 1)
            res = await session.execute(stmt)
            rows = res.scalars().all()
            assert len(rows) == 1
            assert rows[0].judge_score == Decimal("8.5")
            assert rows[0].payload == {"judge_reasoning": "Updated evaluation reasoning"}
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_task_finalization_after_successful_execution() -> None:
    """
    4. Worker task finalization: run_agent_task / _execute_agent_run terminates
    and updates both task and task_run to 'succeeded', never leaving them in 'running'.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)
    finally:
        await dispose_engine(engine)

    provider = MockDeterministicSuccessProvider()
    runtime = AgentRuntime(llm_provider=provider)
    set_current_runtime(runtime)

    # Execute full worker runner
    await asyncio.wait_for(_execute_agent_run(str(run.id), llm_provider=provider), timeout=20.0)

    # Verify task and run status in DB
    check_engine = create_engine_instance()
    check_factory = async_sessionmaker(bind=check_engine, expire_on_commit=False)
    try:
        async with check_factory() as verify_session:
            run_res = await verify_session.execute(select(TaskRun).where(TaskRun.id == run.id))
            persisted_run = run_res.scalar_one()
            assert persisted_run.status == TaskStatus.SUCCEEDED.value

            task_res = await verify_session.execute(select(Task).where(Task.id == task.id))
            persisted_task = task_res.scalar_one()
            assert persisted_task.status == TaskStatus.SUCCEEDED.value
    finally:
        await dispose_engine(check_engine)


@pytest.mark.asyncio
async def test_task_finalization_after_learning_failure() -> None:
    """
    5. Even when learning persistence throws an error, the worker run terminates
    and finalizes the task status to succeeded.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)
    finally:
        await dispose_engine(engine)

    provider = MockDeterministicSuccessProvider()
    runtime = AgentRuntime(llm_provider=provider)
    set_current_runtime(runtime)

    import backend.agent.nodes.learn as learn_module
    orig_record = learn_module.record_recipe_candidate

    async def _failing_record(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Simulated failure recording candidate recipe")

    learn_module.record_recipe_candidate = _failing_record
    try:
        await asyncio.wait_for(_execute_agent_run(str(run.id), llm_provider=provider), timeout=20.0)

        check_engine = create_engine_instance()
        check_factory = async_sessionmaker(bind=check_engine, expire_on_commit=False)
        try:
            async with check_factory() as verify_session:
                run_res = await verify_session.execute(select(TaskRun).where(TaskRun.id == run.id))
                persisted_run = run_res.scalar_one()
                assert persisted_run.status == TaskStatus.SUCCEEDED.value

                task_res = await verify_session.execute(select(Task).where(Task.id == task.id))
                persisted_task = task_res.scalar_one()
                assert persisted_task.status == TaskStatus.SUCCEEDED.value
        finally:
            await dispose_engine(check_engine)
    finally:
        learn_module.record_recipe_candidate = orig_record


@pytest.mark.asyncio
async def test_learning_timeout_does_not_block_task_completion() -> None:
    """
    6. Learning timeout protection: if learning hangs, timeout triggers,
    execution continues to respond, and task reaches succeeded.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)

        state = create_initial_state(
            task_id=str(task.id),
            run_id=str(run.id),
            user_id=str(user.id),
            goal="Calculate TCP checksum",
        )
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 8.5,
            "deterministic_pass": True,
            "tool_success": True,
        }
        state["understood_task"] = "TCP checksum"
        state["task_type"] = "math"

        provider = MockDeterministicSuccessProvider()
        runtime = AgentRuntime(llm_provider=provider, session_factory=session_factory)
        set_current_runtime(runtime)

        import backend.agent.nodes.learn as learn_module
        orig_qg = learn_module.evaluate_quality_gate

        async def _hanging_quality_gate(*args: Any, **kwargs: Any) -> Any:
            # Sleep for longer than the timeout
            await asyncio.sleep(15.0)
            return "promoted", "Done"

        learn_module.evaluate_quality_gate = _hanging_quality_gate
        try:
            # Monkeypatch timeout in learn_node test or wait
            # We test that learn_node completes cleanly
            learn_res = await asyncio.wait_for(learn_node(state), timeout=12.0)
            assert learn_res["learning_decision"] == "skip"
            assert learn_res["current_step"] == "respond"
        finally:
            learn_module.evaluate_quality_gate = orig_qg

        await runtime.close()
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_nonexistent_task_run_discarded_cleanly() -> None:
    """
    7. Stale Celery queue handling: nonexistent or malformed TaskRun is cleanly
    discarded without logging an unhandled ERROR or falsely reporting completion.
    """
    from backend.worker.tasks import _execute_agent_run, run_agent_task

    nonexistent_id = str(uuid.uuid4())

    # Direct async execution returns discarded_stale
    outcome = await _execute_agent_run(nonexistent_id)
    assert outcome == "discarded_stale"

    # Celery entrypoint returns clean discarded dict without crash
    celery_res = run_agent_task(nonexistent_id)
    assert celery_res["status"] == "discarded"
    assert celery_res["reason"] == "discarded_stale"
    assert celery_res["run_id"] == nonexistent_id

    # Malformed UUID string is also cleanly discarded
    malformed_res = run_agent_task("not-a-valid-uuid")
    assert malformed_res["status"] == "discarded"
    assert malformed_res["reason"] == "discarded_stale"


@pytest.mark.asyncio
async def test_terminal_task_run_discarded_cleanly() -> None:
    """
    8. Redundant Celery queue handling: already terminal TaskRun is cleanly
    discarded without re-running or updating state.
    """
    from backend.worker.tasks import _execute_agent_run, run_agent_task

    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)
            # Transition to terminal status
            run.status = TaskStatus.SUCCEEDED.value
            task.status = TaskStatus.SUCCEEDED.value
            await session.commit()
    finally:
        await dispose_engine(engine)

    # Calling run_agent_task on terminal run discards it cleanly
    celery_res = run_agent_task(str(run.id))
    assert celery_res["status"] == "discarded"
    assert celery_res["reason"] == "discarded_terminal"


def test_checkpointer_psycopg_url_normalization() -> None:
    """
    9. Verify get_psycopg_postgres_url normalizes asyncpg / psycopg SQLAlchemy URLs
    to standard psycopg-compatible postgresql:// scheme.
    """
    from backend.db.session import get_psycopg_postgres_url

    asyncpg_url = "postgresql+asyncpg://app_user:app_password@postgres:5432/agent_db"
    normalized = get_psycopg_postgres_url(asyncpg_url)
    assert normalized == "postgresql://app_user:app_password@postgres:5432/agent_db"

    psycopg_url = "postgresql+psycopg://app_user:app_password@localhost:5432/test_db"
    assert get_psycopg_postgres_url(psycopg_url) == "postgresql://app_user:app_password@localhost:5432/test_db"


@pytest.mark.asyncio
async def test_maybe_learn_transaction_before_event_ordering() -> None:
    """
    10. Regression safety: DB transaction in maybe_learn commits/closes strictly
    before learning events (LEARNING_CANDIDATE_CREATED, LEARNING_SAVED) are emitted.
    """
    engine = create_engine_instance()
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            user, task, run = await _create_test_user_and_task(session)

        state = create_initial_state(
            task_id=str(task.id),
            run_id=str(run.id),
            user_id=str(user.id),
            goal="Determine matrix rank",
        )
        state["evaluation"] = {
            "task_success": True,
            "judge_score": 9.0,
            "deterministic_pass": True,
            "tool_success": True,
        }
        state["understood_task"] = "Matrix rank"
        state["task_type"] = "math"

        execution_order: list[str] = []

        # Spy on session commit and emit_event
        orig_session_factory = session_factory

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def tracking_session_factory():
            async with orig_session_factory() as sess:
                orig_commit = sess.commit

                async def tracking_commit():
                    execution_order.append("db_commit")
                    return await orig_commit()

                sess.commit = tracking_commit
                try:
                    yield sess
                finally:
                    execution_order.append("session_closed")

        runtime = AgentRuntime(session_factory=tracking_session_factory)
        orig_emit = runtime.emit_event

        async def tracking_emit(*args: Any, **kwargs: Any) -> Any:
            event_type = kwargs.get("event_type")
            execution_order.append(f"emit_event:{getattr(event_type, 'value', event_type)}")
            return await orig_emit(*args, **kwargs)

        runtime.emit_event = tracking_emit
        set_current_runtime(runtime)

        result = await learn_node(state)
        assert result["current_step"] == "respond"

        # Verify ordering: DB commit and session close MUST happen before any event emission
        assert "db_commit" in execution_order
        assert "session_closed" in execution_order

        commit_index = execution_order.index("db_commit")
        closed_index = execution_order.index("session_closed")

        for idx, item in enumerate(execution_order):
            if item.startswith("emit_event:learning"):
                assert commit_index < idx, f"Event {item} emitted before db_commit!"
                assert closed_index < idx, f"Event {item} emitted before DB session was closed!"

        await runtime.close()
    finally:
        await dispose_engine(engine)

