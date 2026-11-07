"""Organization scope for goals and jobs (accounts phase B1).

Existing rows are backfilled into the ``default`` organization by the column default.
"""

from alembic import op


revision = "0007_organization_scope"
down_revision = "0006_accounts"
branch_labels = None
depends_on = None

_TABLES = ("goals", "jobs")


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'default'")
        op.execute(f"CREATE INDEX {table}_organization ON {table}(organization_id)")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP INDEX {table}_organization")
        op.execute(f"ALTER TABLE {table} DROP COLUMN organization_id")
