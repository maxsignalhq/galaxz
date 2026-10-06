# Wormhole (A2A gateway) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Galaxz speak Google's A2A v1.0 protocol in both directions: publish Pulsar skills as an A2A Agent Card and accept A2A tasks (inbound), and register remote A2A agents' skills in Pulsar (outbound).

**Architecture:** A new `core/a2a/` package. Inbound is a FastAPI router mounted in the Andromeda service: it authenticates per-caller bearer tokens, turns each `SendMessage` into a normal `TaskContract` on the existing durable jobs queue, and maps job state to A2A task states. Outbound is `WormholeAgent`, modelled on `QuasarAgent`: a synchronous httpx JSON-RPC client turns each remote skill into a Pulsar skill `wormhole.<agent>.<skill_id>` with binary confidence.

**Tech Stack:** Python 3, FastAPI/Starlette, httpx (already in requirements), pydantic v2 models already in `core/contracts`, PyYAML, pytest. No new dependency.

**Spec:** `docs/specs/2026-10-05-wormhole-a2a-gateway-design.md` (Task 9 updates it where this plan deviates).

## Global Constraints

- A2A **v1.0 only**; JSON-RPC 2.0 over HTTPS plus SSE; methods `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`, `GetExtendedAgentCard`. Out of scope: gRPC and REST bindings, push notifications, signed-card verification, A2A 0.3, multi-tenancy, `ListTasks`, `SubscribeToTask`.
- No new contract. Reuse `TaskContract`, `SkillManifest`/`SkillDefinition` (incl. `allowed_origins`) and the jobs queue.
- No new dependency (hand-written client; the official A2A SDK is async).
- Both directions off or empty by default: `config/a2a.yaml` ships `callers: []` and `agents: []`.
- Tokens are never inline in YAML; only `token_env` names are stored.
- `TaskContract.origin` for inbound tasks comes from the caller's token, never from the message.
- Outbound confidence is binary (`1.0` or `0.0`) so Andromeda never silently retries a remote agent.
- Wire names follow the A2A proto's JSON mapping: camelCase fields, `TASK_STATE_*` / `ROLE_*` enums, one unified `Part` discriminated by member (`text`, `data`), requests carry `A2A-Version: 1.0`.
- Repo conventions: one module per responsibility, `from __future__ import annotations`, tests in `test/core/` (flat `test_*.py`) and `test/api/`, run with `.venv/bin/python -m pytest`. **Commit messages carry no `Co-Authored-By` trailer** (project memory rule). Work on a feature branch (`git switch -c feature/wormhole-a2a`), not `main`; do not stage the unrelated `config/workspace.yaml` change.

## Review Focus

- **Token exfiltration:** a remote Agent Card names its own JSON-RPC URL; if that URL is on another host, our bearer token would be sent there. Expect the client to refuse any interface URL whose scheme+host differ from the configured `url` (Task 7).
- **Cross-caller task access:** `GetTask`/`CancelTask` take a job id; any job id on the shared queue (another caller's, or one from `/jobs`) must answer "not found" (Task 4).
- **Origin impersonation:** a caller configured with `origin: goal:abc` would satisfy `allowed_origins: ["goal:*"]` and reach restricted skills; configured origins must start with `a2a:` (Task 2).
- **Transitive re-export:** Wormhole's own `wormhole.*` skills must never appear on either Agent Card, or Galaxz would publish third-party agents and could loop between two instances (Task 3).
- **Hostile input:** malformed JSON, oversized bodies, non-object params, a `confidenceThreshold` of `true` or `1.5`, and remote error text must produce JSON-RPC errors (never a 500) without echoing tokens (Tasks 4 and 7).

---

### Task 1: Protocol primitives

**Files:**
- Create: `core/a2a/__init__.py` (empty)
- Create: `core/a2a/protocol.py`
- Test: `test/core/test_a2a_protocol.py`

**Interfaces:**
- Produces: constants `A2A_VERSION`, `BINDING`, `JSONRPC_BINDINGS`, `STATE_SUBMITTED|WORKING|COMPLETED|FAILED|CANCELED|INPUT_REQUIRED|REJECTED|AUTH_REQUIRED`, `TERMINAL_STATES`, `STOP_STATES`, `ROLE_USER`, `ROLE_AGENT`; class `A2AError(code, message, reason=None)`; factories `parse_error()`, `invalid_request(detail)`, `invalid_params(detail)`, `task_not_found()`, `task_not_cancelable()`, `unsupported_operation()`, `version_not_supported()`; functions `rpc_result(request_id, result) -> dict`, `rpc_error(request_id, error) -> dict`, `make_task(task_id, state, *, context_id=None, message_text=None, artifacts=None) -> dict`.

- [ ] **Step 1: Confirm wire details against the spec**

Open https://a2a-protocol.org/latest/specification/ and https://github.com/a2aproject/A2A (`specification/a2a.proto`). Confirm: the JSON-RPC error code table (this plan uses -32050 TaskNotFound, -32051 TaskNotCancelable, -32052 UnsupportedOperation, -32055 VersionNotSupported), the `protocolBinding` value for JSON-RPC (this plan emits `"JSONRPC"` and accepts `"JSON-RPC"`), and whether `SendMessage` results are wrapped as `{"task": ...}` (this plan emits the wrapper and the client accepts both). If anything differs, change the constants below and the numbers in this task's tests before continuing, and note the change in Task 9's spec update.

- [ ] **Step 2: Write the failing tests**

Create `test/core/test_a2a_protocol.py`:

```python
from core.a2a import protocol as p


def test_rpc_error_carries_code_and_reason():
    body = p.rpc_error(7, p.task_not_found())
    assert body == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {
            "code": -32050,
            "message": "Task not found or not accessible",
            "data": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "TASK_NOT_FOUND",
                        "domain": "a2a-protocol.org",
                    }
                ]
            },
        },
    }


def test_rpc_error_without_reason_has_no_data():
    body = p.rpc_error(None, p.parse_error())
    assert body["error"] == {"code": -32700, "message": "Parse error"}
    assert body["id"] is None


def test_error_factories_use_expected_codes():
    assert p.task_not_cancelable().code == -32051
    assert p.unsupported_operation().code == -32052
    assert p.version_not_supported().code == -32055
    assert p.invalid_params("bad").code == -32602
    assert p.invalid_request("big").code == -32600


def test_rpc_result_envelope():
    assert p.rpc_result("a", {"x": 1}) == {"jsonrpc": "2.0", "id": "a", "result": {"x": 1}}


def test_make_task_minimal():
    task = p.make_task("abc", p.STATE_WORKING)
    assert task["id"] == "abc"
    assert task["contextId"] == "abc"
    assert task["status"]["state"] == "TASK_STATE_WORKING"
    assert task["status"]["timestamp"].endswith("Z")
    assert "message" not in task["status"]
    assert "artifacts" not in task


def test_make_task_with_message_and_artifacts():
    artifact = {"artifactId": "r", "parts": [{"data": {"k": 1}}]}
    task = p.make_task("abc", p.STATE_FAILED, context_id="ctx", message_text="nope", artifacts=[artifact])
    assert task["contextId"] == "ctx"
    msg = task["status"]["message"]
    assert msg["role"] == "ROLE_AGENT"
    assert msg["parts"] == [{"text": "nope"}]
    assert msg["messageId"]
    assert task["artifacts"] == [artifact]


def test_state_sets():
    assert p.STATE_COMPLETED in p.TERMINAL_STATES
    assert p.STATE_INPUT_REQUIRED not in p.TERMINAL_STATES
    assert p.STATE_INPUT_REQUIRED in p.STOP_STATES
    assert p.STATE_WORKING not in p.STOP_STATES
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_protocol.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a'`).

- [ ] **Step 4: Implement**

Create empty `core/a2a/__init__.py`, then `core/a2a/protocol.py`:

```python
"""A2A v1.0 wire primitives: task states, errors, JSON-RPC envelopes, Task builder."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

A2A_VERSION = "1.0"
BINDING = "JSONRPC"  # what we emit on our Agent Card
JSONRPC_BINDINGS = frozenset({"JSONRPC", "JSON-RPC"})  # what we accept on remote cards

STATE_SUBMITTED = "TASK_STATE_SUBMITTED"
STATE_WORKING = "TASK_STATE_WORKING"
STATE_COMPLETED = "TASK_STATE_COMPLETED"
STATE_FAILED = "TASK_STATE_FAILED"
STATE_CANCELED = "TASK_STATE_CANCELED"
STATE_INPUT_REQUIRED = "TASK_STATE_INPUT_REQUIRED"
STATE_REJECTED = "TASK_STATE_REJECTED"
STATE_AUTH_REQUIRED = "TASK_STATE_AUTH_REQUIRED"

TERMINAL_STATES = frozenset({STATE_COMPLETED, STATE_FAILED, STATE_CANCELED, STATE_REJECTED})
# Nothing more happens on a task in these states without a client action.
STOP_STATES = TERMINAL_STATES | {STATE_INPUT_REQUIRED, STATE_AUTH_REQUIRED}

ROLE_USER = "ROLE_USER"
ROLE_AGENT = "ROLE_AGENT"

_ERROR_DOMAIN = "a2a-protocol.org"


class A2AError(Exception):
    def __init__(self, code: int, message: str, reason: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason = reason


def parse_error() -> A2AError:
    return A2AError(-32700, "Parse error")


def invalid_request(detail: str = "Invalid request") -> A2AError:
    return A2AError(-32600, detail)


def invalid_params(detail: str) -> A2AError:
    return A2AError(-32602, detail, "INVALID_PARAMS")


def task_not_found() -> A2AError:
    return A2AError(-32050, "Task not found or not accessible", "TASK_NOT_FOUND")


def task_not_cancelable() -> A2AError:
    return A2AError(-32051, "Task is not in a cancelable state", "TASK_NOT_CANCELABLE")


def unsupported_operation() -> A2AError:
    return A2AError(-32052, "Operation not supported", "UNSUPPORTED_OPERATION")


def version_not_supported() -> A2AError:
    return A2AError(-32055, "Protocol version not supported", "VERSION_NOT_SUPPORTED")


def rpc_result(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id, error: A2AError) -> dict:
    body: dict = {"code": error.code, "message": error.message}
    if error.reason:
        body["data"] = {
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": error.reason,
                    "domain": _ERROR_DOMAIN,
                }
            ]
        }
    return {"jsonrpc": "2.0", "id": request_id, "error": body}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def make_task(
    task_id: str,
    state: str,
    *,
    context_id: str | None = None,
    message_text: str | None = None,
    artifacts: list[dict] | None = None,
) -> dict:
    status: dict = {"state": state, "timestamp": _now()}
    if message_text:
        status["message"] = {
            "messageId": str(uuid.uuid4()),
            "role": ROLE_AGENT,
            "parts": [{"text": message_text}],
        }
    task: dict = {"id": task_id, "contextId": context_id or task_id, "status": status}
    if artifacts:
        task["artifacts"] = artifacts
    return task
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_a2a_protocol.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add core/a2a/__init__.py core/a2a/protocol.py test/core/test_a2a_protocol.py
git commit -m "feat(a2a): add A2A v1.0 protocol primitives"
```

---

### Task 2: Configuration and caller authentication

**Files:**
- Create: `core/a2a/config.py`
- Create: `config/a2a.yaml`
- Test: `test/core/test_a2a_config.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `A2A_CONFIG_PATH = "config/a2a.yaml"`; frozen dataclasses `CallerConfig(token, origin, skills=None)` with `.allows_skill(skill_id) -> bool`, `AgentConfig(name, url, token=None, timeout_s=60.0, allowed_origins=None)`, `A2AConfig(callers=(), agents=())` with `.authenticate(authorization: str) -> CallerConfig | None`; `load_a2a_config(path=A2A_CONFIG_PATH, environ=None) -> A2AConfig`.

- [ ] **Step 1: Write the failing tests**

Create `test/core/test_a2a_config.py`:

```python
import textwrap

from core.a2a.config import A2AConfig, CallerConfig, load_a2a_config


def _write(tmp_path, body: str):
    path = tmp_path / "a2a.yaml"
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_missing_file_gives_empty_config(tmp_path):
    cfg = load_a2a_config(str(tmp_path / "nope.yaml"), environ={})
    assert cfg == A2AConfig()


