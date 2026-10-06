# Galaxz Release Notes

## Unreleased — Skill lessons

A cheap, human-gated learning loop that works today, instead of waiting on fine-tuning. Nothing happens until someone proposes and approves a lesson. Design: [`docs/specs/2026-10-05-skill-lessons-design.md`](docs/specs/2026-10-05-skill-lessons-design.md).

| System | What it does |
|--------|--------------|
| **Lessons** (Orion → Nebula) | `POST /lessons/propose` distils short guidelines from Orion events that carry a `human_correction` (3+ unused corrections per agent and skill; one LLM call per group, corrections quoted as data, lessons capped at 300 characters). Results are pending `LessonCandidate`s in `lessons.db` beside Orion's events DB. `GET /lessons?status=`, `POST /lessons/{id}/approve` (optional edited `content`) and `/reject`. Approval writes a Nebula memory in `skill:<skill_id>` (tags `lesson`, `agent:<id>`); `Andromeda.route()` always passes the newest 3 for the routed skill in `context["memory"]`. Revoke with `DELETE /memory/{id}`. No new core contract. |

### Known limitations

- Only Rigel code generation renders `context["memory"]` today, so only that skill benefits so far.
- Quality depends on the LLM and on corrections existing; nothing measures automatically that a lesson helped (signed scorecards can show success rate before and after).
- Proposals are manual (no background job); a group with more than 8 unused corrections is drained over several calls.

## Unreleased — Signed Orion scorecards

Verifiable evidence of how an agent performs, from the one data source an agent cannot fake. Off until you configure a signing key. Design: [`docs/specs/2026-10-05-signed-scorecards-design.md`](docs/specs/2026-10-05-signed-scorecards-design.md).

| System | What it does |
|--------|--------------|
| **Scorecards** (Orion) | Per `(agent, skill)` metrics from Orion's events over the last `days` (default 30): tasks, success rate with a Wilson 95% interval, partial/fail rates, average confidence, human-verified rate, p50/p95 latency, and `sample.sufficient` (>= 20 tasks). Signed with Ed25519 as a detached payload, so verifying needs no canonicalization rules. `GET /scorecards`, `GET /scorecards/{skill_id}`, `GET /scorecards/key`; CLI `galaxz scorecard keygen\|verify`. Key via `GALAXZ_SCORECARD_KEY_PATH` (or `GALAXZ_SCORECARD_KEY`); `GALAXZ_SCORECARD_ISSUER` names the issuer. No new contract or dependency. |

### Known limitations

- It proves that *this operator* attests to these numbers, not that they are good; value comes from the issuer's reputation. Anyone can run their own Galaxz.
- Metrics are only as honest as the feedback that produced them (`human_verified_rate` shows how much a person checked).
- No revocation, key rotation or transparency log; endpoints stay behind `GALAXZ_API_KEY`; scorecards are not yet embedded in Agent Cards or the catalog.

## Unreleased — Pre-action authorization

A policy gate that runs before any agent: deny a skill outright, or hold it for human approval. Empty by default, so behavior is unchanged until `config/policy.yaml` has rules. Design: [`docs/specs/2026-10-05-pre-action-policy-design.md`](docs/specs/2026-10-05-pre-action-policy-design.md).

| System | What it does |
|--------|--------------|
| **Policy gate** | First node of Andromeda's routing graph. Ordered rules match a skill glob and an origin glob; first match wins. `deny` → `no_agent_found` with `failure_reason="policy_denied"` (A2A callers see `TASK_STATE_REJECTED`). `require_review` → escalated into the review queue with a `policy_hold` record; approving or accepting it issues a single-use, one-hour grant (SQLite, `POLICY_DB_PATH`, default `data/policy.db`, created lazily) for that exact origin + skill + payload, and goal tasks are rerun automatically. No new contract. |

### Known limitations

- Evaluated by Andromeda only; conditions other than skill and origin (payload contents, rate, time) are not supported.
- A grant authorises a resubmission, it does not execute the held task by itself.
- The policy file is read at boot (restart to change it) and fails closed: a malformed file stops startup.
- Grants are single-node SQLite, like Nebula.

## Unreleased — Wormhole (A2A gateway)

Galaxz now speaks Google's [A2A](https://a2a-protocol.org) (Agent2Agent) v1.0 protocol, in both directions, without bypassing the contracts. Off or empty by default. Design: [`docs/specs/2026-10-05-wormhole-a2a-gateway-design.md`](docs/specs/2026-10-05-wormhole-a2a-gateway-design.md).

