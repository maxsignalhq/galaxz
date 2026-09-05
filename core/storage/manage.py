"""Explicit PostgreSQL schema administration; never imported to auto-migrate."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

import click
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.engine import Engine
from sqlalchemy.engine import make_url


# All processes administering this schema serialize on the same transaction lock.
MIGRATION_LOCK = 73482046001
_migration_lock = Lock()


class SchemaVersionError(RuntimeError):
    pass


def validate_runtime_database_configuration() -> None:
    """Keep the startup hook for compatibility; boot performs the schema check."""
    return None


def migration_config(connection: Connection | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def expected_revision() -> str:
    head = ScriptDirectory.from_config(migration_config()).get_current_head()
    assert head is not None
    return head


def database_engine(database_url: str) -> Engine:
    try:
        url = make_url(database_url)
    except Exception:
        raise ValueError("GALAXZ_DATABASE_URL must be a valid PostgreSQL URL") from None
    if url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg2")
    if url.drivername not in ("postgresql", "postgresql+psycopg2"):
        raise ValueError("Production schema administration requires a PostgreSQL URL")
    return create_engine(url, pool_pre_ping=True, hide_parameters=True)


def require_current_schema(connection: Connection) -> None:
    """Read-only compatibility check for future production repository startup."""
    if connection.dialect.name != "postgresql":
        raise SchemaVersionError("Production schema checks require PostgreSQL")
    actual = MigrationContext.configure(connection).get_current_heads()
    expected = expected_revision()
    if actual != (expected,):
        raise SchemaVersionError(
            f"Unsupported operational schema {actual or '(uninitialized)'}; expected {expected}. "
            "For older schemas run python -m core.storage.manage upgrade before starting services. "
            "For newer or divergent schemas use the matching Galaxz release; do not downgrade automatically."
        )


def migrate(engine: Engine, revision: str = "head") -> None:
    """Apply reviewed revisions atomically, with a database-wide migration lock."""
    # Alembic's context proxy is process-global; also serialize callers in this
    # process before taking the database lock shared by separate deploy commands.
    with _migration_lock, engine.begin() as connection:
        if connection.dialect.name != "postgresql":
            raise ValueError("Production migrations require PostgreSQL")
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        command.upgrade(migration_config(connection), revision)


@click.command()
@click.argument("action", type=click.Choice(["upgrade", "check"]))
def main(action: str) -> None:
    """Upgrade or check GALAXZ_DATABASE_URL without starting API or worker services."""
    database_url = os.getenv("GALAXZ_DATABASE_URL")
    if not database_url:
        raise click.ClickException("Set GALAXZ_DATABASE_URL to the PostgreSQL database to administer")
    engine = None
    try:
        engine = database_engine(database_url)
        if action == "upgrade":
            migrate(engine)
        with engine.connect() as connection:
            require_current_schema(connection)
    except (ValueError, SchemaVersionError) as exc:
        raise click.ClickException(str(exc)) from None
    except Exception:
        # Driver errors can contain connection credentials or SQL values.
        raise click.ClickException(
            "PostgreSQL schema operation failed. Check connectivity, migration permissions, "
            "schema revision and database server logs. No automatic fallback to SQLite was attempted."
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
    click.echo(f"Operational schema ready: {expected_revision()}")


if __name__ == "__main__":
    main()