def test_shipped_default_is_empty():
    cfg = load_a2a_config("config/a2a.yaml", environ={})
    assert cfg.callers == () and cfg.agents == ()


def test_caller_loaded_with_token_from_env(tmp_path):
    path = _write(
        tmp_path,
        """
        callers:
          - token_env: PARTNER_TOKEN
            origin: "a2a:partner-x"
            skills: ["rigel.*"]
        """,
    )
    cfg = load_a2a_config(path, environ={"PARTNER_TOKEN": "s3cret"})
    assert cfg.callers == (CallerConfig(token="s3cret", origin="a2a:partner-x", skills=("rigel.*",)),)


def test_caller_with_unset_env_is_ignored(tmp_path, caplog):
    path = _write(tmp_path, 'callers:\n  - {token_env: MISSING, origin: "a2a:x"}\n')
    cfg = load_a2a_config(path, environ={})
    assert cfg.callers == ()
    assert "MISSING" in caplog.text


def test_caller_origin_must_use_a2a_prefix(tmp_path):
    path = _write(tmp_path, 'callers:\n  - {token_env: T, origin: "goal:abc"}\n')
    assert load_a2a_config(path, environ={"T": "x"}).callers == ()


def test_caller_missing_fields_or_bad_skills_skipped(tmp_path):
    path = _write(
        tmp_path,
        """
        callers:
          - {origin: "a2a:x"}
          - {token_env: T}
          - {token_env: T, origin: "a2a:y", skills: "rigel.*"}
          - not-a-mapping
        """,
    )
    assert load_a2a_config(path, environ={"T": "x"}).callers == ()


def test_authenticate_accepts_valid_bearer_only():
    cfg = A2AConfig(callers=(CallerConfig("tok-a", "a2a:a"), CallerConfig("tok-b", "a2a:b")))
    assert cfg.authenticate("Bearer tok-b").origin == "a2a:b"
    assert cfg.authenticate("bearer tok-a").origin == "a2a:a"
    assert cfg.authenticate("Bearer wrong") is None
    assert cfg.authenticate("Bearer ") is None
    assert cfg.authenticate("tok-a") is None
    assert cfg.authenticate("") is None
    assert A2AConfig().authenticate("Bearer tok-a") is None


def test_allows_skill_uses_fnmatch():
    assert CallerConfig("t", "a2a:a").allows_skill("anything")
    scoped = CallerConfig("t", "a2a:a", skills=("rigel.*",))
    assert scoped.allows_skill("rigel.skill.code_generation")
    assert not scoped.allows_skill("vega.skill.x")
    assert not CallerConfig("t", "a2a:a", skills=()).allows_skill("rigel.x")


def test_agents_loaded_and_validated(tmp_path):
    path = _write(
        tmp_path,
        """
        agents:
          - name: translator
            url: https://agents.example.com/
            token_env: TR_TOKEN
            timeout_s: 15
            allowed_origins: ["goal:*"]
          - {name: "Bad Name", url: "https://x.example"}
          - {name: nourl, url: "ftp://x.example"}
          - {name: plain, url: "http://localhost:9000"}
        """,
    )
    cfg = load_a2a_config(path, environ={"TR_TOKEN": "tok"})
    assert [a.name for a in cfg.agents] == ["translator", "plain"]
    translator = cfg.agents[0]
    assert translator.url == "https://agents.example.com"
    assert translator.token == "tok"
    assert translator.timeout_s == 15.0
    assert translator.allowed_origins == ["goal:*"]
    assert cfg.agents[1].token is None
    assert cfg.agents[1].timeout_s == 60.0
    assert cfg.agents[1].allowed_origins is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_config.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a.config'`).

- [ ] **Step 3: Implement**

Create `core/a2a/config.py`:

```python
"""Wormhole configuration: inbound callers and outbound remote agents."""
from __future__ import annotations

import hmac
import logging
import os
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase

import yaml

logger = logging.getLogger(__name__)

A2A_CONFIG_PATH = "config/a2a.yaml"
_AGENT_NAME = re.compile(r"^[a-z0-9_-]+$")
_ORIGIN_PREFIX = "a2a:"
_DEFAULT_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class CallerConfig:
    token: str
    origin: str
    skills: tuple[str, ...] | None = None

    def allows_skill(self, skill_id: str) -> bool:
        return self.skills is None or any(fnmatchcase(skill_id, p) for p in self.skills)


@dataclass(frozen=True)
class AgentConfig:
    name: str
    url: str
    token: str | None = None
    timeout_s: float = _DEFAULT_TIMEOUT_S
    allowed_origins: list[str] | None = None


@dataclass(frozen=True)
class A2AConfig:
    callers: tuple[CallerConfig, ...] = ()
    agents: tuple[AgentConfig, ...] = ()

    def authenticate(self, authorization: str) -> CallerConfig | None:
        scheme, _, presented = authorization.partition(" ")
        if scheme.lower() != "bearer" or not presented:
            return None
        match = None
        for caller in self.callers:  # no early exit: keep timing independent of position
            if hmac.compare_digest(presented.encode(), caller.token.encode()):
                match = caller
        return match


def _string_list(value) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


def _load_caller(entry, environ) -> CallerConfig | None:
    if not isinstance(entry, dict):
        logger.error("[a2a] caller entry must be a mapping — skipped")
        return None
    env_name = entry.get("token_env")
    origin = str(entry.get("origin") or "").strip()
    if not env_name or not origin:
        logger.error("[a2a] caller entry needs token_env and origin — skipped")
        return None
    if not origin.startswith(_ORIGIN_PREFIX):
        logger.error("[a2a] caller origin %r must start with %r — skipped", origin, _ORIGIN_PREFIX)
        return None
    token = (environ.get(env_name) or "").strip()
    if not token:
        logger.warning("[a2a] caller %s ignored: %s is not set", origin, env_name)
        return None
    skills = entry.get("skills")
    if skills is not None:
        skills = _string_list(skills)
        if skills is None:
            logger.error("[a2a] caller %s: skills must be a list of strings — skipped", origin)
            return None
    return CallerConfig(token=token, origin=origin, skills=tuple(skills) if skills is not None else None)


def _load_agent(entry, environ) -> AgentConfig | None:
    if not isinstance(entry, dict):
        logger.error("[a2a] agent entry must be a mapping — skipped")
        return None
    name = str(entry.get("name") or "")
    url = str(entry.get("url") or "").strip().rstrip("/")
    if not _AGENT_NAME.match(name):
        logger.error("[a2a] agent name %r must match [a-z0-9_-]+ — skipped", name)
        return None
    if not url.startswith(("http://", "https://")):
        logger.error("[a2a] agent %s: url must start with http:// or https:// — skipped", name)
        return None
    token = None
    env_name = entry.get("token_env")
    if env_name:
        token = (environ.get(env_name) or "").strip() or None
        if token is None:
            logger.warning("[a2a] agent %s: %s is not set — calling without a token", name, env_name)
    timeout = entry.get("timeout_s", _DEFAULT_TIMEOUT_S)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = _DEFAULT_TIMEOUT_S
    allowed = entry.get("allowed_origins")
    if allowed is not None:
        allowed = _string_list(allowed)
        if allowed is None:
            logger.error("[a2a] agent %s: allowed_origins must be a list of strings — skipped", name)
            return None
    return AgentConfig(name=name, url=url, token=token, timeout_s=float(timeout), allowed_origins=allowed)


def load_a2a_config(path: str = A2A_CONFIG_PATH, environ=None) -> A2AConfig:
    environ = os.environ if environ is None else environ
    if not os.path.exists(path):
        return A2AConfig()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    callers = [c for c in (_load_caller(e, environ) for e in raw.get("callers") or []) if c]
    agents = [a for a in (_load_agent(e, environ) for e in raw.get("agents") or []) if a]
    return A2AConfig(callers=tuple(callers), agents=tuple(agents))
```

Create `config/a2a.yaml`:

```yaml
# Wormhole — A2A gateway. Both lists are empty by default: nothing is exposed
# and no remote agent is called until you configure them.
#
# callers: who may call Galaxz over A2A. Tokens come from the environment,
# never from this file. `origin` must start with "a2a:" and is what
# allowed_origins rules and the review queue see; the caller cannot choose it.
# `skills` (optional) limits which skills this caller may request (fnmatch).
callers: []
#  - token_env: A2A_PARTNER_X_TOKEN
#    origin: "a2a:partner-x"
#    skills: ["rigel.*"]

# agents: remote A2A v1.0 agents whose skills become Pulsar skills named
# wormhole.<name>.<skill_id>. `allowed_origins` is the local policy for them.
agents: []
#  - name: translator
#    url: https://agents.example.com
#    token_env: TRANSLATOR_TOKEN
#    timeout_s: 60
#    allowed_origins: ["goal:*"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_a2a_config.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add core/a2a/config.py config/a2a.yaml test/core/test_a2a_config.py
git commit -m "feat(a2a): add Wormhole config and caller authentication"
```

---

### Task 3: Agent Card builder

**Files:**
- Create: `core/a2a/card.py`
- Test: `test/core/test_a2a_card.py`

**Interfaces:**
- Consumes: `A2A_VERSION`, `BINDING` from `core.a2a.protocol`; `CallerConfig` from `core.a2a.config`; `PulsarRegistry.list_agents()`, `SkillDefinition.permits(origin)`.
- Produces: `AGENT_CARD_PATH = "/.well-known/agent-card.json"`; `build_public_card(registry, base_url) -> dict`; `build_extended_card(registry, base_url, caller: CallerConfig) -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `test/core/test_a2a_card.py`:

```python
import pytest

from core.a2a.card import AGENT_CARD_PATH, build_extended_card, build_public_card
from core.a2a.config import CallerConfig
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry


def _skill(skill_id, allowed_origins=None):
    return SkillDefinition(
        skill_id=skill_id,
        description=f"does {skill_id}",
        input_schema={},
        output_schema={},
        allowed_origins=allowed_origins,
    )


@pytest.fixture
def registry(tmp_path):
    reg = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    reg.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[
                _skill("rigel.skill.code_generation"),
                _skill("ops.skill.deploy", ["goal:*"]),
                _skill("partner.skill", ["a2a:alpha"]),
                _skill("nobody.skill", []),
            ],
        )
    )
    reg.register(
        SkillManifest(
            agent_id="wormhole",
            agent_name="Wormhole",
            version="1",
            health_endpoint="http://wormhole:8000/health",
            skills=[_skill("wormhole.translator.translate")],
        )
    )
    return reg


def _ids(card):
    return [s["id"] for s in card["skills"]]


def test_well_known_path():
    assert AGENT_CARD_PATH == "/.well-known/agent-card.json"


def test_public_card_lists_only_unrestricted_skills(registry):
    card = build_public_card(registry, "https://galaxz.example")
    assert _ids(card) == ["rigel.skill.code_generation"]


def test_card_required_fields(registry):
    card = build_public_card(registry, "https://galaxz.example")
    assert card["name"] and card["description"] and card["version"]
    assert card["supportedInterfaces"] == [
        {"url": "https://galaxz.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
    ]
    assert card["capabilities"] == {"streaming": True, "pushNotifications": False, "extendedAgentCard": True}
    assert card["securitySchemes"] == {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}}
    assert card["securityRequirements"] == [{"schemes": {"bearer": {"list": []}}}]
    assert card["defaultInputModes"] == ["application/json"]
    assert card["defaultOutputModes"] == ["application/json"]
    skill = card["skills"][0]
    assert skill["name"] and skill["description"] and skill["tags"] == ["rigel"]


def test_extended_card_respects_origin_policy(registry):
    alpha = CallerConfig("t", "a2a:alpha")
    card = build_extended_card(registry, "https://galaxz.example", alpha)
    assert _ids(card) == ["partner.skill", "rigel.skill.code_generation"]
    beta = CallerConfig("t", "a2a:beta")
    assert _ids(build_extended_card(registry, "https://galaxz.example", beta)) == ["rigel.skill.code_generation"]


