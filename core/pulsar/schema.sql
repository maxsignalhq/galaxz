-- Pulsar agent registry schema
-- Identical for SQLite and PostgreSQL.

CREATE TABLE IF NOT EXISTS agents (
    registry_key TEXT PRIMARY KEY,
    agent_id     TEXT NOT NULL UNIQUE,
    data_json    TEXT NOT NULL
);
