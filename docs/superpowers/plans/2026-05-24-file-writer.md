# FileWriter + Rigel Disk-Write Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When `workspace_root` is set on a routed task, Rigel writes its generated artifacts to disk and returns disk-write receipts (`written_artifacts`) alongside the existing in-memory `artifacts`.

**Architecture:** Three independent tasks build up to the feature: (1) a self-contained `FileWriter` utility in the existing `workspace/` module; (2) `output_path` on `TaskContract` threaded to agent context by Andromeda; (3) a post-processing block in `RigelAgent.run()` that uses `FileWriter` when `workspace_root` is in context. The existing `artifacts` field (code content for the UI) is untouched; `written_artifacts` is added alongside it.

**Tech Stack:** Python 3.12, Pydantic v2 BaseModel, pathlib, pytest `tmp_path` fixture.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `workspace/file_writer.py` | `WrittenArtifact` model + `FileWriter` class |
| Create | `test/workspace/test_file_writer.py` | Unit tests for FileWriter (Tests 1–4) |
| Modify | `core/contracts/contracts.py` | Add `output_path: str \| None = None` to `TaskContract` |
| Modify | `test/core/test_contracts.py` | Two `output_path` contract tests |
| Modify | `agents/andromeda/orchestrator.py` | Thread `output_path` into context alongside `workspace_root` |
| Modify | `test/workspace/test_workspace_config.py` | One Andromeda `output_path` threading test |
| Modify | `agents/rigel/agent.py` | Import `FileWriter`, add `_task_description` helper, post-process block in `run()` |
| Create | `test/agents/test_rigel_workspace.py` | Rigel integration test (Test 5) |

---

## Task 1: `workspace/file_writer.py` — WrittenArtifact + FileWriter

**Files:**
- Create: `workspace/file_writer.py`
- Create: `test/workspace/test_file_writer.py`

- [ ] **Step 1.1: Write the failing tests**

Create `test/workspace/test_file_writer.py`:

```python
import pytest

from workspace.file_writer import FileWriter, WrittenArtifact


def test_write_creates_file_and_returns_valid_artifact(tmp_path):
    writer = FileWriter(str(tmp_path))
    artifact = writer.write("hello.py", "print('hello')\n")

    assert artifact.filename == "hello.py"
    assert artifact.absolute_path == str(tmp_path / "hello.py")
    assert artifact.relative_path == "hello.py"
    assert artifact.size_bytes > 0
    assert (tmp_path / "hello.py").read_text() == "print('hello')\n"


def test_write_creates_missing_parent_directories(tmp_path):
    writer = FileWriter(str(tmp_path))
    artifact = writer.write("subdir/nested/foo.py", "x = 1\n")

    assert (tmp_path / "subdir" / "nested" / "foo.py").exists()
    assert artifact.relative_path == "subdir/nested/foo.py"


def test_infer_filename_code_generation_returns_py_file(tmp_path):
    writer = FileWriter(str(tmp_path))
    result = writer.infer_filename("create a weather app", "code_generation")

    assert result.endswith(".py")
    assert result  # not empty
    assert "weather" in result


def test_infer_filename_empty_description_returns_fallback(tmp_path):
    writer = FileWriter(str(tmp_path))
    result = writer.infer_filename("", "test_writing")

    assert result == "output_test_writing.py"
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/workspace/test_file_writer.py -v
```

Expected: `ModuleNotFoundError: No module named 'workspace.file_writer'`

- [ ] **Step 1.3: Create `workspace/file_writer.py`**

```python
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

_STOP_WORDS = {
    "a", "an", "the", "to", "for", "of", "in", "on", "at",
    "with", "and", "or", "is", "are", "that", "this", "it",
    "be", "as", "by", "from", "into",
}


class WrittenArtifact(BaseModel):
    filename: str
    absolute_path: str
    relative_path: str
    size_bytes: int


class FileWriter:
    def __init__(self, workspace_root: str) -> None:
        self._root = Path(workspace_root)

    def write(self, filename: str, content: str) -> WrittenArtifact:
        full_path = self._root / filename
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        return WrittenArtifact(
            filename=filename,
            absolute_path=str(full_path),
            relative_path=filename,
            size_bytes=len(content.encode("utf-8")),
        )

    def infer_filename(self, task_description: str, skill: str) -> str:
        words = task_description.lower().split()
        filtered = [
            re.sub(r"[^a-z0-9]", "", w)
            for w in words
            if w not in _STOP_WORDS
        ]
        filtered = [w for w in filtered if w]
        slug = "_".join(filtered)[:40]

        if not slug:
            return f"output_{skill}.py"

        if skill == "test_writing":
            return f"test_{slug}.py"
        return f"{slug}.py"
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/workspace/test_file_writer.py -v
```

