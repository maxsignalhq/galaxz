"""Synchronous, idempotent schema upgrades for Orion's SQLite files (accounts phase B3)."""
from __future__ import annotations

import os
import sqlite3

_TABLES = ("feedback_events", "events")


def ensure_organization_columns(db_path: str) -> None:
    """Add ``organization_id`` to a pre-tenancy events database; existing rows land in ``default``.

    Orion's own startup does this too, but the API reads the file directly and may run first.
    """
    if not os.path.exists(db_path):
        return
    try:
        with sqlite3.connect(db_path) as conn:
            for table in _TABLES:
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if columns and "organization_id" not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN organization_id TEXT NOT NULL DEFAULT 'default'")
    except sqlite3.Error:
        pass
