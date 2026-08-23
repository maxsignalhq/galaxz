# ADR-001: Authentication Boundary for v1

## Status
Accepted — implemented. See `docs/decisions/auth-boundary.md` for the current operational
description (exempt routes, opt-in behavior); this ADR is the historical decision record for why
key-based auth was added in v1 at all rather than deferring everything to v2.

## Context
Galaxz v1 is an open-source tool intended for local and self-hosted 
deployment. The platform is stateful — tasks are queued, humans review 
them, and FeedbackEvents flow into Orion. An unauthenticated public 
deployment would be an open relay with write access to the review queue.

## Decision
v1 ships with single static API key authentication on Andromeda's HTTP
endpoints, **opt-in via the `GALAXZ_API_KEY` environment variable** — if unset, auth is disabled
(local dev mode). A fixed set of read-only routes (`/health`, `/status`, `/agents`,
`/tasks/recent`, `/tasks/stats`, `/review/queue`, `/orion/status`) are always exempt, even when a
key is set. Multi-tenancy, JWT, OAuth, and workspace isolation are explicitly out
of scope for v1.

## Consequences
- When `GALAXZ_API_KEY` is set, any request to a non-exempt route without a valid key returns 401
- When `GALAXZ_API_KEY` is unset, all routes are open — this is the default, not an error state
- Key is set in .env, excluded from version control via .gitignore
- Contributors must not build conflicting auth approaches in v1
- Full auth system (JWT, workspaces, tenant isolation) is a v2 milestone

## Out of scope until v2
- Multi-tenancy
- User accounts and roles
- OAuth / SSO
- Per-agent authentication
- Audit logging
- Fine-tune execution — approval workflow only, no training runs in v1
