# Audit logging — design

Date: 2026-11-07. Status: approved by the maintainer ("spec them out and start implementing them").
First of the v2 identity/governance items; see `2026-11-07-v2-identity-governance-overview.md`.

## Problem
`core/security/audit.py` provides an append-only, hash-chained `AuditLog`, with tests, but nothing in
the runtime writes to it. Security-relevant decisions leave no durable trace: a policy denial is only a
WARNING log line (the pre-action policy spec defers this explicitly: "audit integration is left for
v2"), secret use is invisible, and nobody can tell who called a mutating endpoint or that a request was
rejected. The library is also not safe to use as-is: one sqlite connection bound to its creating
thread, and a read-then-insert append that two processes (API and worker) can race, forking the chain.

## Goals
- Every state-changing API request, and every rejected request, leaves a tamper-evident record.
- Policy denials/holds, secret creation and secret use are recorded.
- The chain can be read and verified through the API and the CLI.
- Safe under the worker's threads and two writer processes sharing one database file.

## Non-goals
- No request or response bodies, query strings, headers or secret values in any event.
- No PostgreSQL backend in this change (SQLite file on the shared volume, like the job store); a
  Postgres table is a follow-up inside the accounts work.
- No external anchoring: the chain proves *modification or removal of an earlier record*; it cannot
  prove that the newest records were not truncated.
- No retention/rotation policy yet.
- No per-user attribution beyond today's principals (the accounts spec adds real users).

## Anti-goals
An audit failure must not take the platform down, and an event must never contain a credential.

## Design

### Hardening `AuditLog`
Open the connection with `check_same_thread=False` and `isolation_level=None`; guard it with a lock;
perform each append as `BEGIN IMMEDIATE` → read the head hash → insert → `COMMIT`, with a 30 s busy
timeout, so concurrent writers serialise instead of forking the chain. `evidence_version` gets the
default `"audit-v1"`. Add `export(after=0, limit=None)` for paging and `verify_chain()` which streams
the stored chain and returns `{"valid": bool, "events": n, "head": hash|None, "broken_at": seq|None}`.
The existing static `verify(events)` and the event shape are unchanged.

### One recording helper
`audit_event(actor, action, reason, **extra)` in `core/security/audit.py` writes to the default log
(`GALAXZ_AUDIT_DB`, default `data/audit.db`, one cached instance per path). **Best effort:** any
exception is caught and logged at ERROR with the action name, and the caller continues. Rationale: an
audit-store outage must not stop reviewers approving work or operators cancelling a runaway goal. The
cost is that events can be missed during an outage; the ERROR log is the signal. Strict mode can be
added later if a deployment needs fail-closed.

### What is recorded (v1)
| Source | action | actor | reason | extra |
|---|---|---|---|---|
| HTTP middleware, any POST/PUT/PATCH/DELETE | `http.<method>` | principal id | `allowed` or `denied` | `path`, `status`, `principal_kind` |
| HTTP middleware, any request answered 401/403 | `http.<method>` | `unauthenticated` | `denied` | `path`, `status` |
| Policy gate | `policy.deny` / `policy.hold` | task origin | rule reason | `skill`, `rule_index` |
| Secret resolution (**follow-up**, needs PR #23) | `secret.resolve` | task origin | `resolved` or the failure code | `skill`, `task_id`, `repository_id`, `count` |
| `galaxz secret put` (**follow-up**, needs PR #23) | `secret.put` | `cli` | `created` | `secret_id`, `skill`, `repository`, `task`, `organization_id` |

Paths are recorded without the query string. A path can contain ids (goal, task) which is the point.

### Principal on the request
`ApiKeyMiddleware` sets `request.state.principal` to `{"id", "kind"}`: `api-key` (valid key),
`anonymous` (auth disabled), `exempt-route` (self-authenticating routes), or `unauthenticated`
(rejected). The audit middleware is outermost, so it also sees the 401s. This is the seam the
accounts work replaces with real users.

The two secret rows are specified here so the event vocabulary is complete, but secret references
(`docs/specs/2026-11-07-secret-references-design.md`) are not on `main` at the time of this change; they
are added in a follow-up PR once it merges. Values are never recorded, only references and counts.

### Reading
`GET /audit/events?after=<sequence>&limit=<1..1000>` and `GET /audit/verify`; both require the API
key (not in the exempt list). CLI: `galaxz audit verify` prints the verification result and exits 1 if
the chain is broken.

### Configuration
`GALAXZ_AUDIT_DB` (compose points `galaxz` and `worker` at the shared `job-data` volume).

## Left to the builder
Module layout of the middleware, exact response field names beyond those above, test structure.
