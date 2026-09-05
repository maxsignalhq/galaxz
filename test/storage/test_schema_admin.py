import pytest
from click.testing import CliRunner
from sqlalchemy import create_engine

from core.storage.manage import SchemaVersionError
from core.storage.manage import database_engine
from core.storage.manage import expected_revision
from core.storage.manage import main
from core.storage.manage import migrate
from core.storage.manage import require_current_schema
from core.storage.manage import validate_runtime_database_configuration


def test_revision_graph_has_one_expected_head():
    assert expected_revision() == "0003_artifact_objects"


def test_schema_command_requires_explicit_database(monkeypatch):
    monkeypatch.delenv("GALAXZ_DATABASE_URL", raising=False)
    result = CliRunner().invoke(main, ["upgrade"])
    assert result.exit_code != 0
    assert "Set GALAXZ_DATABASE_URL" in result.output


@pytest.mark.parametrize("url", ["sqlite:///local.db", "not-a-url", "mysql://user:secret@host/db"])
def test_rejects_non_postgres_without_exposing_url(url):
    with pytest.raises(ValueError) as exc:
        database_engine(url)
    assert url not in str(exc.value)
    assert "secret" not in str(exc.value)


def test_production_migrations_do_not_touch_sqlite():
    engine = create_engine("sqlite://")
    with pytest.raises(ValueError, match="PostgreSQL"):
        migrate(engine)
    with engine.connect() as connection:
        with pytest.raises(SchemaVersionError, match="PostgreSQL"):
            require_current_schema(connection)
        assert connection.exec_driver_sql("SELECT name FROM sqlite_master").fetchall() == []
    engine.dispose()


def test_driver_failure_does_not_expose_secrets(monkeypatch):
    monkeypatch.setenv("GALAXZ_DATABASE_URL", "postgresql://user:secret@host/db")

    def fail(url):
        raise RuntimeError("secret driver error")

    monkeypatch.setattr("core.storage.manage.database_engine", fail)
    result = CliRunner().invoke(main, ["upgrade"])
    assert result.exit_code != 0
    assert "secret" not in result.output
    assert "Check connectivity" in result.output


def test_runtime_accepts_postgres_when_boot_performs_schema_check(monkeypatch):
    monkeypatch.setenv("GALAXZ_DATABASE_URL", "postgresql://user:secret@host/db")
    validate_runtime_database_configuration()
