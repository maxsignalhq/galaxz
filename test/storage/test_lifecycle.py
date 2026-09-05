import json
import sqlite3
from datetime import datetime, timedelta, timezone

from core.storage.lifecycle import RetentionPolicy, SQLiteLifecycle, verify_export


def test_policy_round_trip_and_validation(tmp_path):
    path = tmp_path / "retention.json"
    policy = RetentionPolicy({"jobs": 7, "tasks": 30})
    policy.write(path)
    loaded = RetentionPolicy.from_file(path)
    assert loaded.days["jobs"] == 7
    assert loaded.days["goals"] == 365


def test_export_is_portable_and_checksum_verified(tmp_path):
    source = tmp_path / "jobs.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE values_table(value TEXT)")
    connection.execute("INSERT INTO values_table VALUES ('portable')")
    connection.commit(); connection.close()
    package = SQLiteLifecycle({"jobs": source}).export(tmp_path / "export.zip")
    manifest = verify_export(package)
    assert manifest["format"] == "galaxz-operational-export-v1"
    assert manifest["stores"]["jobs"]["size"] > 0


def test_purge_supports_dry_run_and_deletes_expired_rows(tmp_path):
    source = tmp_path / "tasks.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE tasks (issued_at TEXT, completed_at TEXT)")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    connection.execute("INSERT INTO tasks VALUES (?, ?)", (old, old))
    connection.commit(); connection.close()
    lifecycle = SQLiteLifecycle({"tasks": source})
    assert lifecycle.purge_expired(RetentionPolicy({"tasks": 1}), dry_run=True)["tasks"] == 1
    assert sqlite3.connect(source).execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    lifecycle.purge_expired(RetentionPolicy({"tasks": 1}))
    assert sqlite3.connect(source).execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
