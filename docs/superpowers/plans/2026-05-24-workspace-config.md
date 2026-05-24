# Workspace Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in workspace awareness to Galaxz so Andromeda injects a developer's local project path into every routed task's context.

**Architecture:** A `WorkspaceConfig` Pydantic model + YAML loader lives in a new `workspace/` module. `TaskContract` gains an optional `workspace_root` field. `Andromeda.route()` loads the config on every call and, when enabled, stamps both the contract and the context dict before building `AndromedaState`.

**Tech Stack:** Python 3.12, Pydantic v2 BaseModel, PyYAML, pytest with `tmp_path` + `monkeypatch` fixtures.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `config/workspace.yaml` | Default opt-out config shipped with the repo |
| Create | `workspace/__init__.py` | Module marker |
| Create | `workspace/config.py` | `WorkspaceConfig` model + `load_workspace_config()` loader |
| Create | `test/workspace/__init__.py` | Module marker |
| Create | `test/workspace/test_workspace_config.py` | Tests 1–4 |
| Modify | `core/contracts/contracts.py` | Add `workspace_root: str \| None = None` to `TaskContract` |
| Modify | `test/core/test_contracts.py` | Two workspace_root contract tests |
| Modify | `agents/andromeda/orchestrator.py` | Import loader; inject into `route()` |

---

## Task 1: WorkspaceConfig loader — tests first

**Files:**
- Create: `workspace/__init__.py`
- Create: `workspace/config.py`
- Create: `test/workspace/__init__.py`
- Create: `test/workspace/test_workspace_config.py`
- Create: `config/workspace.yaml`

- [ ] **Step 1.1: Create empty module markers**

```bash
touch /path/to/galaxz/workspace/__init__.py
touch /path/to/galaxz/test/workspace/__init__.py
```

Run from the project root (`/Users/rmehra/Projects/galaxz`):
```bash
touch workspace/__init__.py test/workspace/__init__.py
```

- [ ] **Step 1.2: Write the failing tests**

Create `test/workspace/test_workspace_config.py`:

```python
import os
import textwrap

import pytest

from workspace.config import WorkspaceConfig, load_workspace_config


# ── Test 1 ──────────────────────────────────────────────────────────────────
def test_disabled_config_accepts_empty_workspace_root():
    cfg = WorkspaceConfig(enabled=False, workspace_root="")
    assert cfg.enabled is False
    assert cfg.workspace_root == ""


# ── Test 2 ──────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_with_valid_path(tmp_path):
    project_dir = tmp_path / "my-project"
    project_dir.mkdir()

    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        textwrap.dedent(f"""\
            workspace_root: "{project_dir}"
            enabled: true
        """)
    )

    cfg = load_workspace_config(str(config_file))

    assert cfg.enabled is True
    assert cfg.workspace_root == str(project_dir)


# ── Test 3a ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_empty_root_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text("workspace_root: ''\nenabled: true\n")

    with pytest.raises(ValueError, match="workspace_root must not be empty"):
        load_workspace_config(str(config_file))


# ── Test 3b ─────────────────────────────────────────────────────────────────
def test_load_workspace_config_enabled_but_missing_path_raises(tmp_path):
    config_file = tmp_path / "workspace.yaml"
    config_file.write_text(
        "workspace_root: '/does/not/exist/xyz'\nenabled: true\n"
    )

    with pytest.raises(ValueError, match="workspace_root does not exist"):
        load_workspace_config(str(config_file))


# ── Missing file ─────────────────────────────────────────────────────────────
def test_load_workspace_config_missing_file_returns_disabled_default(tmp_path):
    cfg = load_workspace_config(str(tmp_path / "no_such_file.yaml"))

    assert cfg.enabled is False
    assert cfg.workspace_root == ""
```

- [ ] **Step 1.3: Run tests to verify they all fail**

```bash
pytest test/workspace/test_workspace_config.py -v
```

Expected: 5 errors — `ModuleNotFoundError: No module named 'workspace'`

- [ ] **Step 1.4: Create `workspace/config.py`**