| System | What it does |
|--------|--------------|
| **Wormhole** — A2A gateway | *Inbound:* serves an Agent Card at `/.well-known/agent-card.json` (open skills publicly, the caller's permitted skills via `GetExtendedAgentCard`) and accepts `SendMessage`, `SendStreamingMessage` (SSE), `GetTask` and `CancelTask` at `POST /a2a`. Each caller has a bearer token (`token_env` in `config/a2a.yaml`) that fixes its `origin` (`a2a:*`), so `allowed_origins` is real enforcement here; tasks are ordinary `TaskContract`s on the durable job queue. Job states map to A2A states (`complete` → `COMPLETED`, escalated → `INPUT_REQUIRED`, origin denied → `REJECTED`). *Outbound:* each skill of each remote agent becomes a Pulsar skill `wormhole.<agent>.<skill>` with binary confidence (`1.0` / `0.0`), so a remote agent is never silently retried. `GET /wormhole` reports remote agents. |

New configuration: `config/a2a.yaml` (`callers`, `agents`), `A2A_PUBLIC_URL` (Agent Card URL behind a proxy), and one `token_env` variable per caller or remote agent.

### Known limitations

- **A2A v1.0 only**, JSON-RPC over HTTPS plus SSE. No gRPC/REST bindings, push notifications, `ListTasks`, `SubscribeToTask`, multi-tenancy or A2A 0.3.
- **Auth is per-caller bearer tokens**, not OAuth or user accounts. Agent Cards are not signature-verified: list only remote agents you trust, since their output is routed into Galaxz.
- Inbound tasks need the `worker` service; without it they stay `SUBMITTED`.
- Remote skills are discovered at boot. `wormhole.*` skills are never re-published on Galaxz's own card.
- Remote agents receive a text part plus a data part `{"skill", "payload"}`; an agent that only reads text parts sees the joined string values of the payload.

---

## v1.1.0 — Memory, tools, catalog and access control

Four platform capabilities — agent memory, MCP tool support, a local agent catalog and per-skill access control — built on Galaxz's own contracts. Every one is additive and off or empty by default, so a v1.0 deployment behaves the same until you use them. Design notes live in [`docs/specs/`](docs/specs/).

### Added

| System | What it does |
|--------|--------------|
| **Nebula** — agent memory | Durable notes scoped by namespace (a task's `origin`, or `global`). `Andromeda.route()` recalls the best keyword matches for the task into `context["memory"]`, and Rigel code generation includes them in its prompt. Contract: `MemoryEntry`. Store: SQLite at `NEBULA_DB_PATH` (default `data/nebula.db`). API: `POST /memory`, `GET /memory?namespace=a,b&q=…`, `GET /memory/namespaces`, `DELETE /memory/{id}`. |
| **Quasar** — MCP tool manager | A minimal stdio [MCP](https://modelcontextprotocol.io) client. Each tool of each server listed in `config/mcp.yaml` becomes a normal Pulsar skill, `quasar.<server>.<tool>`, so tool calls are routed, logged and access-controlled like any other task. Confidence is only ever `1.0` (success) or `0.0` (tool error), so the router never silently retries a tool with side effects. `GET /quasar` reports server status. Ships with `servers: []`. |
| **Constellation** — agent catalog | A local catalog of installable declarative agents: `catalog/<agent_id>/<version>/agent.yaml`. Install copies a validated package into `config/agents/` (restart to load). Rejects reserved built-in ids (`rigel`, `vega`, …), id/version mismatches and skill ids outside the agent's namespace, and never overwrites a different existing file without `force`. CLI: `galaxz catalog list\|install`. API: `GET /catalog`, `POST /catalog/{id}/install`. Ships with one example, `summarizer`. |
| **Skill access control** | `SkillDefinition.allowed_origins` (optional `fnmatch` patterns matched against `TaskContract.origin`; absent = open, `[]` = nobody). Pulsar filters candidate agents by origin, and a task with no permitted agent returns `no_agent_found` with `failure_reason="origin_not_allowed"`. Existing manifests are unaffected. |
| **Prism pages** | **Memory** (browse, search, add, delete), **Agents & Tools** (every skill with its allowed origins, plus MCP server status and tools) and **Catalog** (install agents). |

New configuration: `NEBULA_DB_PATH` (also set in `docker-compose.yml`), `config/mcp.yaml`, and `GALAXZ_CATALOG_DIR` / `GALAXZ_AGENTS_DIR` to relocate the catalog and the agent config directory.

### Fixed

- **Artifact safety scanner false positives.** The `generic-secret` rule flagged ordinary code such as `api_key = os.environ.get("API_KEY")`, which escalated legitimate Rigel output as `artifact safety review required: blocked`, while a hardcoded `SECRET_KEY = "…"` slipped through. It now flags hardcoded values only (quoted literals, or long digit-bearing unquoted values) and no longer flags lookups, calls or attribute reads. Escalations now name the rule and file (never the matched content). Scanner version bumped to `1.1`; the private-key and AWS-key rules are unchanged.
- **Plan review approve / accept / reject returned 500** after the item had been resolved and the goal started or failed, because the feedback event was built with the `plan:<goal_id>` queue key instead of a UUID. Retries then returned 409. Review items whose goal no longer exists can now be dismissed instead of raising `KeyError`.
- **Tests no longer write to `./data`.** An autouse fixture redirects the default databases to temp directories, so a test run can't leave stale rows in a dev service's review queue.
- **Stale Quasar tools.** Pulsar persists manifests, so tools from a previous `config/mcp.yaml` were still advertised after the servers were removed or failed. Quasar now removes its own manifest when it has no tools.

### Upgrade notes

- Rebuild the image (`docker compose up --build`) to pick up the new code. No database migration is needed: `allowed_origins` is stored in the existing JSON manifests and defaults to open.
- Agents installed from the catalog and MCP servers are loaded at boot, so restart after installing or editing `config/mcp.yaml`.
- Rigel prompts change only when matching memories exist; with an empty Nebula nothing is injected.

### Known limitations

- **Origin access control is policy, not authentication.** `origin` is a caller-supplied string; it becomes enforceable once per-agent or per-user auth lands (v2).
- **Quasar:** stdio transport only (no HTTP/SSE, OAuth, resources or prompts); tools are discovered at boot; MCP servers run with Galaxz's privileges, so list only servers you trust; tool arguments are validated by the server, not by Galaxz.
- **Nebula:** memory is written explicitly through the API or UI (tasks don't auto-remember results); recall is keyword overlap, not embeddings; namespaces are the only isolation (no per-tenant scoping); only Rigel code generation consumes memory so far.
- **Constellation:** local catalog only — no signatures, remote index or uninstall. A package is as trusted as any file you place in `config/agents/`.

---

## v1.0.0 — Initial Public Release

Galaxz is an open-source AI operating system for multi-agent orchestration. Like Linux for servers or Kubernetes for containers, it provides the coordination layer — routing, registry, learning, and observability — that makes AI agents composable, reliable, and improvable over time. Agents register their skills, Andromeda routes work to the right agent based on capability and load, every completed task emits a feedback event that Orion uses to refine future routing, and the whole platform runs behind a single `docker compose up`.

---

## What's in v1.0.0

| Component | Role |
|-----------|------|
| **Andromeda** | Orchestrator — routes tasks to capable agents via a LangGraph state machine, manages escalation and the human review queue |
| **Vega** | QA Agent — turns requirements into test cases, executes test runs, and produces structured bug reports |
| **Rigel** | Engineering Agent — generates code, writes tests, refactors, scaffolds projects, reviews pull requests, and triages debug traces. Includes an execution sandbox (`agents/rigel/execution.py`) that runs generated code in an isolated container with a configurable timeout, plus a workspace-anchored mode for writing output to a caller-specified path |
| **Orion** | Data Refinery — ingests feedback events from every completed task and produces fine-tuning datasets and routing heuristics |
| **Pulsar** | Agent Registry — maintains a live skill manifest for every registered agent so Andromeda can match tasks to capability |
| **Aether** | Message Bus — Redis Streams backbone that carries tasks, results, and feedback events between all components |
| **Prism** | Operator UI — React workspace for submitting tasks, reviewing escalations, approving fine-tune candidates, and inspecting agent health |
| **Forge** | Agent/Skill Scaffolding — `POST /forge/agent` and `POST /forge/skill` generate boilerplate for a new community agent or skill from `core/scaffolder.py`. (Previously mis-described here as an "execution sandbox" — that's actually Rigel's execution mode, listed under Rigel above.) |

---

## Quickstart

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose up --build -d
```

This starts Aether, Pulsar, Andromeda (with Vega/Rigel running in-process), and the
Prism operator UI in dependency order. Prism is served at http://localhost:5173 and
proxies API calls to Andromeda inside the Compose network.

To run Prism against a local (non-Docker) Andromeda instead, start it in dev mode:

```bash
cd prism && npm install && npm run dev   # http://localhost:5173, proxies to localhost:8001
```

---

## Documentation and Community

- [Documentation]
- [Community]

---

## Known Limitations

Galaxz v1.0 is designed for **local and trusted-network deployments only**.

- **Auth is opt-in and minimal.** By default (`GALAXZ_API_KEY` unset) the API accepts all requests without credentials. Setting `GALAXZ_API_KEY` requires a bearer token on most endpoints, but it's a single shared static key, not per-user auth. Either way, do not expose Galaxz to the public internet without a reverse proxy and a real auth layer in front of it.
- **No multi-tenancy.** All agents, tasks, and data share a single workspace. Isolation between users or projects is not implemented.
- **Single-node only.** The registry, message bus, and agent processes run on one host. Horizontal scaling is a post-v1 concern.

See [`docs/decisions/auth-boundary.md`](docs/decisions/auth-boundary.md) for the full rationale behind these constraints and the planned remediation path.

---

## What's Next

- **Goal and project hierarchy** — first-class project objects that group related tasks, track cumulative confidence, and surface progress in Prism

~~Artifact store~~ — shipped: `core/artifacts/store.py` records every produced artifact with versioned history; `Andromeda.route()` writes through it; exposed via `GET /artifacts`, `/artifacts/history`, `/artifacts/diff`, `POST /artifacts/rollback` and the Prism **Artifacts** page (diff + rollback).

~~Workspace path feature~~ — shipped: `TaskContract.output_path` is threaded through `Andromeda.route()` into task context and consumed by Rigel (`agents/rigel/agent.py`) to override the inferred output filename. See `workspace/`, `test/workspace/`, and the workspace-related tests in `test/api/test_andromeda_api.py`.
