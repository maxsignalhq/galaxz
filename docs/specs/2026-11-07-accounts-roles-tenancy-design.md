# Accounts, roles and multi-tenancy — design

Date: 2026-11-07. Depends on: audit logging. Status: drafted at the maintainer's request; **phase A implemented** (phase B1 and B2 implemented, B3 and C not).

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

## Tenant scoping (phase B)

Status: **proposed answers, not yet reviewed.** Phase A shipped one `default` organization; B makes the
organization boundary real. Correction to the text this replaces: only `artifact_versions` carries an
`organization_id` today (nullable, used by object-storage authorization). Goals, tasks, jobs, the review
queue, repositories and memory have none.

### Decision 1: what is scoped

| Store | Scoped by | How |
|---|---|---|
| `goals` | `organization_id` column | root of the goal tree; `projects`, `planned_tasks`, `goal_events`, `goal_repositories` inherit through `goal_id` (no denormalised column) |
| `tasks` (task log), `review_queue` | own `organization_id` column | queried by `task_id` directly, so they cannot rely on a join |
| `jobs` | own `organization_id` column | the worker needs the organization without loading the goal; child job tables inherit through `job_id` |
| `repositories`, `repository_revisions` | `organization_id` column | repository ids become unique per organization |
| `memories` (Nebula) | `organization_id` column | recall must filter by organization: a leak here puts another tenant's notes into a prompt |
| `artifact_versions` | existing column, made NOT NULL | already scoped in object storage |
| `policy_grants` | `organization_id` column | grants are authority; they must not cross tenants |
| Orion (fine-tune candidates, lessons, scorecards) | **B3**, separate PR | Orion is a separate service with its own stores; scope after the core path is proven |
| Pulsar registry, LLM limiter, provider config | **global** | agents are platform resources shared by all tenants |
| Audit log | **global**, `organization_id` recorded per event | one tamper-evident chain; `audit:read` stays admin-only; events gain an `organization_id` field so exports can be filtered |
| Secrets | already scoped | `SecretScope.organization_id` is unchanged; as of B1 the resolver uses the task's organization (a `default` task keeps using `GALAXZ_ORGANIZATION_ID`) |

The organization is stamped from the authenticated principal when a row is created and never changes.
`TaskContract` gains an optional `organization_id` (absent = `default`), set by Andromeda from the
principal; per "contracts first" this contract change lands before any store change. The worker takes the
organization from the job and passes it down, so a goal always executes as its own organization.

### Decision 2: existing rows

Migration `0007_organization_scope` adds `organization_id TEXT NOT NULL DEFAULT 'default'` to each table
above, which backfills every existing row into `default` with no data rewrite. SQLite stores add the column
the same way `ArtifactStore` already does. A deployment that never creates a second organization sees no
behaviour change. `job_idempotency` keys become `(organization_id, key)` so two tenants cannot collide or
probe each other's keys.

### Decision 3: where isolation is enforced

In the application layer (the earlier accepted decision), made hard to forget:
- Every store read and write takes `organization_id` as a **required keyword argument with no default**.
  Omitting it is a `TypeError`, not an unscoped query. Internal system actors (migrations, the reconcile
  loop listing work across tenants) call separate, explicitly named `*_all_organizations` methods.
- A row in another organization is reported as 404, never 403.
- New organizations are created from the CLI only: `galaxz admin org-create`, and `user-create
  --organization`. The legacy `GALAXZ_API_KEY` stays an `admin` of `default` only; it cannot reach other
  organizations. Cross-organization administration is a local CLI operation.
- PostgreSQL row-level security stays a non-goal for B. If wanted later it can be added as a second layer
  (`SET app.organization_id` per connection) without changing the application contract.

### Prerequisite: close the exempt reads

`GET /review/queue`, `/tasks/recent`, `/status`, `/agents` are unauthenticated and return task data. They
cannot be scoped without a principal, so B makes them require `read` (health stays exempt). This breaks any
unauthenticated monitor that scrapes them; it is called out in the CHANGELOG.