Expected:
```
PASSED test/workspace/test_file_writer.py::test_write_creates_file_and_returns_valid_artifact
PASSED test/workspace/test_file_writer.py::test_write_creates_missing_parent_directories
PASSED test/workspace/test_file_writer.py::test_infer_filename_code_generation_returns_py_file
PASSED test/workspace/test_file_writer.py::test_infer_filename_empty_description_returns_fallback
4 passed
```

- [ ] **Step 1.5: Commit**

```bash
git add workspace/file_writer.py test/workspace/test_file_writer.py
git commit -m "feat: add FileWriter utility with WrittenArtifact model"
```

---

## Task 2: `output_path` on TaskContract + Andromeda threading

**Files:**
- Modify: `core/contracts/contracts.py`
- Modify: `test/core/test_contracts.py`
- Modify: `agents/andromeda/orchestrator.py`
- Modify: `test/workspace/test_workspace_config.py`

- [ ] **Step 2.1: Write the failing contract tests**

Append to the end of `test/core/test_contracts.py`:

```python
def test_task_contract_output_path_defaults_to_none():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
    )
    assert task.output_path is None


def test_task_contract_output_path_round_trips():
    task = TaskContract(
        origin="test",
        skill="foo.bar",
        payload={"x": 1},
        confidence_threshold=0.7,
        output_path="src/weather.py",
    )
    restored = TaskContract.model_validate_json(task.model_dump_json())
    assert restored.output_path == "src/weather.py"
```

- [ ] **Step 2.2: Run contract tests to confirm they fail**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/core/test_contracts.py::test_task_contract_output_path_defaults_to_none test/core/test_contracts.py::test_task_contract_output_path_round_trips -v
```

Expected: `FAILED` — `ValidationError` or unexpected keyword argument `output_path`

- [ ] **Step 2.3: Write the failing Andromeda threading test**

Append to `test/workspace/test_workspace_config.py`:

```python
def test_andromeda_route_threads_output_path_into_context(tmp_path, monkeypatch):
    ws_path = str(tmp_path / "my-project")
    os.makedirs(ws_path)

    monkeypatch.setattr(
        "agents.andromeda.orchestrator.load_workspace_config",
        lambda: WorkspaceConfig(workspace_root=ws_path, enabled=True),
    )

    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    task_log = TaskLog(db_path=str(tmp_path / "andromeda_tasks.db"))
    _register_mock_agent(registry)

    mock_agent = _MockAgent()
    andromeda = Andromeda(registry, task_log, agents={"mock": mock_agent})

    from core.contracts import TaskContract
    task = TaskContract(
        origin="test",
        skill=_SKILL_ID,
        payload={"x": 1},
        confidence_threshold=0.65,
        output_path="src/weather.py",
    )
    result = andromeda.route(task=task)

    assert result["status"] == "complete"
    assert result["context"]["output_path"] == "src/weather.py"
    assert mock_agent.received_context.get("output_path") == "src/weather.py"
```

- [ ] **Step 2.4: Run Andromeda test to confirm it fails**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest "test/workspace/test_workspace_config.py::test_andromeda_route_threads_output_path_into_context" -v
```

Expected: `FAILED` — `ValidationError` (output_path not on TaskContract yet) or assertion error

- [ ] **Step 2.5: Add `output_path` to `TaskContract`**

In `core/contracts/contracts.py`, the `TaskContract` class currently has:

```python
    workspace_root: str | None = None  # set by Andromeda from WorkspaceConfig; None when workspace is disabled
    created_at: datetime = Field(default_factory=utc_now)
```

Replace with:

```python
    workspace_root: str | None = None  # set by Andromeda from WorkspaceConfig; None when workspace is disabled
    output_path: str | None = None     # caller-specified filename; threaded to context when workspace is enabled
    created_at: datetime = Field(default_factory=utc_now)
```

- [ ] **Step 2.6: Update Andromeda `route()` to thread `output_path`**

In `agents/andromeda/orchestrator.py`, the current workspace injection block reads:

```python
        ws = self._workspace_config
        if ws.enabled:
            task = task.model_copy(update={"workspace_root": ws.workspace_root})
            context = {**(context or {}), "workspace_root": ws.workspace_root}
```

Replace with:

