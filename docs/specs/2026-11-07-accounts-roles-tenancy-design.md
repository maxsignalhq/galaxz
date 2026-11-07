# Accounts, roles and multi-tenancy — design

Date: 2026-11-07. Depends on: audit logging. Status: drafted at the maintainer's request; **phase A implemented** (phases B and C are not).

## Problem
Auth is one shared `GALAXZ_API_KEY`. Everyone who has it is an administrator, and the identity
recorded for human decisions is whatever string the caller puts in `reviewed_by` in a request body
(review approvals, fine-tune and lesson approvals). There is no organization boundary: one
deployment is one tenant, even though `ArtifactStore` and `SecretScope` already carry an
`organization_id`.

## Goals
- Named users who belong to an organization with a role; API tokens tied to a user/org/role.
- Role-based access control on every non-exempt endpoint.
- Human decisions are attributed to the authenticated principal, not a body field.
- Organization isolation of goals, repositories, artifacts, memory and jobs.

## Non-goals
Billing/metering UI, SCIM provisioning, per-resource ACLs finer than role + organization, PostgreSQL
RLS (considered; deferred to a later hardening pass), cross-organization sharing.

## Data model (Alembic migration `0006_accounts`; SQLite parity for local mode)
`organizations(id, name, created_at)`, `users(id, organization_id, email, display_name, role, active, created_at)`,
`api_tokens(id, user_id, token_hash, prefix, role, expires_at, revoked_at, created_at)`.
Tokens are random 32-byte values shown once; only `sha256(token)` and an 8-character prefix are stored.
A user has exactly one role in exactly one organization in this version.

## Roles
| Role | Can |
|---|---|
| `viewer` | read goals, tasks, artifacts, status |
| `operator` | viewer + submit tasks/goals/jobs, pause/resume/cancel/rerun, memory write |
| `reviewer` | viewer + review queue decisions, fine-tune/lesson approvals |
| `admin` | everything, plus users, tokens, repositories, config, secrets, audit read |
Permissions are named (`goal:write`, `review:decide`, `audit:read`, ...) and mapped to roles in one
table in code. Endpoints declare the permission they need; the default for an undeclared
non-exempt route is `admin`, so a forgotten route fails closed.

## Compatibility
- `GALAXZ_API_KEY` still works: it resolves to `Principal(id="api-key", role=admin, org="default")`.
- No users and no key ⇒ auth stays disabled exactly as today (local dev).
- `reviewed_by` stays in request models for one release, ignored when an authenticated user principal
  exists (the principal id is recorded instead) and still honored for the legacy `api-key` principal.

## Tenant scoping (phase B, separate PR)
Add `organization_id` to goals, repositories, jobs, memory and artifacts (already present). Every
store read/write takes the caller's organization; a row from another organization is reported as
404, never 403, so existence does not leak. Background workers act on behalf of the task's
organization, taken from the goal. Per-organization quotas reuse `core.platform.enforce_quota`.

## Phases
A. users/orgs/tokens/RBAC on the existing single `default` org (ships value alone: real identities
and least privilege). B. organization scoping of stored data. C. quotas.

## Left to the builder
Token format prefix, password-less admin bootstrap command (`galaxz admin create-token`), and the
exact permission names.

## Phase A as built (what differs from or adds to the text above)
- **Token format:** `gzt_` + 43 URL-safe characters; stored as SHA-256 only, with the 8-character prefix
  kept for identification. A token's role may equal the user's role or be `viewer`; an `admin` user may
  issue a token of any role. Tokens may expire (`--ttl-days`) and be revoked.
- **Management is CLI-only** (`galaxz admin user-create | user-list | user-deactivate | token-create |
  token-revoke`), so there is no unauthenticated or self-service path to create an administrator. Each
  action is written to the audit log (never the token).
- **Authentication:** `GET /auth/me` returns the caller's principal. Auth becomes mandatory as soon as one
  user exists, even when `GALAXZ_API_KEY` is unset. If the account store cannot be read the request is
  refused with 503; it never falls back to open access.
- **Permissions:** `read`, `work:write`, `review:decide`, `audit:read`, `admin`; the full route table is in
  `core/accounts/permissions.py`. A test walks every route in the app and fails if one is not declared.
  FastAPI's built-in `/docs`, `/redoc` and `/openapi.json` are declared `admin`. `GET /orion/export`
  (the full training dataset) is `admin`.
- **`reviewed_by`:** the review-queue endpoints (`approve`/`accept`/`reject`) never recorded a reviewer, so
  attribution for them comes from the audit log (principal and task id in the path). The fine-tune and
  lesson approval endpoints now record the authenticated user (`user:<email>`) instead of the body field;
  the body field is still honored for the legacy API key.
- **Storage:** Alembic `0006_accounts` (seeds the `default` organization). Local mode uses SQLite
  (`GALAXZ_ACCOUNTS_DB`); a PostgreSQL `GALAXZ_DATABASE_URL` is used when set. Verified against a real
  PostgreSQL 16.

## Not yet done
- Phase B (organization scoping of goals, repositories, jobs, memory, artifacts) and C (quotas).
- Prism has no login: it authenticates with the deployment's `GALAXZ_API_KEY`, so all its users act as that
  key's administrator. The OIDC spec is what fixes this.
- Rate limiting on failed token attempts.