```python
from __future__ import annotations

import os

import yaml
from pydantic import BaseModel


class WorkspaceConfig(BaseModel):
    workspace_root: str
    enabled: bool


def load_workspace_config(config_path: str = "config/workspace.yaml") -> WorkspaceConfig:
    if not os.path.exists(config_path):
        return WorkspaceConfig(workspace_root="", enabled=False)

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = WorkspaceConfig(
        workspace_root=raw.get("workspace_root", ""),
        enabled=bool(raw.get("enabled", False)),
    )

    if cfg.enabled:
        if not cfg.workspace_root:
            raise ValueError("workspace_root must not be empty when workspace is enabled")
        if not os.path.exists(cfg.workspace_root):
            raise ValueError(f"workspace_root does not exist: {cfg.workspace_root}")

    return cfg
```

- [ ] **Step 1.5: Create `config/workspace.yaml`**

```yaml
workspace_root: ""  # absolute path to the developer's project, e.g. /Users/max/Projects/weather-app
enabled: false       # workspace mode is opt-in; false = previous behaviour preserved
```

- [ ] **Step 1.6: Run tests to verify they all pass**

```bash
pytest test/workspace/test_workspace_config.py -v
```

Expected:
```
PASSED test/workspace/test_workspace_config.py::test_disabled_config_accepts_empty_workspace_root
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_with_valid_path
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_but_empty_root_raises
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_but_missing_path_raises
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_missing_file_returns_disabled_default
5 passed
```

- [ ] **Step 1.7: Commit**

```bash
git add workspace/__init__.py workspace/config.py config/workspace.yaml \
        test/workspace/__init__.py test/workspace/test_workspace_config.py
git commit -m "feat: add WorkspaceConfig loader with opt-in validation"
```

---

## Task 2: Add `workspace_root` to `TaskContract`

**Files:**
- Modify: `core/contracts/contracts.py:15-31`
- Modify: `test/core/test_contracts.py`

- [ ] **Step 2.1: Write the failing tests**

Open `test/core/test_contracts.py` and append these two tests at the end of the file:

```python
def test_task_contract_workspace_root_defaults_to_none():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
    )
    assert task.workspace_root is None


def test_task_contract_workspace_root_round_trips():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
        workspace_root="/Users/dev/my-project",
    )
    restored = TaskContract.model_validate_json(task.model_dump_json())
    assert restored.workspace_root == "/Users/dev/my-project"
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
pytest test/core/test_contracts.py::test_task_contract_workspace_root_defaults_to_none \
       test/core/test_contracts.py::test_task_contract_workspace_root_round_trips -v
```

Expected: `FAILED` — `ValidationError` / unexpected keyword argument `workspace_root`

- [ ] **Step 2.3: Add `workspace_root` to `TaskContract`**

In `core/contracts/contracts.py`, the `TaskContract` class currently ends at the `deadline_ms` field. Add one line after it:

```python
class TaskContract(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    origin: str
    skill: str
    payload: dict
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    deadline_ms: int | None = Field(default=None, ge=0)
    workspace_root: str | None = None          # ← add this line
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("origin", "skill")
    @classmethod
    def validate_non_empty_str(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
pytest test/core/test_contracts.py -v
```

Expected: all tests in the file pass, including the two new ones.

- [ ] **Step 2.5: Commit**

```bash
git add core/contracts/contracts.py test/core/test_contracts.py
git commit -m "feat: add optional workspace_root field to TaskContract"
```

---

## Task 3: Wire workspace injection into `Andromeda.route()`

**Files:**
- Modify: `agents/andromeda/orchestrator.py`
- Modify: `test/workspace/test_workspace_config.py`

- [ ] **Step 3.1: Write the failing test**

Append to `test/workspace/test_workspace_config.py`:

