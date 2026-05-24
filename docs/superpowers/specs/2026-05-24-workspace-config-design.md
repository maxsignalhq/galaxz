# Workspace Config — Design Spec

**Date:** 2026-05-24
**Status:** Approved

---

## Problem

Agents (Rigel in particular) have no knowledge of the developer's local project path. To enable file-aware operations, the platform needs a way to inject a `workspace_root` into the task routing envelope so every downstream agent can access it without needing separate configuration.

---

## Scope

This spec covers three things:

1. A YAML config file + loader module (`workspace/config.py`) that reads whether workspace mode is enabled and what path to use.
2. An optional `workspace_root` field on `TaskContract`, and wiring in `Andromeda.route()` to populate it from config.
3. Tests covering the loader validation rules and the Andromeda routing integration.

**Out of scope for this prompt:**
- Agent-side consumption of `workspace_root` (Rigel, Vega are not touched)
- Adding `workspace_root` to the Aether/Refinery event schema
- Any file I/O by agents

---

## Part A — Config File + Loader

### `config/workspace.yaml`

```yaml
workspace_root: ""  # absolute path to the developer's project
enabled: false       # opt-in; false = previous behaviour preserved
```

Workspace mode is off by default. Developers set `enabled: true` and provide an absolute path before any agent uses it.

### `workspace/config.py`

**Model:**

```python
class WorkspaceConfig(BaseModel):
    workspace_root: str
    enabled: bool
```

**Loader:** `load_workspace_config(config_path: str = "config/workspace.yaml") -> WorkspaceConfig`

| Condition | Behaviour |
|-----------|-----------|
| File missing | Return `WorkspaceConfig(workspace_root="", enabled=False)` — no exception |
| `enabled: false` | Return config as-is, no path validation |
| `enabled: true`, `workspace_root` empty | Raise `ValueError("workspace_root must not be empty when workspace is enabled")` |
| `enabled: true`, path does not exist on disk | Raise `ValueError("workspace_root does not exist: <path>")` |
| `enabled: true`, valid path | Return config |

Pattern follows `core/llm/provider.py`: plain Pydantic v2 BaseModel + `yaml.safe_load`. No `pydantic_settings` dependency.

---

## Part B — TaskContract Field + Andromeda Wiring

### `core/contracts/contracts.py`

Add one optional field to `TaskContract`:

```python
workspace_root: str | None = None
```

No validator needed — it is populated by the platform, not by callers.

### `agents/andromeda/orchestrator.py` — `Andromeda.route()`

After the `task` object is resolved (passed in or constructed from legacy params), and before `initial_state` is built:

```python
ws = load_workspace_config()
if ws.enabled:
    task = task.model_copy(update={"workspace_root": ws.workspace_root})
    context = {**(context or {}), "workspace_root": ws.workspace_root}
```

Two things happen when workspace is enabled:
- `task.workspace_root` is set on the contract (immutable copy, consistent with `transition_status()` pattern).
- `context["workspace_root"]` is set so it flows into `AndromedaState.context` and is visible to every downstream agent without agents needing to read the contract directly.

When `enabled: false`, no mutation occurs — `context` and `task` are untouched, preserving existing behaviour exactly.

---

## Part C — Tests

**File:** `test/workspace/test_workspace_config.py`

| # | Scenario | Assertion |
|---|----------|-----------|
| 1 | `WorkspaceConfig(enabled=False, workspace_root="")` constructed directly | No error |
| 2 | `load_workspace_config()` with temp YAML, `enabled: true`, valid path | Returns config with correct values |
| 3 | `load_workspace_config()` with temp YAML, `enabled: true`, non-existent path | Raises `ValueError` |
| 4 | `Andromeda.route()` with workspace enabled (monkeypatched loader) | Returned state dict has `context["workspace_root"]` set to expected path |

Test 4 uses `monkeypatch` to inject a known `WorkspaceConfig` — no real YAML file or real Andromeda graph execution required for the workspace assertion. The mock agent returns a minimal valid result so routing completes.

---

## File Locations

| File | Action |
|------|--------|
| `config/workspace.yaml` | Create |
| `workspace/__init__.py` | Create |
| `workspace/config.py` | Create |
| `core/contracts/contracts.py` | Edit — add `workspace_root` field |
| `agents/andromeda/orchestrator.py` | Edit — wire `load_workspace_config()` in `route()` |
| `test/workspace/__init__.py` | Create |
| `test/workspace/test_workspace_config.py` | Create |
