"""External artifact payload metadata and download scopes."""

from alembic import op


revision = "0003_artifact_objects"
down_revision = "0002_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE artifact_versions ADD COLUMN object_id TEXT")
    op.execute("ALTER TABLE artifact_versions ADD COLUMN object_size_bytes BIGINT")
    op.execute("ALTER TABLE artifact_versions ADD COLUMN media_type TEXT")
    op.execute("ALTER TABLE artifact_versions ADD COLUMN project_id TEXT")
    op.execute("ALTER TABLE artifact_versions ADD COLUMN organization_id TEXT")
    op.execute("CREATE UNIQUE INDEX artifact_object_identity ON artifact_versions(object_id) WHERE object_id IS NOT NULL")


def downgrade() -> None:
    op.drop_index("artifact_object_identity", table_name="artifact_versions")
    op.execute("ALTER TABLE artifact_versions DROP COLUMN organization_id")
    op.execute("ALTER TABLE artifact_versions DROP COLUMN project_id")
    op.execute("ALTER TABLE artifact_versions DROP COLUMN media_type")
    op.execute("ALTER TABLE artifact_versions DROP COLUMN object_size_bytes")
    op.execute("ALTER TABLE artifact_versions DROP COLUMN object_id")