```python
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from core.contracts import SkillDefinition, SkillManifest
from core.pulsar.registry import PulsarRegistry


_SKILL_ID = "workspace.test.skill"


class _MockAgent:
    def run(self, skill_id, payload, context=None):
        return {"confidence": 0.9, "result": {"ok": True}}


def _register_mock_agent(registry: PulsarRegistry) -> None:
    registry.register(
        SkillManifest(
            agent_id="mock",
            agent_name="Mock Agent",
            version="0.1.0",
            health_endpoint="http://mock:8080/health",
            skills=[
                SkillDefinition(
                    skill_id=_SKILL_ID,
                    description="Mock skill for workspace injection tests.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                )
            ],
        )
    )


def test_andromeda_route_injects_workspace_root_into_context(tmp_path, monkeypatch):
    ws_path = str(tmp_path / "my-project")
    os.makedirs(ws_path)

    monkeypatch.setattr(
        "agents.andromeda.orchestrator.load_workspace_config",
        lambda: WorkspaceConfig(workspace_root=ws_path, enabled=True),
    )

    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    _register_mock_agent(registry)

    andromeda = Andromeda(registry, task_log, agents={"mock": _MockAgent()})
    result = andromeda.route(
        task_type="workspace_test",
        required_skills=[_SKILL_ID],
        payload={"x": 1},
    )

    assert result["status"] == "complete"
    assert result["context"]["workspace_root"] == ws_path
```

- [ ] **Step 3.2: Run test to verify it fails**

```bash
pytest test/workspace/test_workspace_config.py::test_andromeda_route_injects_workspace_root_into_context -v
```

Expected: `FAILED` — `AttributeError` or assertion error because `load_workspace_config` is not imported in orchestrator and `workspace_root` is not in context.

- [ ] **Step 3.3: Wire `load_workspace_config` into `Andromeda.route()`**

In `agents/andromeda/orchestrator.py`:

**a) Add the import** — at the top of the file, after the existing imports, add:

```python
from workspace.config import load_workspace_config
```

**b) Inject workspace into `route()`** — the current `route()` method resolves `task` from the `if task is None` block, then immediately builds `initial_state`. Insert the workspace block between those two sections:

```python
    def route(
        self,
        task: TaskContract | None = None,
        task_type: str | None = None,
        required_skills: list | None = None,
        payload: dict | None = None,
        context: Optional[dict] = None,
        priority: str = "NORMAL",
    ) -> AndromedaState:
        if task is None:
            if not required_skills or payload is None:
                raise ValueError("route requires a TaskContract or legacy required_skills + payload")
            task = TaskContract(
                task_id=uuid.uuid4(),
                origin="legacy_route",
                skill=required_skills[0],
                payload=payload,
                confidence_threshold=0.65,
            )

        ws = load_workspace_config()
        if ws.enabled:
            task = task.model_copy(update={"workspace_root": ws.workspace_root})
            context = {**(context or {}), "workspace_root": ws.workspace_root}

        task_type = task_type or task.skill.split(".")[-1]
        required_skills = required_skills or [task.skill]
        initial_state = AndromedaState(
            task_id=str(task.task_id),
            task_type=task_type,
            required_skills=required_skills,
            priority=priority,
            payload=task.payload,
            context=context or {},
            timeout_ms=task.deadline_ms or 30000,
            status="routing",
            issued_at=task.created_at.isoformat(),
        )
        # ... rest of method unchanged
```

The full replacement for the `route()` body through the `initial_state` block (the `self.task_log.write(...)` and everything after it stay unchanged):