def test_extended_card_respects_caller_skill_allow_list(registry):
    scoped = CallerConfig("t", "a2a:alpha", skills=("partner.*",))
    assert _ids(build_extended_card(registry, "https://galaxz.example", scoped)) == ["partner.skill"]


def test_wormhole_skills_never_published(registry):
    caller = CallerConfig("t", "a2a:alpha")
    assert "wormhole.translator.translate" not in _ids(build_public_card(registry, "https://x"))
    assert "wormhole.translator.translate" not in _ids(build_extended_card(registry, "https://x", caller))


def test_duplicate_skill_ids_listed_once(registry):
    registry.register(
        SkillManifest(
            agent_id="rigel2",
            agent_name="Rigel 2",
            version="1",
            health_endpoint="http://rigel2:8000/health",
            skills=[_skill("rigel.skill.code_generation")],
        )
    )
    assert _ids(build_public_card(registry, "https://x")).count("rigel.skill.code_generation") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_card.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a.card'`).

- [ ] **Step 3: Implement**

Create `core/a2a/card.py`:

```python
"""Build A2A Agent Cards from the Pulsar registry."""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from typing import Callable

from core.a2a import protocol
from core.a2a.config import CallerConfig
from core.contracts import SkillDefinition
from core.pulsar.registry import PulsarRegistry

AGENT_CARD_PATH = "/.well-known/agent-card.json"
_JSON = "application/json"
# Never re-export remote agents we merely proxy: it would publish third parties'
# skills and let two Galaxz instances call each other in a loop.
_PROXY_AGENT_ID = "wormhole"


def _platform_version() -> str:
    try:
        return _package_version("galaxz")
    except PackageNotFoundError:
        return "0.0.0"


def _skill_entry(skill: SkillDefinition) -> dict:
    return {
        "id": skill.skill_id,
        "name": skill.skill_id,
        "description": skill.description,
        "tags": [skill.skill_id.split(".")[0]],
        "inputModes": [_JSON],
        "outputModes": [_JSON],
    }


def _collect(registry: PulsarRegistry, allowed: Callable[[SkillDefinition], bool]) -> list[dict]:
    seen: dict[str, SkillDefinition] = {}
    for manifest in registry.list_agents():
        if manifest.agent_id == _PROXY_AGENT_ID:
            continue
        for skill in manifest.skills:
            if skill.skill_id not in seen and allowed(skill):
                seen[skill.skill_id] = skill
    return [_skill_entry(seen[skill_id]) for skill_id in sorted(seen)]


def _card(base_url: str, skills: list[dict]) -> dict:
    return {
        "name": "Galaxz",
        "description": (
            "Galaxz multi-agent platform. To run a skill, send a data part "
            '{"skill": "<skill id>", "payload": {...}}.'
        ),
        "version": _platform_version(),
        "supportedInterfaces": [
            {
                "url": f"{base_url.rstrip('/')}/a2a",
                "protocolBinding": protocol.BINDING,
                "protocolVersion": protocol.A2A_VERSION,
            }
        ],
        "capabilities": {"streaming": True, "pushNotifications": False, "extendedAgentCard": True},
        "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "defaultInputModes": [_JSON],
        "defaultOutputModes": [_JSON],
        "skills": skills,
    }


def build_public_card(registry: PulsarRegistry, base_url: str) -> dict:
    return _card(base_url, _collect(registry, lambda s: s.allowed_origins is None))


def build_extended_card(registry: PulsarRegistry, base_url: str, caller: CallerConfig) -> dict:
    return _card(
        base_url,
        _collect(registry, lambda s: s.permits(caller.origin) and caller.allows_skill(s.skill_id)),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_a2a_card.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/a2a/card.py test/core/test_a2a_card.py
git commit -m "feat(a2a): build Agent Cards from the Pulsar registry"
```

---

### Task 4: Inbound server (card, SendMessage, GetTask, CancelTask, extended card)

**Files:**
- Create: `core/a2a/server.py`
- Test: `test/core/test_a2a_server.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3; `TaskContract` from `core.contracts`; `SqliteJobRepository.enqueue/get_job/get_task/get_result/cancel`; `InvalidJobState` from `core.jobs.repository`.
- Produces: `build_a2a_router(*, config_getter, registry_getter, jobs_getter, stream_poll_s=0.5, stream_timeout_s=300.0) -> fastapi.APIRouter` (schema-hidden). Routes: `GET /.well-known/agent-card.json`, `POST /a2a`. `MAX_BODY_BYTES = 1_000_000`. Streaming is added in Task 5; this task makes `SendStreamingMessage` answer `UnsupportedOperationError`.

- [ ] **Step 1: Write the failing tests**

Create `test/core/test_a2a_server.py`:

```python
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.a2a.config import A2AConfig, CallerConfig
from core.a2a.server import MAX_BODY_BYTES, build_a2a_router
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry

SKILL = "rigel.skill.code_generation"


def _skill(skill_id, allowed_origins=None):
    return SkillDefinition(
        skill_id=skill_id, description=skill_id, input_schema={}, output_schema={}, allowed_origins=allowed_origins
    )


@pytest.fixture
def env(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[_skill(SKILL), _skill("secret.skill", ["goal:*"]), _skill("partner.skill", ["a2a:alpha"])],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    config = A2AConfig(
        callers=(
            CallerConfig("tok-a", "a2a:alpha"),
            CallerConfig("tok-b", "a2a:beta", skills=("rigel.*",)),
        )
    )
    app = FastAPI()
    app.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: registry,
            jobs_getter=lambda: jobs,
            stream_poll_s=0.01,
            stream_timeout_s=2.0,
        )
    )
    return SimpleNamespace(client=TestClient(app), jobs=jobs, registry=registry)


def rpc(env, method, params=None, *, token="tok-a", version="1.0", raw=None, headers=None):
    hdrs = dict(headers or {})
    if version:
        hdrs["A2A-Version"] = version
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if raw is not None:
        return env.client.post("/a2a", content=raw, headers=hdrs)
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params if params is not None else {}}
    return env.client.post("/a2a", json=body, headers=hdrs)


def send_params(skill=SKILL, message_id="m1", payload=None, **message_extra):
    return {
        "message": {
            "messageId": message_id,
            "role": "ROLE_USER",
            "parts": [{"data": {"skill": skill, "payload": payload if payload is not None else {"spec": "x"}}}],
            **message_extra,
        }
    }


def send(env, token="tok-a", **kwargs):
    resp = rpc(env, "SendMessage", send_params(**kwargs), token=token)
    return resp.json()["result"]["task"]


def finish(env, result):
    claimed = env.jobs.claim(worker_id="w1", lease_seconds=30)
    assert claimed is not None
    job, attempt = claimed
    env.jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
    return job


def error_code(resp):
    return resp.json()["error"]["code"]


# ---- card ----------------------------------------------------------------


def test_public_card_hides_restricted_skills(env):
    card = env.client.get("/.well-known/agent-card.json").json()
    assert [s["id"] for s in card["skills"]] == [SKILL]
    assert card["supportedInterfaces"][0]["url"] == "http://testserver/a2a"


def test_public_card_honours_public_url_override(env, monkeypatch):
    monkeypatch.setenv("A2A_PUBLIC_URL", "https://galaxz.example/")
    card = env.client.get("/.well-known/agent-card.json").json()
    assert card["supportedInterfaces"][0]["url"] == "https://galaxz.example/a2a"


def test_extended_card_per_caller(env):
    alpha = rpc(env, "GetExtendedAgentCard", token="tok-a").json()["result"]
    assert [s["id"] for s in alpha["skills"]] == ["partner.skill", SKILL]
    beta = rpc(env, "GetExtendedAgentCard", token="tok-b").json()["result"]
    assert [s["id"] for s in beta["skills"]] == [SKILL]


# ---- auth and envelope ---------------------------------------------------


def test_missing_or_bad_token_is_401(env):
    assert rpc(env, "GetTask", token=None).status_code == 401
    bad = rpc(env, "GetTask", token="nope")
    assert bad.status_code == 401
    assert bad.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("version", [None, "0.3", "2.0"])
def test_wrong_version_is_rejected(env, version):
    assert error_code(rpc(env, "SendMessage", send_params(), version=version)) == -32055


def test_malformed_json_is_parse_error(env):
    assert error_code(rpc(env, "", raw=b"{not json")) == -32700


def test_non_object_and_bad_envelope_are_invalid_request(env):
    assert error_code(rpc(env, "", raw=b"[1,2]")) == -32600
    assert error_code(rpc(env, "", raw=b'{"jsonrpc":"1.0","method":"GetTask"}')) == -32600
    assert error_code(rpc(env, "", raw=b'{"jsonrpc":"2.0","method":5}')) == -32600


def test_non_object_params_are_invalid_params(env):
    raw = b'{"jsonrpc":"2.0","id":1,"method":"GetTask","params":[1]}'
    assert error_code(rpc(env, "", raw=raw)) == -32602


def test_oversized_body_is_rejected_without_500(env):
    resp = rpc(env, "", raw=b"x" * (MAX_BODY_BYTES + 1))
    assert resp.status_code == 200
    assert error_code(resp) == -32600


def test_unknown_method_is_unsupported_operation(env):
    assert error_code(rpc(env, "ListTasks")) == -32052
    assert error_code(rpc(env, "SendStreamingMessage", send_params())) == -32052  # until Task 5


def test_response_echoes_request_id(env):
    body = {"jsonrpc": "2.0", "id": "abc", "method": "GetExtendedAgentCard", "params": {}}
    resp = env.client.post("/a2a", json=body, headers={"A2A-Version": "1.0", "Authorization": "Bearer tok-a"})
    assert resp.json()["id"] == "abc"


# ---- SendMessage ---------------------------------------------------------


def test_send_message_enqueues_task_with_token_origin(env):
    task = send(env, metadata={"origin": "goal:evil"})
    assert task["status"]["state"] == "TASK_STATE_SUBMITTED"
    stored = env.jobs.get_task(__import__("uuid").UUID(task["id"]))
    assert isinstance(stored, TaskContract)
    assert stored.origin == "a2a:alpha"
    assert stored.skill == SKILL
    assert stored.payload == {"spec": "x"}
    assert stored.confidence_threshold == 0.65


def test_send_message_confidence_threshold_from_metadata(env):
    task = send(env, message_id="m2", metadata={"confidenceThreshold": 0.9})
    stored = env.jobs.get_task(__import__("uuid").UUID(task["id"]))
    assert stored.confidence_threshold == 0.9


def test_send_message_is_idempotent_per_origin_and_message_id(env):
    first = send(env, message_id="same")
    again = send(env, message_id="same")
    other_message = send(env, message_id="different")
    other_caller = send(env, token="tok-b", message_id="same")
    assert first["id"] == again["id"]
    assert len({first["id"], other_message["id"], other_caller["id"]}) == 3


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"message": "text"},
        {"message": {"role": "ROLE_USER", "parts": [{"data": {"skill": SKILL}}]}},
        {"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"data": {"skill": SKILL}}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "hi"}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"skill": SKILL, "payload": "x"}}]}},
        {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"data": {"skill": "  "}}]}},
    ],
)
def test_send_message_invalid_params(env, params):
    assert error_code(rpc(env, "SendMessage", params)) == -32602


@pytest.mark.parametrize("threshold", [True, 1.5, -0.1, "high"])
def test_send_message_bad_threshold(env, threshold):
    resp = rpc(env, "SendMessage", send_params(metadata={"confidenceThreshold": threshold}))
    assert error_code(resp) == -32602


def test_caller_skill_allow_list_yields_rejected_task(env):
    task = send(env, token="tok-b", skill="partner.skill", message_id="r1")
    assert task["status"]["state"] == "TASK_STATE_REJECTED"
    assert env.jobs.list_jobs() == []  # nothing was enqueued
    assert error_code(rpc(env, "GetTask", {"id": task["id"]}, token="tok-b")) == -32050


# ---- GetTask state mapping ----------------------------------------------


def get_task(env, task_id, token="tok-a"):
    return rpc(env, "GetTask", {"id": task_id}, token=token).json()["result"]


def test_queued_and_running_states(env):
    task = send(env)
    assert get_task(env, task["id"])["status"]["state"] == "TASK_STATE_SUBMITTED"
    env.jobs.claim(worker_id="w1", lease_seconds=30)
    assert get_task(env, task["id"])["status"]["state"] == "TASK_STATE_WORKING"


