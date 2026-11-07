# Secret references — design

Date: 2026-11-07. Status: approved by the maintainer ("spec it out and then implement it").
Wires the existing `core/secrets/` library into task execution.

## Intent

`core/secrets/` (Fernet-encrypted, scope-bound `SecretStore`, `redact_secrets`) exists but
nothing in the runtime calls it. Tools that need credentials (a GitHub token for a Quasar MCP
tool, an API key for a remote service) have no safe way to receive them: putting the value in a
goal's objective or a task payload writes it, in plaintext, to the goal store, the task log, the
job tables, the review queue and artifacts.

A task payload may instead carry a **reference**; Galaxz swaps in the real value only for the
duration of the tool call, and removes it from everything that comes back.

## Goals

- A payload string `${{ secrets.<secret_id> }}` resolves to the stored value at execution time.
- Plaintext secrets never reach any persisted store: goals, planned tasks (`resolved_payload_json`),
  jobs, task log, review queue, policy digest, artifacts, results, error messages.
- A secret is usable only by the (organization, repository, skill) it was created for.
- Operators create secrets from the CLI, with the value read from stdin or a prompt.
- No secret configured and no reference in the payload ⇒ behaviour is byte-for-byte unchanged and
  no key is required.

## Non-goals

- No HTTP API to create, list or read secrets (no new network surface carrying secret values).
- No secret rotation, expiry, listing, or deletion UI. Overwrite = create a new secret and update
  the reference.
- No PostgreSQL backend: the store stays SQLite (`GALAXZ_SECRETS_DB`).
- No multi-tenancy. `organization_id` is a single configured value until accounts/orgs exist.
- No interpolation inside larger strings (`"Bearer ${{ secrets.x }}"` is not supported); a
  reference must be the whole string value.

## Anti-goals (would make this a failure even if it "works")

- A secret value appears in the task log, job output, review queue, artifact or an error string.
- A secret is sent to an LLM (Rigel/Vega/YAML prompt skills would embed it in a prompt and echo
  it into generated files).
- Resolution succeeds across scopes (another repository, another skill).

## Design

### Reference syntax and where it resolves

`${{ secrets.<secret_id> }}` as the entire value of any string inside a task payload (nested
dicts/lists are walked). It is deliberately a sibling of the existing
`${{ dependencies.<id>.result }}` syntax; `core/goals/substitution.py` does not match it and passes
it through untouched, so the reference is what gets persisted.

Resolution happens at exactly one place: `Andromeda._execute_node`, immediately before
`agent.run(skill_id, payload, context)`. Everything before that point (planning, `task_log.write`,
`payload_digest` for the policy gate, review queue, `resolved_payload_json`, job enqueue) only ever
sees the reference. The resolved payload exists only as a local variable for the duration of the call.

### Which skills may receive secrets

Only tool-executing skills: skill ids starting with `quasar.` (MCP tools). A reference in a payload
for any other skill fails the task with `failure_reason = "secret_not_permitted_for_skill"` and the
secret is not decrypted. Rationale: prompt-driven skills would put the value into an LLM prompt and
into generated artifacts. (Constant `SECRET_SKILL_PREFIXES` in `core/secrets/resolver.py`.)

### Scope

`SecretScope(organization_id, repository_id, task_id, policy)` is reused unchanged in shape.

| Field | Value at runtime | Value when creating via CLI |
|---|---|---|
| `organization_id` | `GALAXZ_ORGANIZATION_ID`, default `default` | same env |
| `repository_id` | the goal's bound repository (`goal_store.repository_binding`), else `default` | `--repository`, default `default` |
| `policy` | the skill id being executed | `--skill` (required) |
| `task_id` | the task's id | `--task`, default `*` |

Store change: a stored `task_id` of `*` matches any task id (planned task ids are unknown when an
operator creates the secret, which is why exact task binding alone is unusable for goals). The other
three fields still require exact equality. Mismatch ⇒ `PermissionError`, as today.

### Failure behaviour

All failures stop the task before the tool runs and carry a fixed `failure_reason`, never the exception text. Like any failed tool call, Andromeda escalates the task to the review queue:

| Condition | `failure_reason` |
|---|---|
| reference in a non-permitted skill | `secret_not_permitted_for_skill` |
| `GALAXZ_SECRETS_KEY` unset/invalid, or store unreadable | `secret_store_unavailable` |
| unknown id or scope mismatch | `secret_reference_unavailable` |

### Redaction

The resolver records every value it substituted. After `agent.run` returns (or raises), every string
in the result (recursively, dict keys excluded) and in any error text has those values replaced by
`[REDACTED]` using the existing `redact_secrets`, before the result becomes graph state and is
logged. Exceptions raised by the tool are redacted before `failure_reason = str(e)` is built.

### Creating secrets

`galaxz secret put --skill quasar.github.create_issue [--repository R] [--task T]` reads the value
from stdin if piped, else prompts with hidden input (never from argv, which lands in shell history).
Prints the reference string `${{ secrets.<id> }}` to use in payloads. Requires `GALAXZ_SECRETS_KEY`
(a Fernet key; generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).

### Store hardening required for use in the worker

`SecretStore` opens one sqlite connection in `__init__`; the worker calls it from multiple threads.
Open it with `check_same_thread=False` and serialize access with a lock.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GALAXZ_SECRETS_KEY` | unset | Fernet key; required only when a secret is created or resolved |
| `GALAXZ_SECRETS_DB` | `data/secrets.db` | SQLite file |
| `GALAXZ_ORGANIZATION_ID` | `default` | organization scope value |

## Known residual risk

A tool or dependency result could contain the literal text `${{ secrets.<id> }}` and be substituted
into a downstream task's payload. It would resolve only if that downstream task is a `quasar.*`
skill in the same organization and repository **and** matches the skill the secret was created for,
so the blast radius is the skill the operator already authorised. Accepted; mitigated by the
skill-bound scope.

## What is left to the builder

Module layout beyond `core/secrets/resolver.py`, exact CLI help text, and test structure.
