"""Goal token budget, usage and provider-failover pause metadata."""

from alembic import op


revision = "0004_goal_budget"
down_revision = "0003_artifact_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE goals ADD COLUMN token_budget BIGINT")
    op.execute("ALTER TABLE goals ADD COLUMN tokens_used BIGINT NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE goals ADD COLUMN fallback_used BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE goals ADD COLUMN resume_after TEXT")
    op.execute("ALTER TABLE goals ADD COLUMN pause_reason TEXT")


def downgrade() -> None:
    for column in ("pause_reason", "resume_after", "fallback_used", "tokens_used", "token_budget"):
        op.execute(f"ALTER TABLE goals DROP COLUMN {column}")
