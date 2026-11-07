# v2 identity and governance — overview and sequencing

Date: 2026-11-07. Status: drafted at the maintainer's request ("spec them out and start implementing them"); not yet reviewed.

CLAUDE.md lists these as the open v2 items: audit logging, multi-tenancy, user accounts/roles,
OAuth/SSO, per-agent authentication, and executing fine-tune runs. They depend on each other, so
they ship in this order, each as its own PR with its own spec:

| # | Spec | Why this position |
|---|------|-------------------|
| 1 | `2026-11-07-audit-logging-design.md` | Every later item emits audit events. `AuditLog` already exists as an unused library. |
| 2 | `2026-11-07-accounts-roles-tenancy-design.md` | Gives every request a *principal*. SSO, per-agent auth and tenant scoping all attach to it. |
| 3 | `2026-11-07-per-agent-auth-design.md` | Agents get their own credentials; needs the principal model and writes audit events. |
| 4 | `2026-11-07-oidc-sso-design.md` | A login method that resolves to a user from (2). |
| 5 | `2026-11-07-finetune-execution-design.md` | Highest blast radius (external spend, data leaving the platform); needs roles (2) to gate it and audit (1) to record it. |

## Shared model: the principal

Every authenticated request resolves to one `Principal(id, kind, organization_id, roles)` stored
on `request.state.principal`. `kind` is `user | api-key | agent | exempt-route | anonymous`.
`Principal.id` is the audit actor. Until (2) ships, the only principals are:

- `api-key` — a request that presented the valid `GALAXZ_API_KEY`
- `anonymous` — auth is disabled (no key configured; local dev)
- `exempt-route` — one of the routes that authenticate themselves (GitHub webhook, A2A)
- `unauthenticated` — a rejected request (recorded, never given access)

## Constraints that apply to all five

- **Backward compatible by default.** A deployment that sets nothing new behaves exactly as today.
  `GALAXZ_API_KEY` keeps working and maps to an admin principal in the `default` organization.
- **Contracts first.** Any new cross-component data shape is added to `core/contracts/` before use
  (CLAUDE.md rule). New tables are created by Alembic migrations only, never at runtime, in
  PostgreSQL deployments.
- **No secrets in logs, audit events, specs' examples, or request bodies.**
- **Each item is shippable alone.** No item may leave the platform in a state where a later item is
  required to keep it safe.

## Calls made without asking (please review)

- OIDC (generic issuer) rather than a specific vendor's SDK.
- Fine-tune execution through a provider API adapter with a dry-run default; no on-box GPU training.
- Application-level tenant filtering rather than PostgreSQL row-level security (RLS) in the first cut.
- Audit writes are best-effort (never block a request); see the audit spec for the reasoning.
