"""Consolidated baseline of the current operational stores.

Revision ID: 0001_operational
Revises: None
"""

from importlib.resources import files

from alembic import op


revision = "0001_operational"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql = files("core.storage.migrations").joinpath("0001_operational.sql").read_text()
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    for table in (
        "artifact_versions", "review_queue", "goal_repositories", "goal_events", "tasks", "planned_tasks",
        "projects", "goals", "job_outputs", "job_tasks", "job_idempotency",
        "job_transitions", "execution_attempts", "jobs",
    ):
        op.drop_table(table)
