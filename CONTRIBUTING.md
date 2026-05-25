# Contributing to Galaxz

Thank you for your interest in contributing. This guide covers everything you need to get a working development environment, understand the codebase, and submit changes.

---

## 1. Development setup

**Prerequisites**

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose v2
- Python 3.11 or later
- Redis 7 (included in the Compose stack — no separate install needed)
- An API key for your chosen LLM provider (Anthropic by default)

**Clone and start the stack**

```bash
git clone https://github.com/maxsignalhq/galaxz.git
cd galaxz
cp .env.example .env          # add your ANTHROPIC_API_KEY
docker compose up --build -d
```

**Verify everything is healthy**

```bash
curl http://localhost:8000/health   # Andromeda API
curl http://localhost:5173          # Prism UI
```

Both should respond without error. The Andromeda `/health` response includes per-component status for Pulsar, Aether, and the task log.

---

## 2. Project structure

```
agents/         Vega (QA) and Rigel (engineering) agent implementations
core/           Andromeda orchestrator, Pulsar registry, contracts, LLM provider, Aether client
orion/          Data refinery — ingests feedback events, produces fine-tuning datasets and routing heuristics
prism/          Operator UI (React + Vite) — task submission, review queue, dev console, settings
config/         YAML configuration for LLM providers, Rigel skills, workspace, routing weights
docs/           Architecture decision records (docs/decisions/) and design specs
test/           Python unit/integration tests (test/) and Playwright UI tests (test/UI/)
workspace/      FileWriter and workspace config loader used by Rigel for disk-write operations
services/       FastAPI service layer wrapping Andromeda for HTTP access
boot.py         Starts all components in the correct dependency order
```

---

## 3. Adding a new agent

**Recommended path — Forge**

Open the Prism UI and navigate to **Dev Console → Forge**. Forge scaffolds a new agent with the correct contract structure, registers it with Pulsar, and wires it to Aether. This is the fastest and least error-prone path.

**Manual path — for contributors who want to understand the contracts**

Every agent must:

1. **Register a `SkillManifest` with Pulsar on startup.** The manifest declares the agent's ID, name, version, skills (each as a `SkillDefinition` with `skill_id`, `input_schema`, `output_schema`, `avg_confidence`, and `avg_latency_ms`), and a health endpoint. See `agents/rigel/agent.py` (`_build_manifest`) or `agents/vega/agent.py` for reference implementations.

2. **Subscribe to Aether for incoming tasks.** Aether is a Redis Streams bus. Agents consume from `galaxz:tasks` and publish results back. The `AetherClient` in `core/aether/client.py` provides the publish interface; consumer patterns follow the same stream key.

3. **Return results in the Task Contract envelope.** Every agent `run()` method must return a dict with at minimum: `confidence` (float 0–1), `result` (dict), `artifacts` (list), `summary` (str), and `writable` (bool). See `core/contracts/contracts.py` for the full contract.

4. **Emit a `RefineryFeedbackEvent` to Aether after each task.** This feeds Orion and is required for the learning loop to function. See `agents/rigel/agent.py` (`_emit_feedback`) for the pattern.

---

## 4. Adding a new skill to an existing agent

**Recommended path — Forge**

In the Prism UI, go to **Dev Console → Forge**, select an existing agent, and use the skill scaffolder. Forge generates the handler, registers the skill in the agent's manifest, and updates `config/rigel.yaml` (or the equivalent config for other agents).

**Manual path**

1. Add a handler function in `agents/<agent>/skills/` following the existing skill pattern (see `agents/rigel/skills/code_generation.py`).
2. Register the handler in the agent's `SKILL_REGISTRY`.
3. Add the skill entry to the agent's `SKILLS` list and to the relevant config YAML under `config/`.
4. Update `_normalize_skill_output` (for Rigel) or the equivalent normalisation function to define what `artifacts`, `summary`, and `writable` look like for the new skill.
5. Add a structural check to `agents/rigel/confidence.py` (or equivalent) so the confidence scorer knows what a valid result looks like.

---

## 5. Commit conventions

Galaxz uses [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use for |
|--------|---------|
| `feat:` | New capability visible to users or callers |
| `fix:` | Bug fix |
| `chore:` | Maintenance — dependency updates, config, tooling |
| `docs:` | Documentation only |
| `test:` | Adding or updating tests with no production code change |
| `refactor:` | Code restructure with no behaviour change |

Keep the subject line under 72 characters. Add a body when the "why" is non-obvious.

---

## 6. Running tests

**Python tests**

```bash
docker compose exec galaxz python -m pytest test/ -q
```

**UI tests (Playwright)**

```bash
cd test/UI
npm install
npm test
```

The Playwright config starts the Prism Vite dev server automatically. Tests that hit `/api/task` require the full Compose stack to be running.

---

## 7. Architecture decisions

All significant design choices are documented as Architecture Decision Records in `docs/decisions/`. Read these before proposing changes that touch contracts, the message bus, the registry, or the auth boundary — many constraints that look arbitrary have explicit rationale recorded there.