@pytest.mark.parametrize(
    "result,state",
    [
        ({"status": "complete", "confidence": 0.9, "result": {"code": "x"}, "summary": "s"}, "TASK_STATE_COMPLETED"),
        ({"status": "escalated", "confidence": 0.1}, "TASK_STATE_INPUT_REQUIRED"),
        ({"status": "no_agent_found", "failure_reason": "origin_not_allowed"}, "TASK_STATE_REJECTED"),
        ({"status": "no_agent_found", "failure_reason": "no_skill_match"}, "TASK_STATE_FAILED"),
        ({"status": "failed"}, "TASK_STATE_FAILED"),
    ],
)
def test_completed_job_result_maps_to_task_state(env, result, state):
    task = send(env)
    finish(env, result)
    assert get_task(env, task["id"])["status"]["state"] == state


def test_completed_task_carries_output_artifact_with_confidence(env):
    task = send(env)
    finish(env, {"status": "complete", "confidence": 0.9, "result": {"code": "x"}, "summary": "s", "gaps": ["g"]})
    done = get_task(env, task["id"])
    artifact = done["artifacts"][0]
    assert artifact["parts"] == [{"data": {"result": {"code": "x"}, "summary": "s", "gaps": ["g"]}}]
    assert artifact["metadata"] == {"confidence": 0.9}


def test_failed_job_does_not_leak_internal_error(env):
    task = send(env)
    job, attempt = env.jobs.claim(worker_id="w1", lease_seconds=30)
    env.jobs.record_failure(
        job_id=job.job_id, lease_token=attempt.lease_token, error="boom /srv/secret", error_code="permanent", retryable=False
    )
    view = get_task(env, task["id"])
    assert view["status"]["state"] == "TASK_STATE_FAILED"
    assert "boom" not in str(view) and "secret" not in str(view)


# ---- ownership -----------------------------------------------------------


def test_get_task_is_scoped_to_the_creating_caller(env):
    task = send(env, token="tok-a")
    assert error_code(rpc(env, "GetTask", {"id": task["id"]}, token="tok-b")) == -32050


def test_get_task_hides_jobs_not_created_over_a2a(env):
    foreign = TaskContract(origin="andromeda_api", skill=SKILL, payload={}, confidence_threshold=0.65)
    job = env.jobs.enqueue(task_id=foreign.task_id, task=foreign, idempotency_key="foreign-1")
    assert error_code(rpc(env, "GetTask", {"id": str(job.job_id)})) == -32050


@pytest.mark.parametrize("task_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000", None, 5])
def test_get_task_unknown_ids(env, task_id):
    assert error_code(rpc(env, "GetTask", {"id": task_id})) == -32050


# ---- CancelTask ----------------------------------------------------------


def test_cancel_task_and_idempotent_repeat(env):
    task = send(env)
    first = rpc(env, "CancelTask", {"id": task["id"]}).json()["result"]
    assert first["status"]["state"] == "TASK_STATE_CANCELED"
    again = rpc(env, "CancelTask", {"id": task["id"]}).json()["result"]
    assert again["status"]["state"] == "TASK_STATE_CANCELED"


def test_cancel_terminal_task_is_not_cancelable(env):
    task = send(env)
    finish(env, {"status": "complete"})
    assert error_code(rpc(env, "CancelTask", {"id": task["id"]})) == -32051


def test_cancel_other_callers_task_is_not_found(env):
    task = send(env, token="tok-a")
    assert error_code(rpc(env, "CancelTask", {"id": task["id"]}, token="tok-b")) == -32050
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_server.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a.server'`).

- [ ] **Step 3: Implement**

Create `core/a2a/server.py`:

```python
"""Inbound A2A: Agent Card + JSON-RPC endpoint backed by the durable jobs queue."""
from __future__ import annotations

import json
import os
import uuid
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.a2a import protocol as p
from core.a2a.card import AGENT_CARD_PATH, build_extended_card, build_public_card
from core.a2a.config import A2AConfig, CallerConfig
from core.contracts import TaskContract
from core.jobs.repository import InvalidJobState

MAX_BODY_BYTES = 1_000_000
_DEFAULT_THRESHOLD = 0.65


def _extract_call(message: dict) -> tuple[str, dict]:
    for part in message.get("parts") or []:
        data = part.get("data") if isinstance(part, dict) else None
        if isinstance(data, dict) and isinstance(data.get("skill"), str):
            payload = data.get("payload", {})
            if not isinstance(payload, dict):
                raise p.invalid_params("data.payload must be an object")
            return data["skill"], payload
    raise p.invalid_params('message needs a data part {"skill": "...", "payload": {...}}')


def _threshold(message: dict) -> float:
    metadata = message.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise p.invalid_params("message.metadata must be an object")
    value = metadata.get("confidenceThreshold", _DEFAULT_THRESHOLD)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
        raise p.invalid_params("confidenceThreshold must be a number between 0 and 1")
    return float(value)


def _artifact(result: dict) -> dict:
    return {
        "artifactId": "result",
        "name": "result",
        "parts": [
            {
                "data": {
                    "result": result.get("result"),
                    "summary": result.get("summary") or "",
                    "gaps": result.get("gaps") or [],
                }
            }
        ],
        "metadata": {"confidence": result.get("confidence")},
    }


def _map_job(job, result: dict | None) -> tuple[str, str | None, list[dict]]:
    status = job.status.value
    if status == "queued":
        return p.STATE_SUBMITTED, None, []
    if status == "running":
        return p.STATE_WORKING, None, []
    if status == "cancelled":
        return p.STATE_CANCELED, None, []
    if status == "failed":
        return p.STATE_FAILED, "task failed", []
    outcome = (result or {}).get("status")
    if outcome == "complete":
        return p.STATE_COMPLETED, None, [_artifact(result)]
    if outcome == "escalated":
        return p.STATE_INPUT_REQUIRED, "awaiting human review", []
    if outcome == "no_agent_found" and result.get("failure_reason") == "origin_not_allowed":
        return p.STATE_REJECTED, "origin not allowed for this skill", []
    return p.STATE_FAILED, str((result or {}).get("failure_reason") or outcome or "task failed"), []


def _task_view(repo, job) -> dict:
    state, text, artifacts = _map_job(job, repo.get_result(job.job_id))
    return p.make_task(str(job.job_id), state, message_text=text, artifacts=artifacts)


def _parse(raw: bytes) -> tuple[object, str, dict, p.A2AError | None]:
    try:
        body = json.loads(raw)
    except ValueError:
        return None, "", {}, p.parse_error()
    if not isinstance(body, dict):
        return None, "", {}, p.invalid_request()
    request_id = body.get("id")
    method = body.get("method")
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return request_id, "", {}, p.invalid_request()
    params = body.get("params", {})
    if not isinstance(params, dict):
        return request_id, method, {}, p.invalid_params("params must be an object")
    return request_id, method, params, None


def build_a2a_router(
    *,
    config_getter: Callable[[], A2AConfig],
    registry_getter: Callable[[], object],
    jobs_getter: Callable[[], object],
    stream_poll_s: float = 0.5,
    stream_timeout_s: float = 300.0,
) -> APIRouter:
    router = APIRouter(include_in_schema=False)

    def base_url(request: Request) -> str:
        return (os.getenv("A2A_PUBLIC_URL") or str(request.base_url)).rstrip("/")

    def enqueue(params: dict, caller: CallerConfig) -> tuple[UUID | None, dict]:
        message = params.get("message")
        if not isinstance(message, dict):
            raise p.invalid_params("params.message is required")
        message_id = message.get("messageId")
        if not isinstance(message_id, str) or not message_id.strip():
            raise p.invalid_params("message.messageId is required")
        if message.get("role") != p.ROLE_USER:
            raise p.invalid_params("message.role must be ROLE_USER")
        skill, payload = _extract_call(message)
        threshold = _threshold(message)
        if not caller.allows_skill(skill):
            return None, p.make_task(
                str(uuid.uuid4()), p.STATE_REJECTED, message_text="skill not permitted for this caller"
            )
        try:
            task = TaskContract(
                task_id=uuid.uuid4(),
                origin=caller.origin,  # always the token's origin, never the message's
                skill=skill,
                payload=payload,
                confidence_threshold=threshold,
            )
        except ValueError:
            raise p.invalid_params("invalid skill") from None
        repo = jobs_getter()
        job = repo.enqueue(
            task_id=task.task_id,
            task=task,
            idempotency_key=f"a2a:{caller.origin}:{message_id.strip()}",
        )
        return job.job_id, _task_view(repo, job)

    def owned_job(params: dict, caller: CallerConfig):
        repo = jobs_getter()
        try:
            job_id = UUID(str(params.get("id")))
        except ValueError:
            raise p.task_not_found() from None
        job = repo.get_job(job_id)
        task = repo.get_task(job_id) if job is not None else None
        if job is None or task is None or task.origin != caller.origin:
            raise p.task_not_found()
        return job

    def cancel(params: dict, caller: CallerConfig) -> dict:
        job = owned_job(params, caller)
        repo = jobs_getter()
        try:
            job = repo.cancel(job_id=job.job_id)
        except KeyError:
            raise p.task_not_found() from None
        except (ValueError, InvalidJobState):
            raise p.task_not_cancelable() from None
        return _task_view(repo, job)

    def dispatch(method: str, params: dict, caller: CallerConfig, base: str) -> dict:
        if method == "SendMessage":
            _, view = enqueue(params, caller)
            return {"task": view}
        if method == "GetTask":
            return _task_view(jobs_getter(), owned_job(params, caller))
        if method == "CancelTask":
            return cancel(params, caller)
        if method == "GetExtendedAgentCard":
            return build_extended_card(registry_getter(), base, caller)
        raise p.unsupported_operation()

    @router.get(AGENT_CARD_PATH)
    def public_card(request: Request):
        return build_public_card(registry_getter(), base_url(request))

    @router.post("/a2a")
    async def a2a(request: Request):
        caller = config_getter().authenticate(request.headers.get("Authorization", ""))
        if caller is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(p.rpc_error(None, p.invalid_request("Request too large")))
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return JSONResponse(p.rpc_error(None, p.invalid_request("Request too large")))
        request_id, method, params, error = _parse(raw)
        if error is not None:
            return JSONResponse(p.rpc_error(request_id, error))
        if request.headers.get("A2A-Version") != p.A2A_VERSION:
            return JSONResponse(p.rpc_error(request_id, p.version_not_supported()))
        try:
            result = await run_in_threadpool(dispatch, method, params, caller, base_url(request))
        except p.A2AError as exc:
            return JSONResponse(p.rpc_error(request_id, exc))
        return JSONResponse(p.rpc_result(request_id, result))

    return router
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_a2a_server.py -v`
Expected: all pass. If a `claim`/`complete` signature error appears, re-read `core/jobs/repository.py:236` and `:339` and fix the test helper (not the server).

- [ ] **Step 5: Commit**

```bash
git add core/a2a/server.py test/core/test_a2a_server.py
git commit -m "feat(a2a): add inbound A2A server on the jobs queue"
```

---

### Task 5: Streaming (`SendStreamingMessage`)

**Files:**
- Modify: `core/a2a/server.py` (add `events()` generator, streaming branch in `a2a()`; add imports)
- Test: `test/core/test_a2a_server.py` (append)

**Interfaces:**
- Consumes: `enqueue`, `_task_view`, `p.STOP_STATES` from Task 4.
- Produces: `SendStreamingMessage` returns `text/event-stream`; frames are `data: <json-rpc response>\n\n` whose `result` is `{"task": ...}` first, then `{"artifactUpdate": ...}` (on completion) and `{"statusUpdate": {"taskId", "contextId", "status"}}`.

- [ ] **Step 1: Write the failing tests**

Replace the last assertion of `test_unknown_method_is_unsupported_operation` in `test/core/test_a2a_server.py` so it only checks `ListTasks` (streaming is now supported):

```python
def test_unknown_method_is_unsupported_operation(env):
    assert error_code(rpc(env, "ListTasks")) == -32052
```

Append to `test/core/test_a2a_server.py`:

