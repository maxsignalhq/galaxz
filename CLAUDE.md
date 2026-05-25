# CLAUDE.md — Galaxz Project

> **This file is the first thing you read. Every time. No exceptions.**
> Before writing a single line of code, answering a question, or making any architectural suggestion,
> read this file in full — then read the relevant files in `/memory/`.

---

## Standing instruction for every prompt

Before implementing anything, **always check if it is already implemented**:

1. Run targeted `grep` / `ls` / `cat` commands to confirm whether the described files,
   classes, or behaviours already exist.
2. If everything asked for is already present and correct, reply:
   **"Already implemented — [one sentence summary of what exists]. Nothing to do."**
   and stop immediately. Do not produce any further output.
3. If it is partially implemented, describe exactly what is missing, then implement
   only the missing parts.
4. If nothing exists yet, implement it.

**Token discipline:**
- Use targeted reads (`grep`, `ls`, line-range `Read`) before full file reads.
- Read only the files directly relevant to the current task.
- Do not summarise files you have already read back to the user.
- Stop as soon as the acceptance criteria are met — do not add unrequested cleanup,
  refactoring, or commentary.

---

## What Is Galaxz?

Galaxz is an **open-source AI operating system** built on multi-agent orchestration.

It is not a chatbot wrapper. It is not a prompt chain. It is an OS — a platform that coordinates
specialized AI agents, routes work intelligently, learns from every task it executes, and allows
third-party agents to plug in through open contracts.

The founding principle:
> **"The platform must never become the bottleneck. Every boundary is a contract. Every contract is published."**

This project began as "Holonet" (see `/memory/`) and evolved into Galaxz during the design phase.
All Holonet references in memory are canonical history — the same project, earlier name.

---

## Memory System

**Critical instruction:** This project maintains persistent context in the `/memory/` directory.
Each file captures decisions, architecture, and reasoning from prior conversations.

**Always read these files before starting any work:**

```
/memory/
├── brain.md              # Master architecture — the canonical source of truth
├── contracts.md          # The three core contracts (Task, Skill, Refinery Feedback)
├── systems.md            # All seven systems — names, roles, responsibilities
├── build-phases.md       # Phase 1–4 timeline and what was built in each
├── decisions.md          # Key architectural decisions and WHY they were made
└── open-questions.md     # Unresolved questions that need answers before proceeding
```

**If a `/memory/` file contradicts something you think you know — trust the file.**
These files were written with full context from prior conversations that may not be
visible in your current context window.

---

## The Seven Systems

| Name | Role | Color Ref | Status |
|------|------|-----------|--------|
| **Galaxz** | Platform / Container | `#c084fc` | Active |
| **Andromeda** | Orchestrator / Router | `#7dd3fc` | Phase 2 |
| **Vega** | QA Agent | `#34d399` | Phase 1 ✓ |
| **Rigel** | Engineering Agent | `#fbbf24` | Phase 2 |
| **Orion** | Data Refinery (learning loop) | `#f472b6` | Phase 3 |
| **Pulsar** | Agent Registry | `#a78bfa` | Phase 2 |
| **Aether** | Message Bus (Redis Streams) | `#60a5fa` | Phase 1 ✓ |

**Naming rationale:** Every system name is an astronomical object. This is intentional and permanent.
Do not suggest renaming systems. Do not introduce non-astronomical names for new systems.

---

## The Three Core Contracts

These contracts are the constitution of Galaxz. Every agent speaks these. Nothing bypasses them.

### 1. Task Contract
Every agent receives and returns this envelope:
```python
# Input
{
  "task_id": str,        # UUID
  "type": str,           # task category
  "payload": dict,       # the actual work
  "context": dict,       # prior conversation / history
  "priority": int,       # 1–5
  "origin_agent": str    # who sent this
}

# Output
{
  "task_id": str,
  "status": str,         # "complete" | "failed" | "escalate"
  "result": dict,
  "confidence": float,   # 0.0–1.0 — CRITICAL for routing decisions
  "artifacts": list,     # files, diffs, reports
  "next_actions": list   # suggested follow-on tasks
}
```

