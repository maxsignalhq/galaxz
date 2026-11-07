# Per-agent authentication — design

Date: 2026-11-07. Depends on: accounts/roles, audit logging. Status: specified, not implemented.

## Problem
Any process that can reach Pulsar can register a manifest for any `agent_id` and claim any skill.
`core/security/service_identity.py` has the right idea (scoped, expiring credentials) but keeps
tokens in process memory under a random per-process secret, so a token issued by one process cannot
be verified by another. That makes it unusable for the API, the worker and the distributed
Vega/Rigel services, which are separate processes.

## Goals
- An agent proves which `agent_id` it is when it registers, heartbeats or reports.
- A credential can only act for its own `agent_id` and only within its granted scopes.
- Credentials are issued, rotated and revoked by an admin, persist across restarts, and are shared
  by every service that verifies them.

## Non-goals
Redis ACLs for Aether (infrastructure concern), mutual TLS, auth for in-process agents (they share
the process trust boundary), end-user authentication.

## Design
`agent_credentials(id, agent_id, token_hash, scopes, expires_at, revoked_at, created_at)` stored in
the operational database (Alembic migration; SQLite locally). Token = random 32 bytes, hashed with
SHA-256 at rest, displayed once. `ServiceIdentityAuthority` is reimplemented over this table
(same `issue / verify / revoke` surface and tests) instead of its in-memory dict.

Scopes: `pulsar:register`, `pulsar:heartbeat`, `aether:feedback`. The credential's `agent_id` must
equal the `agent_id` in the manifest or event it accompanies; a mismatch is rejected and audited.

Pulsar's HTTP service requires `Authorization: Bearer <agent token>` on register/heartbeat when
`GALAXZ_AGENT_AUTH=required`. Default is `optional` for one release (log a warning when absent) then
`required`. Operators issue a token with `galaxz agent-token issue --agent-id rigel --scope pulsar:register`;
Constellation installs print the command, they do not mint tokens automatically.

## Failure and audit
Invalid, expired, revoked or wrong-agent tokens return 401/403 with a fixed body and write an
`agent.auth.rejected` audit event (agent_id claimed, reason code, never the token).

## Left to the builder
Token prefix format, rotation overlap window (suggest: two active credentials per agent), and how
the distributed-agents compose profile receives its token (env var).
