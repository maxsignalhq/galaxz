"""Artifact versions always belong to an organization (accounts phase B2b)."""

from alembic import op


revision = "0009_artifact_scope"
down_revision = "0008_review_task_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE artifact_versions SET organization_id = 'default' WHERE organization_id IS NULL")
    op.execute("ALTER TABLE artifact_versions ALTER COLUMN organization_id SET DEFAULT 'default'")
    op.execute("ALTER TABLE artifact_versions ALTER COLUMN organization_id SET NOT NULL")
    op.execute("CREATE INDEX artifact_versions_organization ON artifact_versions(organization_id)")


def downgrade() -> None:
    op.execute("DROP INDEX artifact_versions_organization")
    op.execute("ALTER TABLE artifact_versions ALTER COLUMN organization_id DROP NOT NULL")
    op.execute("ALTER TABLE artifact_versions ALTER COLUMN organization_id DROP DEFAULT")