```python
    def route(
        self,
        task: TaskContract | None = None,
        task_type: str | None = None,
        required_skills: list | None = None,
        payload: dict | None = None,
        context: Optional[dict] = None,
        priority: str = "NORMAL",
    ) -> AndromedaState:
        if task is None:
            if not required_skills or payload is None:
                raise ValueError("route requires a TaskContract or legacy required_skills + payload")
            task = TaskContract(
                task_id=uuid.uuid4(),
                origin="legacy_route",
                skill=required_skills[0],
                payload=payload,
                confidence_threshold=0.65,
            )

        ws = load_workspace_config()
        if ws.enabled:
            task = task.model_copy(update={"workspace_root": ws.workspace_root})
            context = {**(context or {}), "workspace_root": ws.workspace_root}

        task_type = task_type or task.skill.split(".")[-1]
        required_skills = required_skills or [task.skill]
        initial_state = AndromedaState(
            task_id=str(task.task_id),
            task_type=task_type,
            required_skills=required_skills,
            priority=priority,
            payload=task.payload,
            context=context or {},
            timeout_ms=task.deadline_ms or 30000,
            status="routing",
            issued_at=task.created_at.isoformat(),
        )

        self.task_log.write(initial_state.model_copy(update={"status": "received"}))
        final_state = self.graph.invoke(initial_state.model_dump(mode="python"))
        validated_state = AndromedaState.model_validate(final_state)
        self.task_log.write(validated_state)
        result = validated_state.model_dump(mode="python")
        skill_output = result.get("result") if isinstance(result.get("result"), dict) else {}
        result["artifacts"] = skill_output.get("artifacts", [])
        result["writable"] = skill_output.get("writable", False)
        result["summary"] = skill_output.get("summary", "")
        result["execution_result"] = skill_output.get("execution_result")
        result["externally_calibrated"] = skill_output.get("externally_calibrated", False)
        if validated_state.status == "escalated":
            sla_deadline = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            self.review_queue.enqueue(
                task_id=validated_state.task_id,
                task_type=validated_state.task_type or "",
                confidence=validated_state.confidence or 0.0,
                payload=validated_state.payload or {},
                skill_id=validated_state.required_skills[0] if validated_state.required_skills else "",
                agent_id=validated_state.assigned_agent or "",
                agent_output=validated_state.result if isinstance(validated_state.result, dict) else {},
                sla_deadline=sla_deadline,
            )
            result["review_pending"] = True
        return result
```

- [ ] **Step 3.4: Run the workspace test suite**

```bash
pytest test/workspace/ -v
```

Expected:
```
PASSED test/workspace/test_workspace_config.py::test_disabled_config_accepts_empty_workspace_root
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_with_valid_path
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_but_empty_root_raises
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_enabled_but_missing_path_raises
PASSED test/workspace/test_workspace_config.py::test_load_workspace_config_missing_file_returns_disabled_default
PASSED test/workspace/test_workspace_config.py::test_andromeda_route_injects_workspace_root_into_context
6 passed
```

- [ ] **Step 3.5: Run the full test suite to check for regressions**

```bash
pytest test/core/ test/workspace/ test/agents/ -v --ignore=test/UI
```

All previously passing tests should still pass. New tests should pass.

- [ ] **Step 3.6: Commit**

```bash
git add agents/andromeda/orchestrator.py test/workspace/test_workspace_config.py
git commit -m "feat: inject workspace_root into Andromeda route context when enabled"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|------------------|-----------|
| `config/workspace.yaml` with `workspace_root` + `enabled` fields | Task 1, Step 1.5 |
| `WorkspaceConfig` Pydantic model | Task 1, Step 1.4 |
| `load_workspace_config()` with missing-file default | Task 1, tests + impl |
| `enabled: true` + empty root raises `ValueError` | Task 1, test 3a + impl |
| `enabled: true` + missing path raises `ValueError` | Task 1, test 3b + impl |
| `TaskContract.workspace_root: str \| None = None` | Task 2 |
| `Andromeda.route()` calls loader before dispatch | Task 3, Step 3.3 |
| `enabled: true` → stamps `task.workspace_root` via `model_copy` | Task 3, Step 3.3 |
| `enabled: true` → stamps `context["workspace_root"]` | Task 3, Step 3.3 |
| `enabled: false` → no mutation | Covered by the `if ws.enabled` guard |
| Test 1: disabled config with empty root | Task 1, test 1 |
| Test 2: valid enabled config passes | Task 1, test 2 |
| Test 3: missing path raises | Task 1, tests 3a + 3b |
| Test 4: routed task has `workspace_root` in context | Task 3 |
| Rigel and Vega not touched | ✓ Neither file is in the file map |
| No Aether schema changes | ✓ Not in any task |

All requirements covered. No placeholders. Types consistent across tasks (`WorkspaceConfig`, `load_workspace_config`, `workspace_root: str | None`).
