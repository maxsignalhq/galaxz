import json
import os
import sqlite3

_DEFAULT_PATH = "data/pulsar.db"

_CREATE_AGENTS_TABLE = """
CREATE TABLE IF NOT EXISTS agents (
    registry_key TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL UNIQUE,
    data_json    TEXT NOT NULL
)
"""


def _sqlite_path(url: str | None) -> str:
    if url is None:
        return _DEFAULT_PATH
    return url[len("sqlite://"):]


class _DbConnection:
    """
    Normalises SQLite and Postgres behind a single interface.
    All SQL uses ? placeholders; Postgres substitution is handled internally.
    execute() always returns a list[tuple] (empty for DDL/DML).
    """

    def __init__(self, url: str | None) -> None:
        self._pg = False
        if url is None or url.startswith("sqlite://"):
            path = _sqlite_path(url)
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._raw = sqlite3.connect(path, check_same_thread=False)
        elif url.startswith("postgresql://") or url.startswith("postgres://"):
            import psycopg2  # noqa: PLC0415
            self._raw = psycopg2.connect(url)
            self._pg = True
        else:
            raise ValueError(f"Unsupported DB URL scheme: {url!r}")

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self._pg:
            sql = sql.replace("?", "%s")
            cur = self._raw.cursor()
            cur.execute(sql, params)
            try:
                return cur.fetchall()
            except Exception:
                return []
        else:
            return self._raw.execute(sql, params).fetchall()

    def commit(self) -> None:
        self._raw.commit()


class SqliteStore:
    """
    RegistryStore implementation backed by _DbConnection.
    Supports SQLite (default) and Postgres — pass the appropriate URL.
    """

    def __init__(self, db_url: str | None) -> None:
        self._db = _DbConnection(db_url)
        self._db.execute(_CREATE_AGENTS_TABLE)
        self._db.commit()

    @staticmethod
    def _key(agent_id: str) -> str:
        return f"pulsar:agents:{agent_id}"

    def register_agent(self, agent_id: str, metadata: dict) -> None:
        self._db.execute(
            """
            INSERT INTO agents (registry_key, agent_id, data_json)
            VALUES (?, ?, ?)
            ON CONFLICT(registry_key) DO UPDATE SET
                agent_id  = excluded.agent_id,
                data_json = excluded.data_json
            """,
            (self._key(agent_id), agent_id, json.dumps(metadata)),
        )
        self._db.commit()

    def get_agent(self, agent_id: str) -> dict | None:
        rows = self._db.execute(
            "SELECT data_json FROM agents WHERE agent_id = ?", (agent_id,)
        )
        return json.loads(rows[0][0]) if rows else None

    def list_agents(self) -> list[dict]:
        rows = self._db.execute("SELECT data_json FROM agents")
        return [json.loads(r[0]) for r in rows]

    def deregister_agent(self, agent_id: str) -> None:
        self._db.execute("DELETE FROM agents WHERE agent_id = ?", (agent_id,))
        self._db.commit()

    def get_agent_skills(self, agent_id: str) -> list[dict]:
        agent = self.get_agent(agent_id)
        if agent is None:
            return []
        return agent.get("skills", [])