```python
import json
import threading
import time


def _frames(response):
    out = []
    for line in response.iter_lines():
        if line.startswith("data: "):
            out.append(json.loads(line[len("data: "):])["result"])
    return out


def _finish_soon(env, result, delay=0.15):
    def run():
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            claimed = env.jobs.claim(worker_id="w-stream", lease_seconds=30)
            if claimed:
                job, attempt = claimed
                env.jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
                return
            time.sleep(0.02)

    threading.Timer(delay, run).start()


def _stream(env, params, token="tok-a"):
    body = {"jsonrpc": "2.0", "id": 9, "method": "SendStreamingMessage", "params": params}
    headers = {"A2A-Version": "1.0", "Authorization": f"Bearer {token}"}
    return env.client.stream("POST", "/a2a", json=body, headers=headers)


def test_stream_emits_task_then_artifact_then_completed(env):
    _finish_soon(env, {"status": "complete", "confidence": 0.8, "result": {"code": "x"}, "summary": "s"})
    with _stream(env, send_params(message_id="s1")) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        frames = _frames(resp)
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    kinds = [next(iter(f)) for f in frames[1:]]
    assert kinds[-2:] == ["artifactUpdate", "statusUpdate"]
    final = frames[-1]["statusUpdate"]
    assert final["status"]["state"] == "TASK_STATE_COMPLETED"
    assert final["taskId"] == frames[0]["task"]["id"]
    assert frames[-2]["artifactUpdate"]["artifact"]["metadata"] == {"confidence": 0.8}


def test_stream_ends_on_input_required(env):
    _finish_soon(env, {"status": "escalated"})
    with _stream(env, send_params(message_id="s2")) as resp:
        frames = _frames(resp)
    assert frames[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


def test_stream_for_rejected_skill_is_a_single_task_event(env):
    with _stream(env, send_params(skill="partner.skill", message_id="s3"), token="tok-b") as resp:
        frames = _frames(resp)
    assert len(frames) == 1
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_REJECTED"


def test_stream_validation_errors_are_plain_json_rpc_errors(env):
    with _stream(env, {"message": {}}) as resp:
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["error"]["code"] == -32602


def test_stream_stops_at_timeout_when_job_never_finishes(env):
    with _stream(env, send_params(message_id="s4")) as resp:
        frames = _frames(resp)  # stream_timeout_s is 2.0 in the fixture
    assert len(frames) == 1
    assert frames[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_server.py -k stream -v`
Expected: FAIL (streaming returns `UnsupportedOperationError`, so `resp.headers["content-type"]` and frame assertions fail).

- [ ] **Step 3: Implement**

In `core/a2a/server.py`, add `import time` to the imports, add `StreamingResponse` to the `fastapi.responses` import, and add this inside `build_a2a_router` after `dispatch`:

```python
    def events(request_id, job_id: UUID | None, first_view: dict):
        def frame(payload: dict) -> str:
            return f"data: {json.dumps(p.rpc_result(request_id, payload))}\n\n"

        yield frame({"task": first_view})
        if job_id is None:
            return
        repo = jobs_getter()
        state = first_view["status"]["state"]
        deadline = time.monotonic() + stream_timeout_s
        while state not in p.STOP_STATES and time.monotonic() < deadline:
            time.sleep(stream_poll_s)
            job = repo.get_job(job_id)
            if job is None:
                return
            view = _task_view(repo, job)
            new_state = view["status"]["state"]
            if new_state == state:
                continue
            state = new_state
            if state == p.STATE_COMPLETED:
                for artifact in view.get("artifacts", []):
                    yield frame(
                        {"artifactUpdate": {"taskId": view["id"], "contextId": view["contextId"], "artifact": artifact}}
                    )
            yield frame(
                {"statusUpdate": {"taskId": view["id"], "contextId": view["contextId"], "status": view["status"]}}
            )
```

In `a2a()`, replace the `try:` block with:

```python
        try:
            if method == "SendStreamingMessage":
                job_id, view = await run_in_threadpool(enqueue, params, caller)
                return StreamingResponse(events(request_id, job_id, view), media_type="text/event-stream")
            result = await run_in_threadpool(dispatch, method, params, caller, base_url(request))
        except p.A2AError as exc:
            return JSONResponse(p.rpc_error(request_id, exc))
        return JSONResponse(p.rpc_result(request_id, result))
```

- [ ] **Step 4: Run the whole server test file**

Run: `.venv/bin/python -m pytest test/core/test_a2a_server.py -v`
Expected: all pass (about 2 s extra from the timeout test).

- [ ] **Step 5: Commit**

```bash
git add core/a2a/server.py test/core/test_a2a_server.py
git commit -m "feat(a2a): stream task updates over SSE"
```

---

### Task 6: Mount the inbound router in the Andromeda service

**Files:**
- Modify: `agents/andromeda/middleware/auth.py` (add two exempt routes)
- Modify: `services/andromeda_service.py` (imports; `_a2a_config()`; `app.include_router(...)`)
- Test: `test/api/test_a2a_api.py`

**Interfaces:**
- Consumes: `build_a2a_router`, `load_a2a_config`, `A2AConfig`; the service's `_andromeda`, `_jobs()`.
- Produces: `GET /.well-known/agent-card.json` and `POST /a2a` live on the Andromeda app, exempt from `GALAXZ_API_KEY` and authenticated by A2A tokens instead. OpenAPI is unchanged because the router is schema-hidden.

- [ ] **Step 1: Write the failing test**

Create `test/api/test_a2a_api.py`:

```python
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc
from core.a2a.config import A2AConfig, CallerConfig
from core.contracts import SkillDefinition, SkillManifest
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry

SKILL = "rigel.skill.code_generation"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None  # rebuild so ApiKeyMiddleware re-reads the key
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[SkillDefinition(skill_id=SKILL, description="code", input_schema={}, output_schema={})],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "jobs.db")
    monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(registry=registry))
    monkeypatch.setattr(svc, "_jobs", lambda: jobs)
    monkeypatch.setattr(svc, "_a2a_config", lambda: A2AConfig(callers=(CallerConfig("tok-a", "a2a:alpha"),)))
    return TestClient(svc.app)


def _rpc(client, headers):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "m1",
                "role": "ROLE_USER",
                "parts": [{"data": {"skill": SKILL, "payload": {"spec": "x"}}}],
            }
        },
    }
    return client.post("/a2a", json=body, headers=headers)


def test_agent_card_is_public_even_with_api_key_set(client):
    resp = client.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["skills"]] == [SKILL]


def test_a2a_uses_its_own_token_not_the_api_key(client):
    api_key_only = _rpc(client, {"Authorization": "Bearer test-key", "A2A-Version": "1.0"})
    assert api_key_only.status_code == 401
    assert api_key_only.headers["WWW-Authenticate"] == "Bearer"  # from the A2A handler, not the middleware

    ok = _rpc(client, {"Authorization": "Bearer tok-a", "A2A-Version": "1.0"})
    assert ok.status_code == 200
    assert ok.json()["result"]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"


def test_other_routes_still_require_the_api_key(client):
    assert client.get("/jobs").status_code == 401
    assert client.get("/jobs", headers={"Authorization": "Bearer tok-a"}).status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest test/api/test_a2a_api.py -v`
Expected: FAIL (`AttributeError: ... has no attribute '_a2a_config'` from monkeypatch, and the card route returns 404/401).

- [ ] **Step 3: Implement**

In `agents/andromeda/middleware/auth.py`, add to `_EXEMPT_ROUTES` (after the `/github/webhook` entry):

```python
    # A2A callers authenticate with per-caller tokens inside the A2A handler
    # (core/a2a/server.py), not with GALAXZ_API_KEY.
    ("GET", "/.well-known/agent-card.json"),
    ("POST", "/a2a"),
```

In `services/andromeda_service.py`, add near the other `core.*` imports:

```python
from core.a2a.config import A2AConfig, load_a2a_config
from core.a2a.server import build_a2a_router
```

Immediately after `app.add_middleware(ApiKeyMiddleware)` (currently line 157), add:

```python
_a2a_config_cache: A2AConfig | None = None


def _a2a_config() -> A2AConfig:
    global _a2a_config_cache
    if _a2a_config_cache is None:
        _a2a_config_cache = load_a2a_config()
    return _a2a_config_cache


app.include_router(
    build_a2a_router(
        config_getter=lambda: _a2a_config(),
        registry_getter=lambda: _andromeda.registry,
        jobs_getter=lambda: _jobs(),
    )
)
```

- [ ] **Step 4: Run tests, including the OpenAPI regression check**

Run: `.venv/bin/python -m pytest test/api/test_a2a_api.py test/api/test_openapi_contract.py test/api/test_andromeda_api.py -v`
Expected: all pass. If `test_openapi_contract` fails, the router leaked into the schema: confirm `APIRouter(include_in_schema=False)` in `core/a2a/server.py`; do not regenerate the contract here.

- [ ] **Step 5: Commit**

```bash
git add agents/andromeda/middleware/auth.py services/andromeda_service.py test/api/test_a2a_api.py
git commit -m "feat(a2a): mount the inbound A2A router in the Andromeda service"
```

---

### Task 7: Outbound A2A client

**Files:**
- Create: `core/a2a/client.py`
- Test: `test/core/test_a2a_client.py`

**Interfaces:**
- Consumes: `A2A_VERSION`, `JSONRPC_BINDINGS`, `ROLE_USER`, `STOP_STATES`, `STATE_*` from `core.a2a.protocol`; `AGENT_CARD_PATH` from `core.a2a.card`.
- Produces: `A2AClientError(RuntimeError)`; frozen dataclass `RemoteResult(state: str, text: str, data: list, raw: dict)`; `A2AClient(base_url, *, token=None, timeout_s=60.0, poll_s=0.5, http=None)` with `.fetch_card() -> dict`, `.connect() -> dict` (fetches card, picks the JSON-RPC 1.0 interface, returns the card), `.execute(remote_skill: str, payload: dict) -> RemoteResult`, `.close()`.

- [ ] **Step 1: Write the failing tests**

Create `test/core/test_a2a_client.py`:

