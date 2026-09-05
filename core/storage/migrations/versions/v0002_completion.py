"""Durable completion publication and immutable attempt evidence mappings.

Revision ID: 0002_completion
Revises: 0001_operational
"""

from alembic import op


revision = "0002_completion"
down_revision = "0001_operational"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE completion_outbox (
            job_id TEXT PRIMARY KEY REFERENCES jobs(job_id),
            attempt_id TEXT NOT NULL UNIQUE REFERENCES execution_attempts(attempt_id),
            created_at TEXT NOT NULL,
            published_at TEXT
        )
    """)
    op.execute("""
        CREATE TABLE artifact_attempt_versions (
            attempt_artifact_key TEXT PRIMARY KEY,
            identity_key TEXT NOT NULL,
            version INTEGER NOT NULL,
            FOREIGN KEY (identity_key, version) REFERENCES artifact_versions(identity_key, version)
        )
    """)
    op.execute("""
        INSERT INTO artifact_attempt_versions (attempt_artifact_key, identity_key, version)
        SELECT attempt_artifact_key, identity_key, version FROM artifact_versions
        WHERE attempt_artifact_key IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX completion_pending ON completion_outbox(created_at)
        WHERE published_at IS NULL
    """)


def downgrade() -> None:
    op.drop_table("artifact_attempt_versions")
    op.drop_table("completion_outbox")
