# Wormhole (A2A gateway) — Design

Date: 2026-10-05

## Problem
Galaxz agents and skills are reachable only through Galaxz's own HTTP API, and
Galaxz cannot call agents built elsewhere. [A2A](https://a2a-protocol.org)
(Agent2Agent, v1.0, Linux Foundation) is the open protocol for agent-to-agent
interoperability. Wormhole speaks A2A in both directions without bypassing the
contracts: every inbound A2A request becomes a routed `TaskContract`, and every
remote A2A skill becomes a normal Pulsar skill.

## Scope
Protocol: A2A **v1.0 only**, JSON-RPC 2.0 over HTTPS plus SSE streaming.
Methods: `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`,
`GetExtendedAgentCard`. Both directions are off or empty by default, so a v1.1
deployment behaves the same until configured.

No new contract. Wormhole adds `core/a2a/` and reuses `TaskContract`,
`SkillManifest`/`SkillDefinition` (including `allowed_origins`) and the jobs queue.

Out of scope for v1: gRPC and REST bindings, push notifications, signed Agent Card
verification (JWS), A2A 0.3 compatibility, multi-tenancy (`tenant` field),
`ListTasks`, `SubscribeToTask`.

## Verified against the v1.0 spec
Method names are PascalCase. Enums are `TASK_STATE_*` and `ROLE_*`. A `Part` is one
unified type discriminated by member presence (`text`, `data`, ...), with no `kind`
field. Requests carry an `A2A-Version` header (`VersionNotSupportedError` if
unsupported). The extended card is advertised by `capabilities.extendedAgentCard`.
The card is served at `/.well-known/agent-card.json`. **Re-check field names against
the spec at implementation time**; this design was written from the spec's prose
pages, not the schema files.

## Configuration: `config/a2a.yaml`
Ships as `callers: []` and `agents: []`.

```yaml
callers:                       # inbound
  - token_env: A2A_PARTNER_X_TOKEN   # bearer token read from the environment
    origin: "a2a:partner-x"          # fixed, must start with "a2a:"; the caller cannot choose it
    skills: ["rigel.skill.*"]        # optional fnmatch allow-list on top of allowed_origins
agents:                        # outbound
  - name: translator
    url: https://agents.example.com   # card base URL
    token_env: TRANSLATOR_TOKEN       # optional
    timeout_s: 60
    allowed_origins: ["goal:*"]       # local policy for this remote agent's skills
```

A caller `origin` must start with `a2a:` so a caller can never impersonate internal
origins such as `goal:*`. Tokens are never stored inline in the file. A caller whose `token_env` is unset is
ignored with a warning.

## Inbound

### Auth
`ApiKeyMiddleware` returns 401 for `/a2a` whenever `GALAXZ_API_KEY` is set, so
`GET /.well-known/agent-card.json` and `POST /a2a` get explicit entries in its exempt
list (as `/github/webhook` has). The A2A handler then authenticates the bearer token
itself and resolves it to a configured caller. The token sets `TaskContract.origin`,
so `SkillDefinition.permits(origin)` is real enforcement on this entry point.
Missing or unknown token: HTTP 401, matching the card's `securitySchemes`. The
token comparison is constant-time.

### Agent Card
- `GET /.well-known/agent-card.json` (public): built from the Pulsar registry,
  listing only skills with `allowed_origins is None`. Declares
  `capabilities.streaming: true`, `extendedAgentCard: true`, no push notifications,
  and a bearer `securityScheme`.
- `GetExtendedAgentCard` (authenticated): the skills the caller's origin is permitted
  to use and that pass the caller's `skills` allow-list.
- Each card skill carries `id` (the Pulsar `skill_id`), `name`, `description`, `tags` and
  JSON input/output modes. The v1.0 `AgentSkill` message has no field for an input schema
  or confidence, so neither is published; callers learn payload shapes from the
  description. Skills of the `wormhole` agent are never published (no transitive
  re-export, no loops between two instances).

### Message to task
The caller names the skill in a data part: `{"skill": "<id>", "payload": {...}}`.
A missing or malformed data part returns a JSON-RPC invalid-params error; Wormhole
never guesses a skill with an LLM. `TaskContract.origin` comes from the token,
`confidence_threshold` from an optional `metadata.confidenceThreshold` (default
`0.65`). The task is enqueued on the existing jobs queue (`_jobs().enqueue`), so
`SendMessage` returns a Task immediately and `GetTask` reads job state and result.
`A2A-Version: 1.0` is required on every request. `messageId` is required and makes
`SendMessage` idempotent per origin. A skill outside the caller's `skills` allow-list
returns a Task in `TASK_STATE_REJECTED` that is not persisted (so `GetTask` on it is
`TaskNotFoundError`). `GetTask` and `CancelTask` only see jobs created by the same caller. The
A2A `Task.id` is the job id.

### State mapping

| Galaxz | A2A |
|--------|-----|
| job `queued` | `TASK_STATE_SUBMITTED` |
| job `running` | `TASK_STATE_WORKING` |
| job `completed`, task status `complete` | `TASK_STATE_COMPLETED` |
| job `completed`, task escalated to review | `TASK_STATE_INPUT_REQUIRED` |
| job `failed` | `TASK_STATE_FAILED` |
| job `cancelled` | `TASK_STATE_CANCELED` |
| origin not permitted for the skill (`no_agent_found`, `origin_not_allowed`) | `TASK_STATE_REJECTED` |

The result artifact carries the output as a data part and puts the confidence in the
artifact's metadata. `CancelTask` calls the same repository cancel as
`/jobs/{id}/cancel`; a job that is already terminal returns `TaskNotCancelableError`.

### Streaming
`SendStreamingMessage` returns SSE. The first event is the Task, then status updates
are emitted as the job state changes (polled from the repository, bounded by a stream
timeout), ending after the terminal state.

## Outbound

### Boot
`core/a2a/client.py` `A2AClient`: synchronous HTTP JSON-RPC client (`httpx`, already a
dependency) sending `A2A-Version: 1.0`. No new dependency: the official SDK is async
and Andromeda's agent interface is synchronous, the same reason Quasar hand-rolls MCP.

`core/a2a/agent.py` `WormholeAgent` (`AGENT_ID="wormhole"`): for each configured agent,
fetch `/.well-known/agent-card.json`, keep only a v1.0 JSON-RPC interface **on the same
scheme and host as the configured `url`** (the card is remote-controlled; this stops our
token being sent elsewhere). When the card advertises `capabilities.extendedAgentCard`
and a token is configured, the skills come from `GetExtendedAgentCard`, falling back to
the public card if the remote refuses, and register **one**
`SkillManifest` with one skill per remote skill, `wormhole.<agent>.<skill_id>`. A
remote agent that is unreachable, malformed or on another protocol version is logged
and skipped. With no skills, no manifest is registered, and a stale manifest from a
previous config is removed (the Quasar fix).

### Running a skill
`run(skill_id, payload, context)` sends `SendMessage` with a text part (the payload's
string values joined, when any) plus a data part `{"skill": <remote id>, "payload": ...}`,
then polls `GetTask` to a terminal state, bounded by `timeout_s`. On
timeout it calls `CancelTask` and raises (task `failed`).

| Remote state | confidence | Effect |
|--------------|-----------|--------|
| `COMPLETED` | 1.0 | success; result data parts become the output |
| `FAILED`, `REJECTED`, `CANCELED` | 0.0 | escalated for review (below Andromeda's 0.40 failure threshold) |
| `INPUT_REQUIRED`, `AUTH_REQUIRED` | 0.0 | escalated for review |

Confidence is binary on purpose. Andromeda's retry rule only retries at confidence
>= 0.60 and below the threshold, so a remote agent that may have side effects is never
silently re-run.

## API (Andromeda service)
- `GET /.well-known/agent-card.json`, `POST /a2a` (inbound protocol).
- `GET /wormhole`: status of outbound agents (`ok`, `error`, skills), like `/quasar`.
- `boot()` loads `config/a2a.yaml` and adds `WormholeAgent` to Andromeda's agents.

## Errors
Protocol errors use JSON-RPC error codes carrying the A2A error names
(`TaskNotFoundError`, `TaskNotCancelableError`, `VersionNotSupportedError`,
`UnsupportedOperationError`). An unknown method is `UnsupportedOperationError`.
Wormhole never includes token values or upstream response bodies in logs or errors.

## Testing
- Card: public card hides restricted skills; extended card respects `permits` and the
  caller `skills` allow-list.
- Auth: no token and bad token give 401; `GALAXZ_API_KEY` set does not block `/a2a`;
  the caller cannot override `origin` from the message.
- Mapping: each row of the state table, incl. escalated to `INPUT_REQUIRED` and
  origin-denied to `REJECTED`; missing skill part returns invalid-params.
- Streaming ends after the terminal state; `CancelTask` on a terminal job errors.
- Outbound: manifest built from a fake card; down or v0.3 agents skipped; stale
  manifest removed; state table to confidence; timeout cancels remote.
- A fake A2A peer fixture (httpx `MockTransport`) so tests need no network.

## Limits
- Origin control is only as strong as the bearer tokens in `config/a2a.yaml`; this is
  per-caller identity, not user accounts or OAuth.
- Agent Cards are not signed or verified; outbound cards are trusted over TLS only.
  List only remote agents you trust: their output is routed into Galaxz.
- Inbound tasks need a running durable worker (`worker` service). Without one they
  stay `SUBMITTED`.
- Skills are discovered at boot; changing a remote agent's skills needs a restart.
- v1.0 peers only; many deployed agents still speak 0.3.