### 2. Skill Contract (Pulsar Registry)
Every agent registers this manifest with Pulsar on startup:
```python
{
  "agent_id": str,
  "domain": str,
  "skills": list[str],
  "input_schema": dict,
  "output_schema": dict,
  "cost_estimate": float,
  "avg_latency": float
}
```

### 3. Refinery Feedback Event (Orion)
Every completed task emits this event to Aether:
```python
{
  "task_id": str,
  "agent_id": str,
  "outcome": str,          # "success" | "failure" | "escalated"
  "human_verified": bool,
  "latency": float,
  "token_cost": float
}
```

**Rule:** No agent passes data to another agent outside these contracts. Ever.
If a new data shape is needed, a new contract is proposed and added here — not worked around.

---

## Architecture — How It All Fits

```
CLIENT REQUEST
     │
     ▼
 ANDROMEDA (orchestrator)
     │
     ├── queries PULSAR (registry) → finds capable agents
     │
     ├── routes via AETHER (Redis Streams message bus)
     │        │
     │        ├──► VEGA (QA)
     │        ├──► RIGEL (Engineering)
     │        └──► [future agents]
     │
     ├── receives results via AETHER
     │
     └── emits feedback event → AETHER → ORION (refinery)
                                              │
                                              └── fine-tuning datasets
                                                  routing heuristics
                                                  quality scores
```

**Startup boot order (mandatory):**
1. Aether (Redis) — must be live before anything else
2. Pulsar — agents cannot register until this is running
3. Agents (Vega, Rigel, etc.) — register with Pulsar on init
4. Orion — subscribes to Aether feedback channel
5. Andromeda — starts routing only after Pulsar confirms at least one agent registered

---

## Build Phases

### Phase 1 — Vega MVP ✓ (COMPLETE)
- Vega agent running end-to-end
- Aether (Redis Streams) live
- Task Contract v1 implemented
- Full QA workflow: Requirements → Test Cases → Bug Reports
- Multi-LLM support (user chooses their LLM provider)
- Output: `docker-compose up` boots Vega + Aether cleanly

### Phase 2 — Andromeda + Rigel + Pulsar (IN PROGRESS)
- Pulsar registry (SQLite-backed)
- Andromeda routing graph (LangGraph)
- Rigel engineering agent
- Two-agent collaboration working
- Output: `python galaxz/boot.py` routes tasks through Andromeda to Vega or Rigel

### Phase 3 — Orion + Aether Full Mesh (UPCOMING)
- Orion data refinery consuming all feedback events
- Full Redis Streams mesh between all agents
- Confidence scoring using historical data (not hardcoded)
- Fine-tuning dataset generation

### Phase 4 — Open Source Launch
- Community governance structure
- Agent certification marketplace
- Hosted platform + enterprise features
- Documentation site

---