```python
import json

import httpx
import pytest

from core.a2a.client import A2AClient, A2AClientError

BASE = "https://remote.example"
RPC = f"{BASE}/a2a"


def card(**interface):
    iface = {"url": RPC, "protocolBinding": "JSONRPC", "protocolVersion": "1.0", **interface}
    return {"name": "Remote", "skills": [{"id": "translate", "description": "Translate"}], "supportedInterfaces": [iface]}


def task(state, *, text=None, data=None):
    out = {"id": "t-1", "contextId": "t-1", "status": {"state": state}}
    if text:
        out["status"]["message"] = {"messageId": "x", "role": "ROLE_AGENT", "parts": [{"text": text}]}
    if data is not None:
        out["artifacts"] = [{"artifactId": "a", "parts": [{"data": data}]}]
    return out


class Remote:
    """Scriptable fake A2A agent served through httpx.MockTransport."""

    def __init__(self, card_body=None, send=None, gets=()):
        self.card_body = card_body if card_body is not None else card()
        self.send = send
        self.gets = list(gets)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/.well-known/agent-card.json":
            return httpx.Response(200, json=self.card_body)
        body = json.loads(request.content)
        method = body["method"]
        if method == "SendMessage":
            return self._reply(body, self.send)
        if method == "GetTask":
            return self._reply(body, self.gets.pop(0) if len(self.gets) > 1 else self.gets[0])
        if method == "CancelTask":
            return self._reply(body, {"task": task("TASK_STATE_CANCELED")})
        return httpx.Response(404)

    @staticmethod
    def _reply(body, result):
        if isinstance(result, httpx.Response):
            return result
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def methods(self):
        return [json.loads(r.content)["method"] for r in self.requests if r.method == "POST"]


def client_for(remote, **kwargs):
    http = httpx.Client(transport=httpx.MockTransport(remote))
    return A2AClient(BASE, http=http, poll_s=0.01, **kwargs)


def test_connect_picks_jsonrpc_v1_interface():
    c = client_for(Remote())
    assert c.connect()["name"] == "Remote"


def test_connect_accepts_binding_alias():
    client_for(Remote(card_body=card(protocolBinding="JSON-RPC"))).connect()


@pytest.mark.parametrize(
    "interface",
    [{"protocolVersion": "0.3"}, {"protocolBinding": "GRPC"}, {"url": "ftp://remote.example/a2a"}],
)
def test_connect_rejects_unusable_interfaces(interface):
    with pytest.raises(A2AClientError, match="JSON-RPC 1.0"):
        client_for(Remote(card_body=card(**interface))).connect()


def test_connect_refuses_interface_on_another_host_so_token_cannot_leak():
    remote = Remote(card_body=card(url="https://evil.example/a2a"))
    with pytest.raises(A2AClientError, match="JSON-RPC 1.0"):
        client_for(remote, token="secret").connect()
    assert all("evil.example" not in str(r.url) for r in remote.requests)


def test_connect_failures_become_client_errors():
    def boom(request):
        raise httpx.ConnectError("refused")

    c = A2AClient(BASE, http=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(A2AClientError, match="agent card"):
        c.connect()
    c2 = client_for(Remote(card_body=[1, 2]))
    with pytest.raises(A2AClientError, match="agent card"):
        c2.connect()


def test_execute_sends_text_and_data_parts_with_headers():
    remote = Remote(send={"task": task("TASK_STATE_COMPLETED", data={"out": 1})})
    c = client_for(remote, token="tok")
    result = c.execute("translate", {"text": "hello", "n": 2})
    rpc = [r for r in remote.requests if r.method == "POST"][0]
    assert rpc.headers["A2A-Version"] == "1.0"
    assert rpc.headers["Authorization"] == "Bearer tok"
    message = json.loads(rpc.content)["params"]["message"]
    assert message["role"] == "ROLE_USER" and message["messageId"]
    assert message["parts"] == [
        {"text": "hello"},
        {"data": {"skill": "translate", "payload": {"text": "hello", "n": 2}}},
    ]
    assert result.state == "TASK_STATE_COMPLETED"
    assert result.data == [{"out": 1}]


def test_execute_without_token_sends_no_authorization_and_no_text_part():
    remote = Remote(send={"task": task("TASK_STATE_COMPLETED")})
    client_for(remote).execute("translate", {"n": 1})
    rpc = [r for r in remote.requests if r.method == "POST"][0]
    assert "Authorization" not in rpc.headers
    assert json.loads(rpc.content)["params"]["message"]["parts"] == [
        {"data": {"skill": "translate", "payload": {"n": 1}}}
    ]


def test_execute_accepts_unwrapped_task_and_message_only_results():
    unwrapped = Remote(send=task("TASK_STATE_COMPLETED", text="done"))
    assert client_for(unwrapped).execute("translate", {}).text == "done"
    message_only = Remote(send={"message": {"messageId": "m", "role": "ROLE_AGENT", "parts": [{"text": "hi"}]}})
    result = client_for(message_only).execute("translate", {})
    assert (result.state, result.text) == ("TASK_STATE_COMPLETED", "hi")


def test_execute_polls_until_terminal():
    remote = Remote(
        send={"task": task("TASK_STATE_WORKING")},
        gets=[task("TASK_STATE_WORKING"), task("TASK_STATE_COMPLETED", text="finally")],
    )
    result = client_for(remote).execute("translate", {})
    assert result.state == "TASK_STATE_COMPLETED" and result.text == "finally"
    assert remote.methods() == ["SendMessage", "GetTask", "GetTask"]


@pytest.mark.parametrize("state", ["TASK_STATE_INPUT_REQUIRED", "TASK_STATE_AUTH_REQUIRED", "TASK_STATE_FAILED"])
def test_execute_returns_on_interrupted_and_failed_states(state):
    result = client_for(Remote(send={"task": task(state)})).execute("translate", {})
    assert result.state == state


def test_execute_times_out_and_cancels_remote():
    remote = Remote(send={"task": task("TASK_STATE_WORKING")}, gets=[task("TASK_STATE_WORKING")])
    c = client_for(remote, timeout_s=0.05)
    with pytest.raises(A2AClientError, match="timed out"):
        c.execute("translate", {})
    assert remote.methods()[-1] == "CancelTask"


def test_rpc_error_http_error_and_bad_json_become_client_errors_without_secrets():
    rpc_error = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32052, "message": "nope"}}
    with pytest.raises(A2AClientError, match="-32052"):
        client_for(Remote(send=httpx.Response(200, json=rpc_error)), token="s3cret").execute("t", {})
    with pytest.raises(A2AClientError, match="HTTP 500") as exc:
        client_for(Remote(send=httpx.Response(500, text="leaked s3cret body")), token="s3cret").execute("t", {})
    assert "s3cret" not in str(exc.value)
    with pytest.raises(A2AClientError, match="invalid JSON"):
        client_for(Remote(send=httpx.Response(200, text="<html>"))).execute("t", {})


def test_malformed_task_is_a_client_error():
    with pytest.raises(A2AClientError, match="malformed"):
        client_for(Remote(send={"task": {"id": "t", "status": {}}})).execute("t", {})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_a2a_client.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a.client'`).

- [ ] **Step 3: Implement**

Create `core/a2a/client.py`:

```python
"""Synchronous A2A v1.0 client (JSON-RPC over HTTPS) for outbound calls."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from core.a2a import protocol as p
from core.a2a.card import AGENT_CARD_PATH

MAX_RESPONSE_BYTES = 5_000_000
_REQUEST_TIMEOUT_S = 30.0


class A2AClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteResult:
    state: str
    text: str
    data: list
    raw: dict


def _origin(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc.lower()


def _parts_text(parts) -> list[str]:
    return [part["text"] for part in parts or [] if isinstance(part, dict) and isinstance(part.get("text"), str)]


def _task_state(task: dict) -> str:
    status = task.get("status")
    state = status.get("state") if isinstance(status, dict) else None
    if not isinstance(task.get("id"), str) or not isinstance(state, str):
        raise A2AClientError("remote returned a malformed task")
    return state


def _task_result(task: dict) -> RemoteResult:
    state = _task_state(task)
    texts: list[str] = []
    data: list = []
    message = task["status"].get("message")
    if isinstance(message, dict):
        texts += _parts_text(message.get("parts"))
    for artifact in task.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        texts += _parts_text(artifact.get("parts"))
        data += [part["data"] for part in artifact.get("parts") or [] if isinstance(part, dict) and "data" in part]
    return RemoteResult(state=state, text="\n".join(texts), data=data, raw=task)


class A2AClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout_s: float = 60.0,
        poll_s: float = 0.5,
        http: httpx.Client | None = None,
    ):
        self._base = base_url.rstrip("/")
        self._token = token
        self._timeout_s = timeout_s
        self._poll_s = poll_s
        self._http = http or httpx.Client(timeout=_REQUEST_TIMEOUT_S)  # redirects are not followed
        self._owns_http = http is None
        self._rpc_url: str | None = None

    def _headers(self) -> dict:
        headers = {"A2A-Version": p.A2A_VERSION, "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def fetch_card(self) -> dict:
        try:
            resp = self._http.get(self._base + AGENT_CARD_PATH, headers=self._headers())
        except httpx.HTTPError as exc:
            raise A2AClientError(f"agent card fetch failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise A2AClientError(f"agent card fetch failed: HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError:
            raise A2AClientError("agent card fetch failed: invalid JSON") from None
        if not isinstance(body, dict):
            raise A2AClientError("agent card fetch failed: card is not an object")
        return body

    def _pick_interface(self, card: dict) -> str:
        for interface in card.get("supportedInterfaces") or []:
            if not isinstance(interface, dict):
                continue
            url = interface.get("url")
            if (
                interface.get("protocolBinding") in p.JSONRPC_BINDINGS
                and interface.get("protocolVersion") == p.A2A_VERSION
                and isinstance(url, str)
                and url.startswith(("http://", "https://"))
                # The card is remote-controlled: never send our token to another host.
                and _origin(url) == _origin(self._base)
            ):
                return url
        raise A2AClientError("agent has no JSON-RPC 1.0 interface on its own host")

    def connect(self) -> dict:
        card = self.fetch_card()
        self._rpc_url = self._pick_interface(card)
        return card

    def _call(self, method: str, params: dict) -> dict:
        assert self._rpc_url is not None
        body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}
        try:
            resp = self._http.post(self._rpc_url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise A2AClientError(f"{method} failed: {type(exc).__name__}") from None
        if resp.status_code != 200:
            raise A2AClientError(f"{method} failed: HTTP {resp.status_code}")
        if len(resp.content) > MAX_RESPONSE_BYTES:
            raise A2AClientError(f"{method} failed: response too large")
        try:
            payload = resp.json()
        except ValueError:
            raise A2AClientError(f"{method} failed: invalid JSON") from None
        if not isinstance(payload, dict):
            raise A2AClientError(f"{method} failed: invalid response")
        error = payload.get("error")
        if isinstance(error, dict):
            raise A2AClientError(f"{method} failed: {error.get('code')} {str(error.get('message'))[:200]}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise A2AClientError(f"{method} failed: missing result")
        return result

    def _cancel_quietly(self, task_id: str) -> None:
        try:
            self._call("CancelTask", {"id": task_id})
        except A2AClientError:
            pass

    def execute(self, remote_skill: str, payload: dict) -> RemoteResult:
        if self._rpc_url is None:
            self.connect()
        deadline = time.monotonic() + self._timeout_s
        parts: list[dict] = []
        text = " ".join(v for v in payload.values() if isinstance(v, str)).strip()
        if text:
            parts.append({"text": text})
        parts.append({"data": {"skill": remote_skill, "payload": payload}})
        message = {"messageId": str(uuid.uuid4()), "role": p.ROLE_USER, "parts": parts}
        result = self._call("SendMessage", {"message": message})

        reply = result.get("message")
        if "task" not in result and isinstance(reply, dict):
            return RemoteResult(
                state=p.STATE_COMPLETED, text="\n".join(_parts_text(reply.get("parts"))), data=[], raw=reply
            )
        task = result.get("task", result)  # tolerate an unwrapped Task
        while True:
            state = _task_state(task)
            if state in p.STOP_STATES:
                return _task_result(task)
            if time.monotonic() >= deadline:
                self._cancel_quietly(task["id"])
                raise A2AClientError("timed out waiting for remote task")
            time.sleep(self._poll_s)
            task = self._call("GetTask", {"id": task["id"]})

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_a2a_client.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/a2a/client.py test/core/test_a2a_client.py
git commit -m "feat(a2a): add synchronous outbound A2A client"
```

---

### Task 8: WormholeAgent (remote skills as Pulsar skills)

**Files:**
- Create: `core/a2a/agent.py`
- Test: `test/core/test_wormhole_agent.py`

**Interfaces:**
- Consumes: `AgentConfig` (Task 2); `A2AClient`, `A2AClientError`, `RemoteResult` (Task 7); `PulsarRegistry.register/get_agent/deregister`; `SkillDefinition`, `SkillManifest`.
- Produces: `WormholeAgent(registry, agents: list[AgentConfig], client_factory=A2AClient)` with `AGENT_ID = "wormhole"`, `.skill_ids -> set[str]`, `.status() -> {"configured": bool, "agents": [{"name", "ok", "error", "skills": [{"skill_id", "description"}], "allowed_origins"}]}`, `.run(skill_id, payload, context=None) -> dict` (Quasar-shaped result plus `"state"`, `"text"`, `"data"`), `.close()`. `client_factory(url, *, token, timeout_s)` must return an object with `connect()`, `execute()`, `close()`.

- [ ] **Step 1: Write the failing tests**

Create `test/core/test_wormhole_agent.py`:

