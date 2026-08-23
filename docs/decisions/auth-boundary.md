# Authentication Boundary — v1.0

> **Reconciled 2026-08-23.** This doc previously said v1.0 ships with *no* authentication at all,
> while `ADR-001-auth.md` said v1 ships with *mandatory* API-key auth on every endpoint. Neither
> matched the code. This version describes what `agents/andromeda/middleware/auth.py`
> (`ApiKeyMiddleware`) actually does. `ADR-001-auth.md` has been updated to match and should be
> read as the historical decision record; this doc is the current operational description.

## Decision
Galaxz v1.0 ships with **optional** static API-key authentication on Andromeda's HTTP API,
off by default. This is an explicit, intentional decision — not an oversight.

## Rationale
v1.0 is designed for:
- Local development and testing (single developer, localhost) — auth off, zero friction
- Trusted internal networks (team deployments behind a firewall) — auth on, via one env var
- Open source contributors evaluating the platform

Making auth opt-in avoids forcing every local/dev user to manage a key, while still giving
team deployments a real (if minimal) boundary without waiting on a full v2 auth system.

## What this means
- If `GALAXZ_API_KEY` is **unset**, all endpoints are open — no token required. Andromeda logs
  `GALAXZ_API_KEY not set — auth disabled (local dev mode)` at startup as a reminder.
- If `GALAXZ_API_KEY` **is set**, every request must send `Authorization: Bearer <key>` or get a
  `401 {"error": "unauthorized"}` — **except** the routes below, which are always public
  regardless of key, so health checks and read-only dashboards keep working:
  `GET /health`, `GET /status`, `GET /agents`, `GET /tasks/recent`, `GET /tasks/stats`,
  `GET /review/queue`, `GET /orion/status`.
- `.env.example` ships `GALAXZ_API_KEY=change-me-before-deploying` as a placeholder — **you must
  change this value** before any non-localhost deployment, or you'll have a well-known key.
- Do not expose an instance to the public internet, keyed or not, without also putting a reverse
  proxy in front of it (nginx basic auth, Cloudflare Access, etc.) — a single static key is not a
  substitute for TLS, rate limiting, or per-user accounts.

## Implementation (this is the mechanism, already shipped — not a future plan)
- API key authentication via `Authorization: Bearer <key>`, enforced by `ApiKeyMiddleware`
  (`agents/andromeda/middleware/auth.py`), wired into `services/andromeda_service.py`.
- Key comes from the `GALAXZ_API_KEY` environment variable — there is no `api_keys` table or
  per-key storage; it's a single shared secret, not multi-key or per-user.
- All existing agent and Orion code is unchanged — auth lives at the HTTP layer in Andromeda only.

## For contributors
Do not add auth to agent code, Orion pipeline, or Pulsar registry.
Auth belongs at the HTTP request layer in Andromeda only.

## Out of scope until v2
- Multi-tenancy, per-key/per-user accounts, OAuth/SSO
- Per-agent authentication, audit logging
- Anything beyond the single shared static key described above
