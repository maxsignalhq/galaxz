"""Goal workspace_root, matching the SQLite GoalStore."""

from alembic import op


revision = "0005_goal_workspace_root"
down_revision = "0004_goal_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE goals ADD COLUMN workspace_root TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE goals DROP COLUMN workspace_root")
