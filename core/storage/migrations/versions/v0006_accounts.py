"""Organizations, users and API tokens (accounts and roles)."""

from datetime import datetime, timezone

from alembic import op


revision = "0006_accounts"
down_revision = "0005_goal_workspace_root"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TABLE organizations (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)")
    op.execute(
        "CREATE TABLE users (id TEXT PRIMARY KEY, organization_id TEXT NOT NULL REFERENCES organizations(id), "
        "email TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL DEFAULT '', role TEXT NOT NULL, "
        "active BOOLEAN NOT NULL DEFAULT TRUE, created_at TEXT NOT NULL)"
    )
    op.execute(
        "CREATE TABLE api_tokens (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), "
        "token_hash TEXT NOT NULL UNIQUE, prefix TEXT NOT NULL, role TEXT NOT NULL, expires_at TEXT, "
        "revoked_at TEXT, created_at TEXT NOT NULL)"
    )
    op.execute("CREATE INDEX api_tokens_user ON api_tokens(user_id)")
    op.execute(
        f"INSERT INTO organizations (id, name, created_at) VALUES ('default', 'Default', '{datetime.now(timezone.utc).isoformat()}')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE api_tokens")
    op.execute("DROP TABLE users")
    op.execute("DROP TABLE organizations")