## Technical Decisions (Do Not Relitigate Without Reading `/memory/decisions.md`)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Open source | Stronger strategic play — ecosystem leverage, network effects |
| Agent framework | LangGraph | Chosen over CrewAI and AutoGen for Phase 1/2 |
| Message bus | Redis Streams (Aether) | Async, resilient, battle-tested |
| Registry store | SQLite (Pulsar) | Simple for Phase 1–2, swap to Postgres at scale |
| LLM provider | User-selectable | Multi-LLM from day one — no vendor lock-in |
| Reference project | [paperclipai/paperclip](https://github.com/paperclipai/paperclip) | Model for multi-LLM provider pattern |
| Build approach | Solo + AI coding agents | Est. 6–9 months solo, 3–5 months with small team |

---

## Working With This Codebase

### Before You Do Anything
1. Read this file (`CLAUDE.md`)
2. Read `/memory/brain.md`
3. Read `/memory/open-questions.md` — don't solve something already decided, don't ignore something unresolved
4. If you're working on a specific system, read that system's notes in `/memory/systems.md`

### Behavioral Guardrails
These rules are intentionally general. They sit below the Galaxz architecture rules above and should not override contracts, memory decisions, or explicit user instructions.

#### Think Before Coding
- Do not assume silently. State relevant assumptions before implementing.
- If the request has multiple plausible interpretations, surface them instead of choosing one invisibly.
- If a simpler approach solves the task, prefer it and say why.
- If an ambiguity would materially change the implementation, stop and ask before writing code.

#### Simplicity First
- Write the minimum code that solves the requested problem.
- Do not add speculative features, configurability, abstractions, or future-proofing.
- Do not add defensive handling for impossible states unless a real boundary can produce them.
- If a solution is growing large, re-check whether the problem can be solved with a smaller change.

#### Surgical Changes
- Touch only files and lines required for the current task.
- Do not refactor, reformat, rename, or "improve" adjacent code unless it is directly necessary.
- Match the existing style even when a different style would be preferable in a new project.
- Remove only unused code created by your own changes. Mention pre-existing dead code instead of deleting it.
- Every changed line should trace back to the user request or to verification required by that request.

#### Goal-Driven Execution
- Define success criteria before substantial implementation.
- For bug fixes, prefer a failing test or reproducible check first, then make it pass.
- For validation or pipeline changes, include both happy-path and failure-path coverage when practical.
- For multi-step work, keep a short plan with a verification step for each meaningful phase.
- Keep looping until the stated checks pass or a concrete blocker is documented.

### Code Principles
- **One file per prompt / per change** — no sprawling multi-file diffs unless explicitly requested
- **Contracts first** — if a change touches a contract boundary, update the contract definition before writing implementation
- **Confidence scores are non-negotiable** — every agent output must include a confidence float
- **Aether for everything async** — no direct agent-to-agent calls that bypass the message bus
- **Boot order is sacred** — nothing starts before its dependency is confirmed live
- **Stubs are intentional** — if something is hardcoded or stubbed (e.g. `historical_confidence = 0.50`), it's waiting for a later phase. Don't "fix" it early.

### File Structure
```
galaxz/
├── core/
│   ├── contracts/         # Task, Skill, Refinery contract schemas
│   └── pulsar/            # Agent registry
├── agents/
│   ├── andromeda/         # Orchestrator
│   ├── vega/              # QA agent
│   └── rigel/             # Engineering agent
├── aether/                # Message bus config + helpers
├── orion/                 # Data refinery (Phase 3)
├── memory/                # Project memory — read before every session
├── boot.py                # System startup in correct order
├── docker-compose.yml
└── CLAUDE.md              # ← You are here
```

---

## What Galaxz Is NOT

- Not a single-agent assistant
- Not a wrapper around one LLM provider
- Not a proprietary closed platform
- Not a chatbot interface
- Not another LangChain clone

If a suggestion you're about to make would push the project toward any of the above — pause and reconsider.

---

## The Vision in One Paragraph

Galaxz is the OS that other AI agents run on. Like Linux for servers or Kubernetes for containers,
it provides the coordination layer — routing, registry, learning, and observability — that makes
multi-agent systems composable, reliable, and improvable over time. The open source core creates
the ecosystem. The hosted platform and enterprise features create the business. Every agent that
joins the network makes the network smarter. That's the flywheel.

---

*Last updated from: Galaxz design project brain chat + Phase 1 (Vega) + Phase 2 (Andromeda + Rigel) chats*
*Next: Read `/memory/open-questions.md` before starting any new work.*

> **This file is the last thing you read. Every time. No exceptions.**
> After user enters /exit and before closing the session,
> find the latest session from .claude — then  add the all the converstion to 'sessionID.txt in `/memory/` folder.

---

## Memory Files — Current Reality

The `/memory/` section above lists files (`brain.md`, `contracts.md`, etc.) that are the **intended** memory structure.
As of the last session (2026-04-19), the memory directory contains **session snapshot files** instead:

```
memory/
└── <session-id>.txt    # One file per session — read the most recent one
```

**How to find the right memory file:**
```bash
ls -lt memory/          # most recently modified = most recent session
```

Read the most recent `.txt` file in `memory/` — it is the canonical record of what was built and decided.
The planned `brain.md` / `contracts.md` / `systems.md` files do not yet exist; do not assume they do.

**Session memory format** (copy into every new session file you create):
- Header: date + session ID
- These instructions (verbatim)
- Summary of everything built or changed this session
- Key design decisions made
- Open questions / next steps

---

## Actual File Structure (Phase 1 — As Built)

The planned structure in the "Working With This Codebase" section above is aspirational.
The **actual** structure on disk after Phase 1:

```
galaxz/
├── core/
│   ├── __init__.py
│   ├── contracts/
│   │   ├── __init__.py
│   │   └── task.py              # TaskContract, TaskStatus, VegaStage, transition_status()
│   ├── aether/
│   │   ├── __init__.py
│   │   └── client.py            # AetherClient, get_aether_client()
│   └── llm/
│       ├── __init__.py
│       └── provider.py          # ProviderConfig, load_provider_config(), call_llm()
├── agents/
│   └── vega/
│       ├── __init__.py
│       ├── pipeline.py          # run_vega_pipeline() — orchestrates all 3 stages
│       └── stages/
│           ├── __init__.py
│           ├── analyzer.py      # Requirement, AnalyzerInput/Output, run_analyzer()
│           ├── test_designer.py # TestCase, TestDesignerInput/Output, run_test_designer()
│           └── bug_reporter.py  # TestResult, BugReport, BugReporterInput/Output, run_bug_reporter()
├── config/
│   └── providers.yaml           # LLM provider config — currently: anthropic/claude-sonnet-4-20250514
├── cli/
│   ├── __init__.py
│   └── run.py                   # Click CLI: `galaxz vega --input ... --results ... --output ...`
├── test/
│   ├── agents/                 # agent regression tests
│   ├── api/                    # end-to-end API smoke tests
│   ├── data/                   # shared test input data
│   ├── orion/                  # Orion ingestion/curation/heuristic tests
│   └── vega/                   # Vega pipeline regression tests
├── memory/
│   └── <session-id>.txt         # Session memory files
├── .env                         # ANTHROPIC_API_KEY, REDIS_URL (not committed)
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── CLAUDE.md
```

Not yet on disk (Phase 2+): `agents/andromeda/`, `agents/rigel/`, `core/pulsar/`, `orion/`, `boot.py`.
Do not assume these exist. Do not stub them out unless explicitly requested.

---

## Phase 1 Implementation — Patterns and Rules

These patterns are **established and must not be changed** without explicit instruction.

### TaskContract (`core/contracts/task.py`)
- **Pydantic v2 BaseModel. Immutable — never mutated in place.**
- `transition_status()` returns a **new** contract via `model_copy(update={...})`.
- State machine enforced via `VALID_TRANSITIONS`:
  ```
  pending → running → complete | retrying | failed
  retrying → running | failed
  complete and failed are terminal
  ```
- `started_at` set automatically on `→ running`.
- `completed_at` set automatically on `→ complete` or `→ failed`.

### AetherClient (`core/aether/client.py`)
- Wraps `redis-py`. Single stream key: `"galaxz:tasks"`.
- Publishes via `XADD` with field name `"data"` (JSON-serialised contract).
- Publish-only for now — consumer/read methods are a Phase 2+ concern.
- `get_aether_client()` reads `REDIS_URL` from env (default: `redis://localhost:6379`).

### LLM Provider (`core/llm/provider.py`)
- `load_provider_config()` reads `config/providers.yaml` and resolves `${ENV_VAR}` via `re.sub` against `os.environ`.
- `call_llm()` uses `litellm.completion()` with model string as `"{provider}/{model}"` (litellm routing convention).
- All litellm exceptions wrapped in `RuntimeError("LLM call failed: {original}")`.

### Stage Function Pattern (all three Vega stages follow this exactly)
1. Build system prompt + user message with schema hint (JSON schema injected for Analyzer)
2. Call `call_llm()`
3. Parse response with `Model.model_validate_json()`
4. **Recompute all counts/summaries locally — never trust LLM-provided counts**
5. Return via `model_copy(update={...})`

Special cases:
- **Analyzer**: injects `AnalyzerOutput.model_json_schema()` into the user message.
- **Test Designer**: initialises `coverage_summary` from input `req_ids` so silently skipped requirements appear with `count=0` in `uncovered_reqs`.
- **Bug Reporter**: returns early (no LLM call) if there are no `fail`/`blocked` results. `pass_rate` always computed locally.

### Pipeline (`agents/vega/pipeline.py`)
- One `run_id` (uuid4) shared across all three stage contracts.
- Each stage lifecycle: `create contract → publish(pending) → transition(running) → publish → run stage → transition(complete) + set output → publish`.
- On exception: `transition(failed) + set error → publish → re-raise`.
- Stage 3 skipped entirely (no contract created) when `test_results` is `None`.
- `AetherClient` closed in a `finally` block regardless of outcome.

### CLI (`cli/run.py`)
- Click group `galaxz` with one command `vega`.
- `--input` (required): path to requirements text file.
- `--results` (optional): path to JSON file containing list of `TestResult` dicts.
- `--config` (default: `config/providers.yaml`): provider config path.
- `--output` (optional): path to write full pipeline result as JSON.
- `json.dump` uses `default=str` to handle datetime fields.
- Internal param named `input_path` (not `input`) to avoid shadowing Python built-in.

### Docker / Infrastructure
- `ENV PYTHONPATH=/app` in Dockerfile — no `setup.py` or `pyproject.toml` needed.
- `docker-compose.yml`: two services — `aether` (Redis 7 alpine) and `galaxz` (built image).
- `env_file: .env` in compose — secrets never baked into the image.
- `config/` bind-mounted to `/app/config` — edit `providers.yaml` without rebuilding.

---

## Known Intentional Stubs (Do Not Fix Early)

These are placeholders waiting for a later phase. Leave them as-is:

| Location | Stub | Waiting For |
|----------|------|-------------|
| `BugReport.rigel_handoff: bool` | always `False` | Phase 2 — Andromeda routes flagged bugs to Rigel |
| `TaskContract.retry_count / max_retries` | fields exist, not wired | retry logic (Phase 2+) |
| `TaskContract.prompt_tokens / output_tokens` | fields exist | stage functions don't thread token counts back yet |
| `historical_confidence = 0.50` (any occurrence) | hardcoded | Phase 3 — Orion provides real scores |

---

## Dependencies and Environment

**`requirements.txt`:**
```
pydantic>=2.0
redis>=5.0
litellm>=1.0
pyyaml>=6.0
click>=8.0
python-dotenv>=1.0
```

**Python version:** 3.9 (enforced by existing `__pycache__` bytecode)

**Environment variables:**
| Variable | Purpose | Default |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key — injected via `ProviderConfig` into litellm | (required) |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379` |

---

## How to Run (Phase 1)

```bash
# 1. Copy and populate env file
cp .env.example .env   # then add ANTHROPIC_API_KEY

# 2. Boot Vega + Aether
docker-compose up --build

# 3. Run the pipeline (in a separate shell)
docker-compose exec galaxz python -m galaxz.cli.run vega \
  --input /path/to/requirements.txt \
  [--results /path/to/test_results.json] \
  [--output /path/to/output.json]
```

Output prints: `run_id`, requirement count, test case count, bug count (or "Stage 3 skipped").
