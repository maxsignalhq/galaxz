# Authentication Boundary — v1.0

## Decision
Galaxz v1.0 ships with no authentication on any API endpoint.
This is an explicit, intentional decision — not an oversight.

## Rationale
v1.0 is designed for:
- Local development and testing (single developer, localhost)
- Trusted internal networks (team deployments behind a firewall)
- Open source contributors evaluating the platform

Adding auth before the core routing, learning, and agent protocol
are stable would create churn. The API surface is still evolving.

## What this means
- All API endpoints are open with no token or key required
- Do not expose a v1.0 instance to the public internet
- For internet-facing deployments: put a reverse proxy with auth
  (nginx basic auth, Cloudflare Access, etc.) in front of Galaxz

## The v1.1 auth contract
When auth is added in v1.1, it will:
- Use API key authentication (Authorization: Bearer <key>)
- Keys stored in a new api_keys table in andromeda_tasks.db
- All existing agent and Orion code unchanged — auth at the
  HTTP layer only, not inside business logic
- /health endpoint remains public — no auth required

## For contributors
Do not add auth to agent code, Orion pipeline, or Pulsar registry.
Auth belongs at the HTTP request layer in Andromeda only.
See GitHub Issue #auth-v1.1 for the implementation spec when ready.
