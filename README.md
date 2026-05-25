# galaxz

**The open AI agent operating system.**

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Build](https://img.shields.io/badge/build-passing-brightgreen)

> **Demo:** [Watch the walkthrough →](https://youtu.be/PLACEHOLDER)

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
docker compose exec galaxz python -m galaxz.cli route \
  --skill rigel.skill.code_generation \
  --payload '{"spec": "validate email address", "language": "python"}'
```

Expected output: `task_id`, `assigned_agent: rigel`, `status: complete`, `confidence: ~0.84`

---

## Configuration

Set `GALAXZ_API_KEY` in `.env` to secure your deployment. Omit it for local development.

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

---

## Project structure

```
.
├── agents/
│   ├── andromeda/       # Orchestrator / routing graph
│   ├── rigel/           # Engineering agent
│   └── vega/            # QA agent (analyzer → test designer → bug reporter)
├── cli/                 # CLI entrypoint
├── config/
│   └── providers.yaml   # LLM provider config (model, key, base URL)
├── core/
│   ├── aether/          # Redis Streams client
│   ├── contracts/       # Task, Skill, and Refinery contract schemas
│   ├── llm/             # Provider abstraction (litellm)
│   └── pulsar/          # Agent skill registry
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
