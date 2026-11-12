"""Organization scope for the task log and review queue (accounts phase B2a)."""

from alembic import op


revision = "0008_review_task_scope"
down_revision = "0007_organization_scope"
branch_labels = None
depends_on = None

_TABLES = ("tasks", "review_queue")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'default'")
        op.execute(f"CREATE INDEX {table}_organization ON {table}(organization_id)")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP INDEX {table}_organization")
        op.execute(f"ALTER TABLE {table} DROP COLUMN organization_id")
