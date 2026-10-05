# galaxz

**The open AI agent operating system.**

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Build](https://img.shields.io/badge/build-passing-brightgreen)

<video src="https://raw.githubusercontent.com/maxsignalhq/galaxz/main/docs/galaxz-ui-walkthrough.webm" controls width="100%"></video>

---

## What it is

Galaxz is an open-source platform that orchestrates specialized AI agents — Vega (QA), Rigel (Engineering), and community-built agents — through a shared intelligence layer called Andromeda. Every task is routed to the right agent via Pulsar's skill registry, executed over Aether (Redis Streams), and fed back into Orion's learning pipeline. The system improves with every task it runs.

---

## Quickstart

**Prerequisites:** Docker, Docker Compose, an API key for at least one LLM provider.

**Step 1 — Clone**
```bash
git clone https://github.com/[username]/galaxz.git
cd galaxz
```

**Step 2 — Configure**
```bash
cp .env.example .env
# Edit .env and add your LLM provider API key
```

**Step 3 — Boot**
```bash
docker compose up --build
```

By default, Galaxz runs in compact mode: the main `galaxz` service boots
Andromeda, Orion, Rigel, and Vega in one runtime to keep local and early-stage
deployments inexpensive.

Rigel and Vega still have standalone service wrappers for a future distributed
agent runtime. To start those optional agent containers explicitly:

```bash
docker compose --profile distributed-agents up --build
```

**Step 4 — Run your first task**
```bash
docker compose exec galaxz galaxz route \
  --skill rigel.skill.code_generation \
  --payload '{"spec": "validate email address", "language": "python"}'
```

Expected output: `task_id`, `assigned_agent: rigel`, `status: complete`, `confidence: ~0.84`

For durable execution, submit to the job API and poll the returned identifier:

```bash
curl -X POST http://localhost:8001/jobs \
  -H 'Content-Type: application/json' \
  -d '{"task":"validate email address","skill_id":"code_generation","idempotency_key":"example-1"}'
curl http://localhost:8001/jobs/JOB_ID
```

The separate `worker` service claims persisted jobs, renews leases, retries
classified transient failures, and prevents stale workers from overwriting a
completed result. The existing `/task` endpoint remains the synchronous
migration path. See [job storage operations](docs/operations/job-storage.md).

Goal DAGs also execute through durable jobs and survive API or worker restarts.
See [durable goal operations](docs/operations/durable-goals.md) and the
[result-substitution contract](docs/contracts/goal-result-substitution.md).

### Integration environment

Use the isolated integration stack for reproducible service-level checks. It
uses placeholder provider credentials, temporary container state, and dedicated
host ports, so it does not read or modify the developer stack's `.env` or data.
Run its standalone Compose file with the explicit project name shown below;
do not combine it with the development Compose file. Generated-code execution
is disabled in this stack: these checks cover routing, persistence, and recovery.
Sandbox behavior is covered by the execution tests.

```bash
docker compose --env-file /dev/null -p galaxz-integration -f docker-compose.integration.yml up --build --wait
curl --fail http://localhost:18001/health
curl --fail http://localhost:18003/health
curl --fail http://localhost:15173/api/health
docker compose --env-file /dev/null -p galaxz-integration -f docker-compose.integration.yml down --volumes
```

The checked-in Andromeda OpenAPI document is a regression contract. Intentional
HTTP API changes must include an explicit compatibility, versioning, or
migration decision before the contract is reviewed and exported:

```bash
.venv/bin/python -m scripts.export_openapi_contract
.venv/bin/pytest -q test/api/test_openapi_contract.py
```

To reproduce the complete production baseline from a clean checkout, run:

```bash
bash scripts/verify_production_baseline.sh
```

### Continuous integration

The required CI jobs can also be reproduced independently:

```bash
# Python
.venv/bin/python -m compileall -q agents cli core orion services test
.venv/bin/pytest -q test

# Prism
npm --prefix prism ci
npm --prefix prism run typecheck
npm --prefix prism run build

# Containers and HTTP smoke contract
docker compose --env-file /dev/null -p galaxz-integration -f docker-compose.integration.yml up --build --wait
.venv/bin/python test/integration/smoke_task.py
.venv/bin/python test/integration/crash_recovery.py
docker compose --env-file /dev/null -p galaxz-integration -f docker-compose.integration.yml down --volumes
```

---

## Configuration

Set `GALAXZ_API_KEY` in `.env` to secure your deployment. Omit it for local development.

| Variable / file | Purpose |
|-----------------|---------|
| `NEBULA_DB_PATH` | Where Nebula (agent memory) stores notes (default `data/nebula.db`) |
| `config/mcp.yaml` | MCP servers whose tools Quasar exposes as skills (empty by default) |
| `GALAXZ_CATALOG_DIR`, `GALAXZ_AGENTS_DIR` | Override the agent catalog (`catalog/`) and installed-agent (`config/agents/`) directories |

---

## System overview

| System    | Role                  | Status  |
|-----------|-----------------------|---------|
| Andromeda | Orchestrator / Router | ✅ Live |
| Vega      | QA Agent (3 stages)   | ✅ Live |
| Rigel     | Engineering Agent     | ✅ Live |
| Pulsar    | Skill Registry        | ✅ Live |
| Aether    | Message Bus (Redis)   | ✅ Live |
| Orion     | Data Refinery         | ✅ Live |
| Nebula        | Agent memory (notes recalled into tasks) | ✅ Live |
| Quasar        | MCP tool manager (tools as skills)       | ✅ Live |
| Constellation | Local catalog of installable agents      | ✅ Live |

### Memory, tools, catalog and access control

All four are additive and empty by default. In the Prism UI they are the **Memory**,
**Agents & Tools** and **Catalog** pages.

```bash
# Nebula — remember something; matching notes are added to later Rigel code-generation prompts
curl -X POST localhost:8001/memory -H "Authorization: Bearer $GALAXZ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"namespace":"global","content":"Parse config with yaml.safe_load","tags":["python"]}'

# Constellation — install an agent from catalog/ into config/agents/ (restart to load it)
python -m cli.run catalog list
python -m cli.run catalog install summarizer
```

- **Quasar:** list MCP servers in `config/mcp.yaml` (see the commented example) and restart.
  Each tool becomes a skill named `quasar.<server>.<tool>`; stdio servers only, and they run
  with Galaxz's privileges, so list only servers you trust.
- **Access control:** give a skill `allowed_origins` (for example `["goal:*"]`) in its manifest to
  limit which task origins may use it. A task with no permitted agent returns `no_agent_found`
  with `failure_reason="origin_not_allowed"`. This is policy, not authentication.

See [RELEASE.md](RELEASE.md) for details and limits, and [docs/specs/](docs/specs/) for the designs.

---

## Production roadmap

See [docs/phases.md](docs/phases.md) for the production-readiness phases, Jira
delivery sequence, current starting point, and continuation protocol for coding
agents.

---

## Project structure

```
.
├── agents/
│   ├── andromeda/       # Orchestrator / routing graph
│   ├── rigel/           # Engineering agent
│   └── vega/            # QA agent (analyzer → test designer → bug reporter)
├── catalog/             # Installable agent packages (Constellation)
├── cli/                 # CLI entrypoint
├── config/
│   ├── mcp.yaml         # MCP servers for Quasar (empty by default)
│   └── providers.yaml   # LLM provider config (model, key, base URL)
├── core/
│   ├── aether/          # Redis Streams client
│   ├── constellation/   # Agent catalog (list / install)
│   ├── contracts/       # Task, Skill, and Refinery contract schemas
│   ├── llm/             # Provider abstraction (litellm)
│   ├── nebula/          # Agent memory store
│   ├── pulsar/          # Agent skill registry
│   └── quasar/          # MCP client and tool-to-skill agent
├── docs/specs/          # Design notes for each capability
├── evals/               # Evaluation harness and datasets
├── orion/               # Data refinery (feedback ingestion, heuristics)
├── prism/               # Web UI (Vite / TypeScript)
├── services/            # Long-running service wrappers
├── test/                # Test suite
├── boot.py              # Ordered system startup
├── docker-compose.yml
└── requirements.txt
```

---

## Adding a community agent

1. Implement the `SkillContract` interface from `core/contracts/skill_contract.py`
2. Register your agent with Pulsar on init
3. Run it in-process for compact mode, or add an optional profiled service to
   `docker-compose.yml` when the distributed agent runtime is needed.

---

## Security

Galaxz v1 is designed for local and trusted-network deployment.
No authentication or multi-tenancy is implemented by default.

See [docs/decisions/auth-boundary.md](docs/decisions/auth-boundary.md)
for the full v1 auth boundary decision, trust boundary table, and v2
roadmap.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

Licensed under [MIT](LICENSE).
