# Pulsar Storage Backend

## Decision
SQLite is the default and recommended backend for all single-instance
Galaxz deployments. There is no performance or scale reason to change it
for self-hosted use.

## When to upgrade
Upgrade to Postgres only when running multiple Andromeda instances
(horizontal scaling). SQLite cannot be shared across processes on
different machines. A single instance with high task volume does not
require Postgres.

## How to upgrade
1. Set PULSAR_DB_URL=postgresql://... in your .env file
2. Restart the galaxz service
3. Agents re-register with Pulsar on boot — no data migration needed
   (Pulsar state is ephemeral: agents populate the registry at startup)

## Schema
The Postgres schema is identical to SQLite. See pulsar/schema.sql.