### Delivery

1. **B1** — `TaskContract.organization_id`, migration `0007`, goals/tasks/jobs/worker, `org-create`, close
   the exempt reads.
2. **B2** — review queue and task log (B2a); artifacts, repositories, memory, policy grants, GitHub and `org-create` (B2b).
3. **B3** — Orion stores.

Each PR keeps single-organization behaviour byte-for-byte. Tests: a two-organization fixture and a test
that walks every route taking an id and asserts organization B receives 404 for organization A's id; a
no-default-argument check on the store methods; a Postgres test of the migration against a populated
database.

### B1 as built (differs from the proposal above)

- **Migration `0007_organization_scope`** covers `goals` and `jobs` only. `tasks`, `review_queue`,
  repositories, memory and policy grants get their column with the PR that scopes them (B2), because a
  column nothing reads or filters on would look like isolation that is not there. SQLite stores add the
  column on open, as before; the job store has a matching SQLite migration (v3).
- **Required keyword, narrowed.** Tenant-facing lookups are the new `GoalStore.get_goal_for(id, *,
  organization_id)` and `SqliteJobRepository.get_job_for(...)` (and the Postgres twins); `list_goals` and
  `list_jobs` require `organization_id`. Mutators keyed by an id (`set_goal_status`, `cancel`, ...) stay
  unscoped because the route has already authorised that id through `_own_goal` / `get_job_for`. Platform
  internals use the explicitly named `list_jobs_all_organizations` and `list_goals(organization_id=None)`
  / `list_active_goals`. A test fails if the service calls an unscoped lookup.
- **Idempotency** is namespaced by prefixing the caller's key with the organization (`org:key`) for every
  organization except `default`, instead of changing the table's primary key.
- **`org-create` is deferred to B2.** Until the review queue, task log, repositories and memory are scoped,
  a second organization would still see them, so B1 deliberately offers no way to create one from the CLI.
- **Closed reads:** `/status`, `/agents`, `/tasks/recent`, `/tasks/stats` and `/review/queue` now require
  `read`. They are not yet filtered by organization (B2), which is safe only because a second organization
  cannot yet be created.
- Still unscoped, by design for B1: `/route` and `/task` (tasks created outside goals and jobs carry the
  default organization), the A2A gateway, and the review-resume path.

### B2a as built (task log and review queue)

- **Migration `0008_review_task_scope`** adds `organization_id` to `tasks` and `review_queue` (SQLite stores add the
  column on open; existing rows land in `default`).
- `TaskLog` and `ReviewQueue` (SQLite and Postgres): `get`, `recent`, `stats`, `throughput`, `get_pending`,
  `get_stats` require `organization_id`; `None` means every organization and is used only by the unauthenticated
  `/health` liveness count. `ReviewQueue.get_for` is the tenant-facing lookup. `enqueue` takes `organization_id`
  (default `default`) and every production caller passes it: Andromeda escalation, the completion publisher
  (from the task) and goal-plan review (from the goal).
- A status change in the task log keeps the organization the task was created under.
- `/task`, `/review/queue*`, `/tasks/*`, `/status` and `/tasks/{id}/feedback` are scoped; another organization
  gets 404.
- Two latent PostgreSQL bugs surfaced by the new Postgres test and fixed here: `PostgresTaskLog.write` sent a
  boolean to an integer column, and `PostgresReviewQueue.get_stats` compared a text deadline to a timestamp.

### B2b as built (artifacts, memory, repositories, grants, GitHub, `org-create`)

- **Artifacts.** Migration `0009_artifact_scope` backfills `artifact_versions.organization_id` to `default` and
  makes it NOT NULL. The identity key of a non-default organization is `org:<id>::<root>::<file>`, so equal paths
  in two organizations never share a version history (keys for `default` are unchanged). `list_files` requires
  `organization_id`; `history`, `get_version`, `latest_version_number` and `diff` also filter on it. The routes
  **no longer accept `organization_id` from the query string or body** (it was client-controlled); it comes from
  the principal. The completion publisher and Andromeda's direct path record artifacts under the task's
  organization.