```python
        ws = self._workspace_config
        if ws.enabled:
            task = task.model_copy(update={"workspace_root": ws.workspace_root})
            context_update = {"workspace_root": ws.workspace_root}
            if task.output_path is not None:
                context_update["output_path"] = task.output_path
            context = {**(context or {}), **context_update}
```

- [ ] **Step 2.7: Run all Task 2 tests**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/core/test_contracts.py test/workspace/test_workspace_config.py -v
```

Expected: all tests pass (9 contract tests + 9 workspace tests = 18 total).

- [ ] **Step 2.8: Commit**

```bash
git add core/contracts/contracts.py test/core/test_contracts.py \
        agents/andromeda/orchestrator.py test/workspace/test_workspace_config.py
git commit -m "feat: add output_path to TaskContract, thread through Andromeda context"
```

---

## Task 3: Rigel disk-write post-processing

**Files:**
- Modify: `agents/rigel/agent.py`
- Create: `test/agents/test_rigel_workspace.py`

- [ ] **Step 3.1: Write the failing integration test**

Create `test/agents/test_rigel_workspace.py`:

```python
import json
from uuid import uuid4

import pytest

from agents.rigel.agent import RigelAgent
from agents.rigel.config import RigelConfig
from core.pulsar.registry import PulsarRegistry


def _mock_llm(system: str, user: str) -> str:
    if "Rate whether this output fully satisfies the task" in user:
        return json.dumps({"score": 0.85, "gaps": []})
    # code_generation returns raw code (not JSON)
    return "def add(a, b):\n    return a + b\n"


@pytest.fixture
def rigel(tmp_path):
    registry = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    agent = RigelAgent(
        registry,
        rigel_config=RigelConfig(execution_calibration_enabled=False),
    )
    agent.llm = _mock_llm
    return agent


def test_rigel_writes_artifact_to_disk_when_workspace_root_set(rigel, tmp_path):
    ws = str(tmp_path / "project")
    context = {"workspace_root": ws, "task_id": str(uuid4())}

    result = rigel.run(
        "rigel.skill.code_generation",
        {"spec": "create add function", "language": "python"},
        context=context,
    )

    assert "written_artifacts" in result
    assert len(result["written_artifacts"]) >= 1

    artifact = result["written_artifacts"][0]
    assert artifact["absolute_path"]
    assert artifact["size_bytes"] > 0

    import os
    assert os.path.isfile(artifact["absolute_path"])
    # existing in-memory artifacts are preserved
    assert result["artifacts"][0]["content"]


def test_rigel_written_artifacts_empty_when_no_workspace_root(rigel, tmp_path):
    context = {"task_id": str(uuid4())}

    result = rigel.run(
        "rigel.skill.code_generation",
        {"spec": "create add function", "language": "python"},
        context=context,
    )

    assert result["written_artifacts"] == []
    assert result["artifacts"][0]["content"]  # in-memory still present
```

- [ ] **Step 3.2: Run integration tests to confirm they fail**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/agents/test_rigel_workspace.py -v
```

Expected: `FAILED` — `KeyError: 'written_artifacts'` (field not yet in result)

- [ ] **Step 3.3: Add `FileWriter` import to `agents/rigel/agent.py`**

At the top of `agents/rigel/agent.py`, after the existing imports block (after `from core.pulsar.registry import PulsarRegistry`), add:

```python
from workspace.file_writer import FileWriter
```

- [ ] **Step 3.4: Add `_task_description` helper to `agents/rigel/agent.py`**

Near the other module-level private helpers at the bottom of `agents/rigel/agent.py` (after `_EXT_TO_LANGUAGE` dict, before `_normalize_skill_output`), add:

```python
_DESCRIPTION_KEYS: dict[str, str] = {
    "code_generation": "spec",
    "test_writing": "code",
    "refactor": "refactor_intent",
    "scaffold": "project_type",
    "debug_triage": "error_trace",
    "pr_review": "diff",
}


def _task_description(skill_id: str, payload: dict) -> str:
    skill = skill_id.split(".")[-1]
    return payload.get(_DESCRIPTION_KEYS.get(skill, ""), "")
```

- [ ] **Step 3.5: Add workspace post-processing block to `RigelAgent.run()`**

In `agents/rigel/agent.py`, the end of `run()` currently reads:

```python
        task_result = {
            **raw_result,
            "confidence": confidence_data["confidence"],
            "confidence_breakdown": {
                "structural": confidence_data["structural"],
                "self_critique": confidence_data["self_critique"],
                "historical": confidence_data["historical"],
                "soft_confidence": confidence_data["soft_confidence"],
                "execution_outcome": confidence_data["execution_outcome"],
            },
            "gaps": confidence_data["gaps"],
            "execution_result": (
                execution_result.model_dump(mode="python")
                if execution_result is not None
                else None
            ),
            "externally_calibrated": externally_calibrated,
            "artifacts": normalized["artifacts"],
            "summary": normalized["summary"],
            "writable": normalized["writable"],
            **({"skill_confidence": skill_confidence} if skill_confidence is not None else {}),
        }

        self._emit_feedback(
```

Replace the `task_result = {...}` block and the `self._emit_feedback(` line with:

```python
        task_result = {
            **raw_result,
            "confidence": confidence_data["confidence"],
            "confidence_breakdown": {
                "structural": confidence_data["structural"],
                "self_critique": confidence_data["self_critique"],
                "historical": confidence_data["historical"],
                "soft_confidence": confidence_data["soft_confidence"],
                "execution_outcome": confidence_data["execution_outcome"],
            },
            "gaps": confidence_data["gaps"],
            "execution_result": (
                execution_result.model_dump(mode="python")
                if execution_result is not None
                else None
            ),
            "externally_calibrated": externally_calibrated,
            "artifacts": normalized["artifacts"],
            "summary": normalized["summary"],
            "writable": normalized["writable"],
            **({"skill_confidence": skill_confidence} if skill_confidence is not None else {}),
        }

        written_artifacts = []
        if context and context.get("workspace_root") and normalized["writable"]:
            writer = FileWriter(context["workspace_root"])
            for artifact in normalized["artifacts"]:
                if len(normalized["artifacts"]) == 1:
                    filename = context.get("output_path") or writer.infer_filename(
                        _task_description(skill_id, payload), skill_id.split(".")[-1]
                    )
                else:
                    filename = artifact["filename"]
                wa = writer.write(filename, artifact["content"])
                written_artifacts.append(wa.model_dump(mode="python"))
        task_result["written_artifacts"] = written_artifacts

        self._emit_feedback(
```

- [ ] **Step 3.6: Run integration tests**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/agents/test_rigel_workspace.py -v
```

Expected:
```
PASSED test/agents/test_rigel_workspace.py::test_rigel_writes_artifact_to_disk_when_workspace_root_set
PASSED test/agents/test_rigel_workspace.py::test_rigel_written_artifacts_empty_when_no_workspace_root
2 passed
```

- [ ] **Step 3.7: Run full regression**

```bash
cd /Users/rmehra/Projects/galaxz && .venv/bin/pytest test/core/ test/workspace/ test/agents/ -v --ignore=test/UI 2>&1 | tail -10
```

Expected: all tests pass, no regressions.

- [ ] **Step 3.8: Commit**

```bash
git add agents/rigel/agent.py test/agents/test_rigel_workspace.py
git commit -m "feat: write Rigel artifacts to disk when workspace_root is in context"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|-------------|------|
| `WrittenArtifact` model (`filename`, `absolute_path`, `relative_path`, `size_bytes`) | Task 1 |
| `FileWriter.__init__(workspace_root)` | Task 1 |
| `FileWriter.write()` — creates dirs, writes file, returns artifact | Task 1 |
| `FileWriter.infer_filename()` — extension by skill, slug from description, fallback | Task 1 |
| `output_path: str \| None` on `TaskContract` | Task 2 |
| Andromeda threads `output_path` into context when workspace enabled | Task 2 |
| Rigel checks `context["workspace_root"]` + `normalized["writable"]` | Task 3 |
| Single-file: uses `output_path` → falls back to `infer_filename()` | Task 3 |
| Multi-file (scaffold): uses each `artifact["filename"]` | Task 3 |
| `written_artifacts` added to result (separate from `artifacts`) | Task 3 |
| `written_artifacts: []` when workspace not set | Task 3 |
| Test 1: write creates file + valid artifact | Task 1 |
| Test 2: write creates missing parent dirs | Task 1 |
| Test 3: infer_filename returns `.py` file | Task 1 |
| Test 4: infer_filename empty → fallback | Task 1 |
| Test 5: Rigel with workspace_root has non-empty absolute_path in written_artifacts | Task 3 |
| No changes to Vega, Orion, execution sandbox | ✓ Not in file map |
| No git operations | ✓ |

All requirements covered. No placeholders. Types consistent: `WrittenArtifact` defined in Task 1, used by name in Task 3 via `wa.model_dump()`. `FileWriter` defined in Task 1, imported in Task 3. `output_path` defined on `TaskContract` in Task 2, read from `context` in Task 3.