```python
import pytest

from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.review_queue import ReviewQueue
from agents.andromeda.task_log import TaskLog
from core.a2a.agent import WormholeAgent
from core.a2a.client import A2AClientError, RemoteResult
from core.a2a.config import AgentConfig
from core.artifacts.store import ArtifactStore
from core.contracts import SkillDefinition, SkillManifest, TaskContract
from core.nebula.store import NebulaStore
from core.pulsar.registry import PulsarRegistry

CARD = {
    "skills": [
        {"id": "translate", "description": "Translate text"},
        {"id": "bad id!", "description": "invalid id is skipped"},
        {"id": "summarize"},
    ]
}


class FakeClient:
    instances: dict[str, "FakeClient"] = {}

    def __init__(self, url, *, token=None, timeout_s=60.0):
        self.url, self.token, self.timeout_s = url, token, timeout_s
        self.closed = False
        self.calls: list[tuple[str, dict]] = []
        self.card = CARD
        self.result = RemoteResult("TASK_STATE_COMPLETED", "bonjour", [{"out": "bonjour"}], {})
        FakeClient.instances[url] = self

    def connect(self):
        if self.card is None:
            raise A2AClientError("agent card fetch failed: ConnectError")
        return self.card

    def execute(self, skill, payload):
        self.calls.append((skill, payload))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _reset():
    FakeClient.instances.clear()


def cfg(name="translator", url="https://t.example", allowed=None):
    return AgentConfig(name=name, url=url, token="tok", timeout_s=7.0, allowed_origins=allowed)


def registry_for(tmp_path):
    return PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))


def test_registers_remote_skills_with_local_policy(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg(allowed=["goal:*"])], client_factory=FakeClient)
    manifest = registry.get_agent("wormhole")
    skills = {s.skill_id: s for s in manifest.skills}
    assert set(skills) == {"wormhole.translator.translate", "wormhole.translator.summarize"}
    assert skills["wormhole.translator.translate"].description == "Translate text"
    assert skills["wormhole.translator.summarize"].description == "summarize"
    assert skills["wormhole.translator.translate"].allowed_origins == ["goal:*"]
    assert agent.skill_ids == set(skills)
    client = FakeClient.instances["https://t.example"]
    assert (client.token, client.timeout_s) == ("tok", 7.0)


def test_unreachable_agent_is_skipped_and_reported(tmp_path):
    registry = registry_for(tmp_path)

    class DeadFactory(FakeClient):
        def __init__(self, url, **kw):
            super().__init__(url, **kw)
            if "dead" in url:
                self.card = None

    agent = WormholeAgent(
        registry, [cfg(), cfg(name="dead", url="https://dead.example")], client_factory=DeadFactory
    )
    status = agent.status()
    assert status["configured"] is True
    good, dead = status["agents"]
    assert good["ok"] is True and good["error"] is None
    assert [s["skill_id"] for s in good["skills"]] == [
        "wormhole.translator.translate",
        "wormhole.translator.summarize",
    ]
    assert dead["name"] == "dead" and dead["ok"] is False and "ConnectError" in dead["error"]
    assert dead["skills"] == []
    assert DeadFactory.instances["https://dead.example"].closed is True


def test_no_skills_means_no_manifest_and_stale_one_is_removed(tmp_path):
    registry = registry_for(tmp_path)
    registry.register(
        SkillManifest(
            agent_id="wormhole",
            agent_name="old",
            version="0",
            health_endpoint="http://wormhole:8000/health",
            skills=[SkillDefinition(skill_id="wormhole.old.x", description="x", input_schema={}, output_schema={})],
        )
    )
    empty = WormholeAgent(registry, [], client_factory=FakeClient)
    assert registry.get_agent("wormhole") is None
    assert empty.status() == {"configured": False, "agents": []}
    assert empty.skill_ids == set()
    assert PulsarRegistry(db_path=str(tmp_path / "pulsar.db")).get_agent("wormhole") is None


def test_run_maps_remote_state_to_binary_confidence(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    client = FakeClient.instances["https://t.example"]

    ok = agent.run("wormhole.translator.translate", {"text": "hello"}, {})
    assert client.calls == [("translate", {"text": "hello"})]
    assert ok["confidence"] == 1.0
    assert ok["summary"] == "bonjour"
    assert ok["state"] == "TASK_STATE_COMPLETED" and ok["data"] == [{"out": "bonjour"}]
    assert ok["gaps"] == [] and ok["artifacts"] == [] and ok["writable"] is False
    assert ok["execution_result"] is None and ok["externally_calibrated"] is False
    assert set(ok["confidence_breakdown"]) == {"structural", "self_critique", "historical"}

    for state in [
        "TASK_STATE_FAILED",
        "TASK_STATE_REJECTED",
        "TASK_STATE_CANCELED",
        "TASK_STATE_INPUT_REQUIRED",
        "TASK_STATE_AUTH_REQUIRED",
    ]:
        client.result = RemoteResult(state, "why", [], {})
        bad = agent.run("wormhole.translator.translate", {}, {})
        assert bad["confidence"] == 0.0
        assert bad["gaps"] == ["why"]
        assert bad["state"] == state


def test_run_gap_has_fallback_text_and_unknown_skill_raises(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    FakeClient.instances["https://t.example"].result = RemoteResult("TASK_STATE_FAILED", "", [], {})
    assert agent.run("wormhole.translator.translate", {}, {})["gaps"] == ["remote task ended as TASK_STATE_FAILED"]
    with pytest.raises(ValueError, match="unknown skill"):
        agent.run("wormhole.translator.missing", {}, {})


def test_transport_error_propagates_so_the_task_fails(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    FakeClient.instances["https://t.example"].result = A2AClientError("timed out waiting for remote task")
    with pytest.raises(A2AClientError, match="timed out"):
        agent.run("wormhole.translator.translate", {}, {})


def test_close_closes_every_connected_client(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg()], client_factory=FakeClient)
    agent.close()
    assert FakeClient.instances["https://t.example"].closed is True


def test_routes_through_andromeda_and_honors_origin_policy(tmp_path):
    registry = registry_for(tmp_path)
    agent = WormholeAgent(registry, [cfg(allowed=["ops"])], client_factory=FakeClient)
    andromeda = Andromeda(
        registry=registry,
        review_queue=ReviewQueue(db_path=str(tmp_path / "reviews.db")),
        task_log=TaskLog(db_path=str(tmp_path / "tasks.db")),
        agents={"wormhole": agent},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "artifacts.db")),
        nebula=NebulaStore(db_path=str(tmp_path / "nebula.db")),
    )

    def route(origin):
        return andromeda.route(
            task=TaskContract(
                origin=origin,
                skill="wormhole.translator.translate",
                payload={"text": "hello"},
                confidence_threshold=0.9,
            )
        )

    assert route("ops")["status"] == "complete"
    assert route("intruder")["failure_reason"] == "origin_not_allowed"
    FakeClient.instances["https://t.example"].result = RemoteResult("TASK_STATE_FAILED", "no", [], {})
    assert route("ops")["status"] != "complete"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/core/test_wormhole_agent.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'core.a2a.agent'`).

- [ ] **Step 3: Implement**

Create `core/a2a/agent.py`:

```python
"""Wormhole: exposes remote A2A agents' skills as Pulsar skills (`wormhole.<agent>.<skill>`)."""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from core.a2a import protocol
from core.a2a.client import A2AClient, A2AClientError
from core.a2a.config import AgentConfig
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry

logger = logging.getLogger(__name__)

_REMOTE_SKILL_ID = re.compile(r"^[\w.:-]+$")


class WormholeAgent:
    AGENT_ID = "wormhole"
    AGENT_NAME = "Wormhole A2A Gateway"
    VERSION = "0.1.0"

    def __init__(
        self,
        registry: PulsarRegistry,
        agents: list[AgentConfig],
        client_factory: Callable[..., A2AClient] = A2AClient,
    ):
        self._clients: dict[str, A2AClient] = {}
        self._skills: dict[str, tuple[str, str]] = {}  # skill_id -> (agent name, remote skill id)
        self._status: list[dict] = []
        definitions: list[SkillDefinition] = []

        for cfg in agents:
            status = {
                "name": cfg.name,
                "ok": False,
                "error": None,
                "skills": [],
                "allowed_origins": cfg.allowed_origins,
            }
            self._status.append(status)
            client = client_factory(cfg.url, token=cfg.token, timeout_s=cfg.timeout_s)
            try:
                card = client.connect()
            except A2AClientError as exc:
                logger.warning("[wormhole] skipping remote agent %s: %s", cfg.name, exc)
                status["error"] = str(exc)
                client.close()
                continue
            status["ok"] = True
            self._clients[cfg.name] = client
            for remote in card.get("skills") or []:
                remote_id = remote.get("id") if isinstance(remote, dict) else None
                if not isinstance(remote_id, str) or not _REMOTE_SKILL_ID.match(remote_id):
                    logger.warning("[wormhole] %s: skipping skill with invalid id %r", cfg.name, remote_id)
                    continue
                skill_id = f"wormhole.{cfg.name}.{remote_id}"
                description = str(remote.get("description") or "").strip() or remote_id
                self._skills[skill_id] = (cfg.name, remote_id)
                status["skills"].append({"skill_id": skill_id, "description": description})
                definitions.append(
                    SkillDefinition(
                        skill_id=skill_id,
                        description=description,
                        input_schema={},
                        output_schema={},
                        avg_confidence=0.9,
                        allowed_origins=cfg.allowed_origins,
                    )
                )

        if definitions:
            registry.register(
                SkillManifest(
                    agent_id=self.AGENT_ID,
                    agent_name=self.AGENT_NAME,
                    version=self.VERSION,
                    skills=definitions,
                    health_endpoint=f"http://{self.AGENT_ID}:8000/health",
                )
            )
            logger.info("[wormhole] registered with Pulsar — %d remote skills", len(definitions))
        elif registry.get_agent(self.AGENT_ID) is not None:
            # Pulsar persists manifests; don't advertise skills from a previous config.
            registry.deregister(self.AGENT_ID)
            logger.info("[wormhole] no remote skills available — removed stale manifest")

    @property
    def skill_ids(self) -> set[str]:
        return set(self._skills)

    def status(self) -> dict:
        return {"configured": bool(self._status), "agents": self._status}

    def run(self, skill_id: str, payload: dict, context: Optional[dict] = None) -> dict:
        target = self._skills.get(skill_id)
        if target is None:
            raise ValueError(f"{self.AGENT_ID}: unknown skill {skill_id!r}")
        name, remote_id = target
        result = self._clients[name].execute(remote_id, payload)  # A2AClientError fails the task

        succeeded = result.state == protocol.STATE_COMPLETED
        # Binary on purpose: only 1.0 or 0.0, so Andromeda's low-confidence retry rule
        # never re-runs a remote agent that may have side effects.
        confidence = 1.0 if succeeded else 0.0
        gap = result.text or f"remote task ended as {result.state}"
        return {
            "state": result.state,
            "text": result.text,
            "data": result.data,
            "artifacts": [],
            "summary": result.text,
            "writable": False,
            "confidence": confidence,
            "confidence_breakdown": {"structural": confidence, "self_critique": confidence, "historical": 0.50},
            "gaps": [] if succeeded else [gap],
            "execution_result": None,
            "externally_calibrated": False,
        }

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest test/core/test_wormhole_agent.py -v`
Expected: all pass. If the Andromeda routing test fails on a missing result key, compare the returned dict with `QuasarAgent.run` in `core/quasar/agent.py` and add the missing key.

- [ ] **Step 5: Commit**

```bash
git add core/a2a/agent.py test/core/test_wormhole_agent.py
git commit -m "feat(a2a): add WormholeAgent exposing remote A2A skills via Pulsar"
```

---

### Task 9: Boot wiring, `/wormhole` status, end-to-end loopback, docs

**Files:**
- Modify: `boot.py` (import, create `WormholeAgent`, add to agents, `andromeda.wormhole`)
- Modify: `services/andromeda_service.py` (add `GET /wormhole` after `/quasar`)
- Modify: `core/constellation/catalog.py:14` (reserve `wormhole`)
- Modify: `test/contracts/andromeda-openapi.json` (regenerate)
- Modify: `docs/specs/2026-10-05-wormhole-a2a-gateway-design.md`, `README.md`, `RELEASE.md`, `CLAUDE.md`
- Test: `test/api/test_wormhole_api.py`, `test/core/test_a2a_loopback.py`, extend `test/core/test_constellation.py`

**Interfaces:**
- Consumes: `WormholeAgent`, `load_a2a_config`, `A2AClient`, `build_a2a_router`.
- Produces: boot attaches `andromeda.wormhole` (always, like `andromeda.quasar`); `GET /wormhole` returns `WormholeAgent.status()` or `{"configured": False, "agents": []}`.