- **Memory (Nebula).** `memories.organization_id` (added on open, existing rows in `default`). `recall`, `list`,
  `namespaces` and `forget` require `organization_id`; the prompt builder passes the task's. Approved skill
  lessons are written under the approving user's organization, so a tenant only gets lessons its own reviewers
  approved; the shared `default` lessons are not injected into other organizations.
- **Policy grants.** `policy_grants.organization_id`; `consume` only matches a grant issued in the same
  organization as the held task.
- **Repositories.** The table is rebuilt on open (its UNIQUE key had to gain the organization), existing rows
  land in `default`. `get` and `resolve_base` require `organization_id`. **A repository belongs to one
  organization**: registering a provider/owner/name that another organization holds is refused (422), and a
  goal cannot bind another organization's repository.
- **GitHub (decision for the open question).** An installation is access to repositories, not a tenant:
  there is no separate installation binding. `POST /github/pull-request` and `/github/check-run` need the
  repository registered to the caller's organization (another organization's, or an unregistered one, is 404);
  unregistered repositories stay usable by `default` so single-organization deployments are unchanged.
  `GET /github/installations*` list every repository an installation can reach, so they are `default` only
  (403 otherwise).
- **A2A gateway.** Unchanged: inbound A2A tasks run in the `default` organization and a caller can only see
  jobs with its own origin. Mapping a caller token to an organization is a one-line config change when needed.
- **Review-resume path.** Keeps its single unscoped goal lookup: the review item was already authorised for the
  caller's organization and carries a goal of the same organization.
- **`org-create`.** `galaxz admin org-create <id> [--name]`, `org-list`, and `user-create --organization`
  (the organization must exist). Ids are `[a-z0-9-]{2,63}` because they end up inside storage keys.
  This is the first point at which a second organization can exist.
- Not scoped on purpose: evidence ids in `POST /github/pull-request` (`goal_id`, `task_ids`) are only echoed
  into the PR body.

### Risks to review

- Nebula recall and policy grants are the two places a leak turns into prompt content or authority, so they
  are in B2 with their own cross-tenant tests.
- GitHub App installations are shared and repositories are owned by one organization (see "B2b as built");
  revisit if an installation must be restricted to a tenant before a hosted launch.
- Application-layer filtering depends on every query remembering the filter; the required-keyword
  signature and the route-walk test are the guard, not RLS.

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
  (the full training dataset) is `admin`. `POST /forge/agent|skill` is `admin` too: the scaffolder writes Python
  source under `agents/`, which the platform imports, so it is code installation like `/catalog/{id}/install`.
  Judgment-call rows to review: forge (admin), `/artifacts/rollback` (operator), `/orion/training/run`
  (operator), `/orion/export` (admin), FastAPI docs routes (admin).
- **`reviewed_by`:** the review-queue endpoints (`approve`/`accept`/`reject`) never recorded a reviewer, so
  attribution for them comes from the audit log (principal and task id in the path). The fine-tune and
  lesson approval endpoints now record the authenticated user (`user:<email>`) instead of the body field;
  the body field is still honored for the legacy API key.
- **Storage:** Alembic `0006_accounts` (seeds the `default` organization). Local mode uses SQLite
  (`GALAXZ_ACCOUNTS_DB`); a PostgreSQL `GALAXZ_DATABASE_URL` is used when set. Verified against a real
  PostgreSQL 16.

## Not yet done
- Phase B3 (Orion stores: fine-tune candidates, lessons, scorecards) and C (quotas).
- Prism has no login: it authenticates with the deployment's `GALAXZ_API_KEY`, so all its users act as that
  key's administrator. The OIDC spec is what fixes this.
- Rate limiting on failed token attempts.
- The pre-existing exempt reads (`GET /review/queue`, `/tasks/recent`, `/status`, `/agents`) still return task
  payloads and outputs without credentials. Out of scope here; worth closing in a follow-up.
- The credential check runs on a worker thread (blocking database I/O stays off the event loop).
