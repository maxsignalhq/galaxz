# Galaxz v1.0.0 — Initial Public Release

Galaxz is an open-source AI operating system for multi-agent orchestration. Like Linux for servers or Kubernetes for containers, it provides the coordination layer — routing, registry, learning, and observability — that makes AI agents composable, reliable, and improvable over time. Agents register their skills, Andromeda routes work to the right agent based on capability and load, every completed task emits a feedback event that Orion uses to refine future routing, and the whole platform runs behind a single `docker compose up`.

---

## What's in v1.0.0

| Component | Role |
|-----------|------|
| **Andromeda** | Orchestrator — routes tasks to capable agents via a LangGraph state machine, manages escalation and the human review queue |
| **Vega** | QA Agent — turns requirements into test cases, executes test runs, and produces structured bug reports |
| **Rigel** | Engineering Agent — generates code, writes tests, refactors, scaffolds projects, reviews pull requests, and triages debug traces |
| **Orion** | Data Refinery — ingests feedback events from every completed task and produces fine-tuning datasets and routing heuristics |
| **Pulsar** | Agent Registry — maintains a live skill manifest for every registered agent so Andromeda can match tasks to capability |
| **Aether** | Message Bus — Redis Streams backbone that carries tasks, results, and feedback events between all components |
| **Prism** | Operator UI — React workspace for submitting tasks, reviewing escalations, approving fine-tune candidates, and inspecting agent health |
| **Forge** | Execution Sandbox — isolated container environment for running Rigel-generated code with configurable timeout and workspace-anchored mode |

---

## Quickstart

```bash
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose up --build -d
```

All services start in dependency order. Once healthy, open the Prism UI at `http://localhost:5173`.

---

## Documentation and Community

- [Documentation]
- [Community]

---

## Known Limitations

Galaxz v1.0 is designed for **local and trusted-network deployments only**.

- **No authentication.** The API accepts all requests without credentials. Do not expose Galaxz to the public internet without a reverse proxy and auth layer in front of it.
- **No multi-tenancy.** All agents, tasks, and data share a single workspace. Isolation between users or projects is not implemented.
- **Single-node only.** The registry, message bus, and agent processes run on one host. Horizontal scaling is a post-v1 concern.

See [`docs/decisions/auth-boundary.md`](docs/decisions/auth-boundary.md) for the full rationale behind these constraints and the planned remediation path.

---

## What's Next

- **Workspace path feature** — per-task output path overrides so generated artifacts land exactly where the caller specifies
- **Goal and project hierarchy** — first-class project objects that group related tasks, track cumulative confidence, and surface progress in Prism
- **Artifact store** — persistent, queryable storage for all generated code, reports, and test suites with diff and rollback support