- [ ] **Step 1: Write the failing tests**

Create `test/api/test_wormhole_api.py`:

```python
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import services.andromeda_service as svc

AUTH = {"Authorization": "Bearer test-key"}


class FakeWormhole:
    def status(self):
        return {
            "configured": True,
            "agents": [{"name": "t", "ok": True, "error": None, "skills": [], "allowed_origins": None}],
        }


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setenv("GALAXZ_API_KEY", "test-key")
    svc.app.middleware_stack = None

    def make(**attrs):
        monkeypatch.setattr(svc, "_andromeda", SimpleNamespace(**attrs))
        return TestClient(svc.app)

    return make


def test_requires_auth(make_client):
    assert make_client().get("/wormhole").status_code == 401


def test_unconfigured_reports_empty(make_client):
    r = make_client().get("/wormhole", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"configured": False, "agents": []}


def test_configured_returns_agent_status(make_client):
    r = make_client(wormhole=FakeWormhole()).get("/wormhole", headers=AUTH)
    assert r.json()["agents"][0]["name"] == "t"
```

Create `test/core/test_a2a_loopback.py` (a Galaxz instance calling another Galaxz instance's inbound A2A router, wire-compatible end to end):

```python
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.a2a.agent import WormholeAgent
from core.a2a.client import A2AClient
from core.a2a.config import A2AConfig, AgentConfig, CallerConfig
from core.a2a.server import build_a2a_router
from core.contracts import SkillDefinition, SkillManifest
from core.jobs import SqliteJobRepository
from core.pulsar.registry import PulsarRegistry


def _work_one_job(jobs, result):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        claimed = jobs.claim(worker_id="remote-worker", lease_seconds=30)
        if claimed:
            job, attempt = claimed
            jobs.complete(job_id=job.job_id, lease_token=attempt.lease_token, output_ref="o", result=result)
            return
        time.sleep(0.02)


def test_wormhole_calls_a_remote_galaxz_over_a2a(tmp_path):
    # "Remote" Galaxz: Pulsar + inbound router + a stand-in durable worker.
    remote_registry = PulsarRegistry(db_path=str(tmp_path / "remote-pulsar.db"))
    remote_registry.register(
        SkillManifest(
            agent_id="rigel",
            agent_name="Rigel",
            version="1",
            health_endpoint="http://rigel:8000/health",
            skills=[SkillDefinition(skill_id="rigel.skill.echo", description="echo", input_schema={}, output_schema={})],
        )
    )
    jobs = SqliteJobRepository(tmp_path / "remote-jobs.db")
    config = A2AConfig(callers=(CallerConfig("secret-token", "a2a:local-galaxz"),))
    remote = FastAPI()
    remote.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: remote_registry,
            jobs_getter=lambda: jobs,
            stream_poll_s=0.01,
        )
    )
    remote_http = TestClient(remote, base_url="https://remote.example")

    def client_factory(url, *, token, timeout_s):
        return A2AClient(url, token=token, timeout_s=timeout_s, poll_s=0.02, http=remote_http)

    # "Local" Galaxz: Wormhole pulls the remote card and registers its skills.
    local_registry = PulsarRegistry(db_path=str(tmp_path / "local-pulsar.db"))
    agent = WormholeAgent(
        local_registry,
        [AgentConfig(name="remote", url="https://remote.example", token="secret-token", timeout_s=5.0)],
        client_factory=client_factory,
    )
    assert agent.skill_ids == {"wormhole.remote.rigel.skill.echo"}

    threading.Timer(
        0.1, _work_one_job, args=(jobs, {"status": "complete", "confidence": 0.9, "result": {"echo": "hi"}, "summary": "hi"})
    ).start()
    out = agent.run("wormhole.remote.rigel.skill.echo", {"text": "hi"}, {})

    assert out["confidence"] == 1.0
    assert out["state"] == "TASK_STATE_COMPLETED"
    assert out["data"] == [{"result": {"echo": "hi"}, "summary": "hi", "gaps": []}]
    stored = jobs.list_jobs()[0]
    assert jobs.get_task(stored.job_id).origin == "a2a:local-galaxz"
    assert jobs.get_task(stored.job_id).skill == "rigel.skill.echo"


def test_wormhole_with_wrong_token_skips_the_remote(tmp_path):
    remote_registry = PulsarRegistry(db_path=str(tmp_path / "remote-pulsar.db"))
    config = A2AConfig(callers=(CallerConfig("right", "a2a:x"),))
    remote = FastAPI()
    remote.include_router(
        build_a2a_router(
            config_getter=lambda: config,
            registry_getter=lambda: remote_registry,
            jobs_getter=lambda: SqliteJobRepository(tmp_path / "j.db"),
        )
    )
    http = TestClient(remote, base_url="https://remote.example")
    registry = PulsarRegistry(db_path=str(tmp_path / "local.db"))
    # The public card needs no token, but the remote card is empty here, so nothing registers.
    agent = WormholeAgent(
        registry,
        [AgentConfig(name="remote", url="https://remote.example", token="wrong")],
        client_factory=lambda url, *, token, timeout_s: A2AClient(url, token=token, http=http),
    )
    assert agent.skill_ids == set()
    assert registry.get_agent("wormhole") is None
```

Append to `test/core/test_constellation.py` (reusing its existing parametrized test): change line 86 to include `"wormhole"`:

```python
@pytest.mark.parametrize("agent_id", ["rigel", "vega", "quasar", "wormhole", "andromeda"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest test/api/test_wormhole_api.py test/core/test_a2a_loopback.py test/core/test_constellation.py -v`
Expected: FAIL (`/wormhole` returns 404; constellation accepts `wormhole`). The loopback tests should already pass because Tasks 4, 7 and 8 are complete; if they do not, fix the cause before continuing (this is the first end-to-end check of the wire format).

- [ ] **Step 3: Implement boot wiring, status route and reservation**

In `boot.py`, add to the imports:

```python
from core.a2a.agent import WormholeAgent
from core.a2a.config import load_a2a_config
```

After the `quasar_agents = ...` line add:

```python
    wormhole = WormholeAgent(registry, list(load_a2a_config().agents))  # also clears a stale manifest when none are configured
    wormhole_agents = {wormhole.AGENT_ID: wormhole} if wormhole.skill_ids else {}
```

Add `**wormhole_agents,` after `**quasar_agents,` in the `agents={...}` dict, and after the `andromeda.quasar = quasar ...` line add:

```python
    andromeda.wormhole = wormhole  # kept even if every remote agent failed, so /wormhole can report why
```

In `services/andromeda_service.py`, immediately after the `get_quasar_status` function add:

```python
@app.get("/wormhole")
def get_wormhole_status():
    wormhole = getattr(_andromeda, "wormhole", None)
    if wormhole is None:
        return {"configured": False, "agents": []}
    return wormhole.status()
```

In `core/constellation/catalog.py:14`, add `"wormhole"` to the reserved set:

```python
    {"rigel", "vega", "andromeda", "pulsar", "orion", "aether", "quasar", "wormhole"}
```

- [ ] **Step 4: Regenerate the OpenAPI contract and run the whole affected suite**

`/wormhole` is a new public route, so the regression contract must be regenerated and reviewed:

Run: `.venv/bin/python -m scripts.export_openapi_contract && git diff --stat test/contracts/andromeda-openapi.json`
Expected: the diff adds only a `/wormhole` path (no `/a2a` or `/.well-known` entries).

Run: `.venv/bin/python -m pytest test/core test/api test/agents -q`
Expected: all pass (the pre-existing suite is 165+ tests; nothing that passed before may fail).

- [ ] **Step 5: Update the spec where this plan deviates**

In `docs/specs/2026-10-05-wormhole-a2a-gateway-design.md` make these edits:
1. Agent Card section: replace the last bullet ("Each card skill carries ...") with: "Each card skill carries `id` (the Pulsar `skill_id`), `name`, `description`, `tags` and JSON input/output modes. The v1.0 `AgentSkill` message has no field for an input schema or confidence, so neither is published; callers learn payload shapes from the description. Skills of the `wormhole` agent are never published (no transitive re-export)."
2. Configuration section: state that caller `origin` must start with `a2a:` so a caller can never impersonate internal origins such as `goal:*`.
3. Message to task section: replace "an allow-list violation" wording with: a skill outside the caller's `skills` allow-list returns a Task in `TASK_STATE_REJECTED` that is not persisted (so `GetTask` on it is `TaskNotFoundError`); `A2A-Version` is required on every request; `messageId` is required and makes `SendMessage` idempotent per origin.
4. Running a skill (outbound) section: replace "data part carrying `payload`" with "a text part (the payload's string values joined, when any) plus a data part `{"skill": <remote id>, "payload": ...}`"; and change the confidence table's Effect column to say a `0.0` confidence routes the task to the review queue (Andromeda escalates below the 0.40 failure threshold).
5. Outbound client: the JSON-RPC URL on a remote card must be on the same scheme and host as the configured `url`, otherwise the interface is refused (prevents sending our token to another host).

- [ ] **Step 6: Document the feature**

- `README.md`: next to the Quasar paragraph (around line 177) add a short **Wormhole (A2A)** paragraph: inbound endpoints, `config/a2a.yaml` (`callers` / `agents`, `a2a:` origins, `token_env`), outbound skill naming `wormhole.<agent>.<skill>`, `GET /wormhole`, and the limits (v1.0 only, no signed cards, needs the `worker` service for inbound tasks, `A2A_PUBLIC_URL` when behind a proxy).
- `RELEASE.md`: add an `## Unreleased — Wormhole (A2A gateway)` section above `## v1.1.0` using the table style of the v1.1.0 entry, plus the spec's limits.
- `CLAUDE.md`: in "The Seven Systems", extend the "Two more components exist alongside the seven" note to three and add a bullet: `**Wormhole** (`core/a2a/`) — A2A v1.0 gateway: publishes Pulsar skills as an Agent Card, accepts A2A tasks onto the jobs queue, and registers remote A2A agents as `wormhole.<agent>.<skill>` skills. Spec: `docs/specs/2026-10-05-wormhole-a2a-gateway-design.md`.`

- [ ] **Step 7: Commit**

```bash
git add boot.py services/andromeda_service.py core/constellation/catalog.py test/contracts/andromeda-openapi.json \
  test/api/test_wormhole_api.py test/core/test_a2a_loopback.py test/core/test_constellation.py \
  docs/specs/2026-10-05-wormhole-a2a-gateway-design.md README.md RELEASE.md CLAUDE.md
git commit -m "feat(a2a): wire Wormhole into boot, add /wormhole status, docs and loopback test"
```

---

## Self-review notes

- **Spec coverage:** inbound auth, card (public and extended), message-to-task, state mapping, cancel, streaming, outbound boot/skills/run/confidence, config, `/wormhole`, errors, limits are each covered (Tasks 2-9). The spec's `GetExtendedAgentCard`, `CancelTask`, SSE and origin-denied `REJECTED` all have tests.
- **Deviations from the spec, all folded into Task 9 Step 5:** no input-schema/confidence on card skills (proto has no field); skill allow-list violation returns an unpersisted `REJECTED` task; outbound sends text + data parts; `a2a:` origin prefix; same-host interface rule; `wormhole.*` skills never published.
- **Known verification points left to the executor:** wire details in Task 1 Step 1 (error codes, `JSONRPC` binding string, `SendMessage` result wrapper). Constants live in `core/a2a/protocol.py` only.
- **Not covered:** a real durable worker against the inbound queue (the loopback uses a stand-in worker; `services/worker_service.py` is unchanged and already runs `Andromeda.route`).

## Execution notes (added while implementing)

- `A2AClient.connect()` additionally calls `GetExtendedAgentCard` when the remote card advertises `capabilities.extendedAgentCard` and a token is configured, so a remote that restricts skills per caller is fully discoverable; it falls back to the public card if refused. Covered by three client tests and three loopback tests (restricted skill visible with the right token only; wrong or missing token sees public skills only).
- `CLAUDE.md` is not tracked in git in this repository, so the Task 9 CLAUDE.md edit was skipped; README, RELEASE and the spec carry the documentation.
