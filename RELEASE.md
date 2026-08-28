# Galaxz v1.0.0 — Initial Public Release

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

This starts Aether, Pulsar, and Andromeda (with Vega/Rigel running in-process) in dependency order.

**Prism is not yet part of `docker-compose.yml`** — there's no Dockerfile for it and its dev-server
proxy is hardcoded to `localhost:8001`, so it needs to run outside Compose for now:

```bash
cd prism && npm install && npm run dev   # http://localhost:5173
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
- **Artifact store** — persistent, queryable storage for all generated code, reports, and test suites with diff and rollback support

~~Workspace path feature~~ — shipped: `TaskContract.output_path` is threaded through `Andromeda.route()` into task context and consumed by Rigel (`agents/rigel/agent.py`) to override the inferred output filename. See `workspace/`, `test/workspace/`, and the workspace-related tests in `test/api/test_andromeda_api.py`.
