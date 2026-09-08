"""Add strict task and task-run status vocabulary constraints."""

from typing import Sequence, Union

from alembic import op


revision: str = "0002_status_check_constraints"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_CHECK = "status IN ('pending', 'running', 'succeeded', 'failed')"


def upgrade() -> None:
    op.create_check_constraint(
        "ck_tasks_status_valid",
        "tasks",
        _STATUS_CHECK,
    )
    op.create_check_constraint(
        "ck_task_runs_status_valid",
        "task_runs",
        _STATUS_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint("ck_task_runs_status_valid", "task_runs", type_="check")
    op.drop_constraint("ck_tasks_status_valid", "tasks", type_="check")