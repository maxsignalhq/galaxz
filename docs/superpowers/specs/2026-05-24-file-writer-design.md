# FileWriter + Rigel Disk-Write Integration — Design Spec

**Date:** 2026-05-24
**Status:** Approved

---

## Problem

Rigel generates code as in-memory strings. When `workspace_root` is set on a `TaskContract`, those artifacts should be written to the developer's project on disk. The in-memory artifacts (with `content`) must be preserved unchanged for the UI; a separate disk-write receipt is added alongside.

---

## Scope

1. `output_path: str | None` field on `TaskContract`, threaded through context by Andromeda alongside `workspace_root`
2. `workspace/file_writer.py` — `WrittenArtifact` model + `FileWriter` class
3. Rigel `run()` post-processing — write artifacts when `workspace_root` is in context, add `written_artifacts` to result
4. Tests: 4 unit tests for `FileWriter`, 1 Rigel integration test

**Out of scope:**
- Execution sandbox interaction
- Git operations
- Vega, Andromeda, Orion changes (beyond `output_path` threading in Andromeda)

---

## Part 0 — Contract + Andromeda

### `core/contracts/contracts.py`

Add one field to `TaskContract`:

```python
output_path: str | None = None  # caller-specified filename; threaded to context when workspace is enabled
```

### `agents/andromeda/orchestrator.py` — `Andromeda.route()`

Inside the existing `if ws.enabled:` block, thread `output_path` alongside `workspace_root`:

```python
if ws.enabled:
    task = task.model_copy(update={"workspace_root": ws.workspace_root})
    context_update = {"workspace_root": ws.workspace_root}
    if task.output_path is not None:
        context_update["output_path"] = task.output_path
    context = {**(context or {}), **context_update}
```

`output_path` is only placed in context when workspace is enabled — it has no meaning without a filesystem target.

---

## Part A — `workspace/file_writer.py`

> File lives at `workspace/file_writer.py` (the existing `workspace/` module at the project root — not `galaxz/workspace/`).

### `WrittenArtifact`

```python
class WrittenArtifact(BaseModel):
    filename: str
    absolute_path: str
    relative_path: str   # relative to workspace_root
    size_bytes: int
```

### `FileWriter`

**`__init__(workspace_root: str)`** — stores root as `Path`. No existence check (the loader already validated it at config time).

**`write(filename: str, content: str) -> WrittenArtifact`**
- Resolves full path as `Path(workspace_root) / filename`
- `path.parent.mkdir(parents=True, exist_ok=True)`
- Writes UTF-8 content
- Returns `WrittenArtifact(filename=filename, absolute_path=str(full_path), relative_path=filename, size_bytes=len(content.encode()))`

**`infer_filename(task_description: str, skill: str) -> str`**

Skill-to-extension map:
| Skill | Extension / Pattern |
|-------|---------------------|
| `code_generation` | `{slug}.py` |
| `test_writing` | `test_{slug}.py` (or `test_.py` if slug is empty, then fallback applies) |
| `refactor` | `{slug}.py` |
| anything else | `{slug}.py` |

Slug algorithm:
1. Lowercase the description
2. Remove stop words: `a, an, the, to, for, of, in, on, at, with, and, or, is, are, that, this, it, be, as, by, from, into`
3. Strip non-alphanumeric characters (keep letters, digits)
4. Split on whitespace, join with `_`
5. Truncate to 40 characters
6. If slug is empty → fallback: `output_{skill}.py` (e.g. `output_test_writing.py`)

---

## Part B — Rigel Wiring

In `RigelAgent.run()`, add a post-processing block after `task_result` is built and before returning.

```python
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
```

Rules:
- `writable: False` skills (`debug_triage`, `pr_review`) → `written_artifacts` is always `[]`
- Scaffold (multi-file) → each artifact uses its own `artifact["filename"]` from `_normalize_skill_output`
- Single-file skills → `output_path` from context takes priority; falls back to `infer_filename()`
- `FileWriter` imported from `workspace.file_writer`

### `_task_description(skill_id: str, payload: dict) -> str` (module-level private helper)

Extracts the best human-readable description from the payload for filename inference:

| Skill | Key |
|-------|-----|
| `code_generation` | `payload.get("spec", "")` |
| `test_writing` | `payload.get("code", "")` |
| `refactor` | `payload.get("refactor_intent", "")` |
| `scaffold` | `payload.get("project_type", "")` |
| `debug_triage` | `payload.get("error_trace", "")` |
| `pr_review` | `payload.get("diff", "")` |
| fallback | `""` |

---

## Part C — Tests

### `test/workspace/test_file_writer.py`

| # | Test | Assertion |
|---|------|-----------|
| 1 | `write()` basic | File exists at `absolute_path`; `WrittenArtifact` has correct `filename`, `absolute_path`, `relative_path`, `size_bytes > 0` |
| 2 | `write()` nested path | `subdir/foo.py` creates parent dir; no error; file readable |
| 3 | `infer_filename("create a weather app", "code_generation")` | Result ends with `.py`; not empty |
| 4 | `infer_filename("", "test_writing")` | Returns `"output_test_writing.py"` (fallback, not empty string) |

### `test/agents/test_rigel_workspace.py`

| # | Test | Assertion |
|---|------|-----------|
| 5 | Rigel `run()` with `workspace_root` in context | `written_artifacts` has ≥ 1 entry; `absolute_path` is non-empty; file exists on disk at that path |

Test 5 setup:
- `tmp_path` from pytest
- Patch `agent.llm` with deterministic mock (same pattern as `deterministic_rigel_llm` fixture in existing agent tests)
- Call `agent.run("rigel.skill.code_generation", {"spec": "create add function", "language": "python"}, context={"workspace_root": str(tmp_path), "task_id": str(uuid4())})`

---

## File Map

| Action | Path |
|--------|------|
| Modify | `core/contracts/contracts.py` |
| Modify | `agents/andromeda/orchestrator.py` |
| Create | `workspace/file_writer.py` |
| Create | `test/workspace/test_file_writer.py` |
| Create | `test/agents/test_rigel_workspace.py` |
| Modify | `agents/rigel/agent.py` |
