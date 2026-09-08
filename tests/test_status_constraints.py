"""Tests for strict task and task-run status database constraints."""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, Column, MetaData, String, Table, create_engine, insert
from sqlalchemy.exc import IntegrityError

from backend.db.models import Task, TaskRun, TaskStatus


def constrained_status_table(source: Table, name: str) -> Table:
    constraints = [
        CheckConstraint(str(constraint.sqltext), name=constraint.name)
        for constraint in source.constraints
        if isinstance(constraint, CheckConstraint)
    ]
    return Table(
        name,
        MetaData(),
        Column("status", String(20), nullable=False),
        *constraints,
    )


@pytest.mark.parametrize("model", [Task, TaskRun])
def test_status_constraints_accept_blueprint_values(model: type[Task] | type[TaskRun]) -> None:
    table = constrained_status_table(model.__table__, f"{model.__tablename__}_status_test")
    engine = create_engine("sqlite://")
    table.create(engine)

    with engine.begin() as connection:
        for status in TaskStatus:
            connection.execute(insert(table).values(status=status.value))


@pytest.mark.parametrize("model", [Task, TaskRun])
@pytest.mark.parametrize("status", ["completed", "cancelled", "invalid"])
def test_status_constraints_reject_invalid_values(
    model: type[Task] | type[TaskRun],
    status: str,
) -> None:
    table = constrained_status_table(model.__table__, f"{model.__tablename__}_invalid_status_test")
    engine = create_engine("sqlite://")
    table.create(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert(table).values(status=status))