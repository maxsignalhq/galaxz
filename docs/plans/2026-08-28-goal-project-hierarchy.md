# Goal / Project Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a caller submit one natural-language objective and have Andromeda decompose it into a `Goal → Project → Task` DAG, execute the tasks in dependency order, escalate failures to the existing review queue, and report rolled-up status.

**Architecture:** A planning-and-execution layer sits *above* `Andromeda.route()`, not inside the LangGraph routing graph. `GoalPlanner` makes one LLM call to turn an objective into projects and tasks with `depends_on` edges. `GoalStore` (SQLite) persists the tree. `GoalRunner` walks the DAG on a daemon thread, calling `Andromeda.route()` once per task with a normal `TaskContract`, pausing the goal and enqueuing to `ReviewQueue` on any failure or sub-threshold result. Four HTTP endpoints and a Prism page expose it.

**Tech Stack:** Python 3, Pydantic v2, `sqlite3` (stdlib), FastAPI, `litellm` via `core/llm/provider.call_llm`, React 18 + Vite + TypeScript (Prism), `pytest` / `pytest-asyncio`.

**Spec:** `docs/specs/2026-08-28-goal-project-hierarchy-design.md`

## Global Constraints

- Pydantic models are **v2 `BaseModel`, immutable in spirit** — never mutate in place; return new instances. Match `core/contracts/contracts.py` conventions (`Field(default_factory=...)`, `field_validator`, `utc_now`).
- Every agent/task output already carries a confidence float — do not remove or bypass that. The goal layer only *composes* `TaskContract`s; it never bypasses a contract.
- New SQLite DBs live under `data/` (already covered by `.gitignore`'s `data/*.db` and `*.db`). Every store constructor takes a `db_path` / `db_url` argument so tests pass an isolated `tmp_path`. Open connections with `check_same_thread=False`.
- Skill ids are validated against `{s.skill_id for s in registry.get_all_skills()}` — the method is `get_all_skills()`, not `list_skills()`.
- New HTTP routes are **protected** — do not add them to `_EXEMPT_ROUTES` in `agents/andromeda/middleware/auth.py`.
- One logical change per commit. TDD: failing test first, then minimal code.
- Do not reformat or refactor adjacent code. Touch only what each task needs.
- Deviation from spec, intentional: `GoalStore` uses stdlib `sqlite3` directly (like `core/artifacts/store.py` and `agents/andromeda/review_queue.py`), **not** Pulsar's `_DbConnection`. Postgres support is a later swap; YAGNI now.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `core/contracts/contracts.py` (modify) | Add `GoalStatus`, `PlannedTaskStatus`, `GoalContract`, `ProjectNode`, `PlannedTask` |
| `core/contracts/__init__.py` (modify) | Export the five new names |
| `core/goals/__init__.py` (create) | Package marker, re-export `GoalStore` |
| `core/goals/store.py` (create) | SQLite persistence: goals / projects / tasks tables, tree read, rollup, guarded status transition |
| `agents/andromeda/planner.py` (create) | `GoalPlanner` — one LLM call, schema injection, plan validation (unknown skill, cycle, bad index), `PlanResult` |
| `agents/andromeda/goal_runner.py` (create) | `GoalRunner` — DAG walk, per-task `route()`, escalate/pause, resume |
| `agents/andromeda/orchestrator.py` (modify) | Construct `goal_store` / `goal_planner` / `goal_runner` in `Andromeda.__init__` |
| `agents/andromeda/review_queue.py` (modify) | Add nullable `goal_id` column via `_MIGRATE_STMTS`; `enqueue(..., goal_id=None)`; `_COLUMNS` update |
| `services/andromeda_service.py` (modify) | `GoalRequest` model, 4 endpoints, `goal_id` resume hook in approve/reject |
| `prism/src/pages/Goals.tsx` (create) | Submit objective, render tree, poll, resume |
| `prism/src/App.tsx` (modify) | Route `/goals` |
| `prism/src/components/Sidebar.tsx` (modify) | Nav entry `goals` |
| `test/goals/test_goal_store.py` (create) | Store unit tests |
| `test/goals/test_goal_planner.py` (create) | Planner unit tests (stubbed LLM) |
| `test/goals/test_goal_runner.py` (create) | Runner unit tests (fake Andromeda) |
| `test/api/test_goals_api.py` (create) | Endpoint tests |
| `evals/run_evals.py` (modify) | One deterministic goal scenario |
| `CLAUDE.md` (modify) | Document the new contracts (section becomes four) |

---

## Task 1: Contracts

**Files:**
- Modify: `core/contracts/contracts.py`
- Modify: `core/contracts/__init__.py`
- Test: `test/goals/test_contracts_goals.py`

**Interfaces:**
- Produces:
  - `GoalStatus = Literal["planning","ready","running","paused","complete","failed"]`
  - `PlannedTaskStatus = Literal["pending","running","complete","failed","escalated"]`
  - `GoalContract(goal_id: UUID, origin: str, objective: str, confidence_threshold: float, status: GoalStatus="planning", plan_confidence: float|None=None, created_at: datetime)`
  - `ProjectNode(project_id: UUID, goal_id: UUID, title: str, description: str="")`
  - `PlannedTask(task_id: UUID, project_id: UUID, goal_id: UUID, skill: str, payload: dict, depends_on: list[UUID]=[], status: PlannedTaskStatus="pending", confidence: float|None=None, result: dict|None=None, error: str|None=None)`

- [ ] **Step 1: Write the failing test**

```python
# test/goals/test_contracts_goals.py
import uuid
import pytest
from pydantic import ValidationError
from core.contracts import GoalContract, ProjectNode, PlannedTask


def test_goal_contract_defaults():
    g = GoalContract(origin="test", objective="build a todo API", confidence_threshold=0.65)
    assert g.status == "planning"
    assert g.plan_confidence is None
    assert isinstance(g.goal_id, uuid.UUID)
    assert g.created_at is not None


def test_goal_contract_rejects_blank_objective():
    with pytest.raises(ValidationError):
        GoalContract(origin="test", objective="   ", confidence_threshold=0.65)


def test_goal_contract_threshold_bounds():
    with pytest.raises(ValidationError):
        GoalContract(origin="t", objective="x", confidence_threshold=1.5)


def test_planned_task_defaults():
    gid, pid = uuid.uuid4(), uuid.uuid4()
    t = PlannedTask(project_id=pid, goal_id=gid, skill="rigel.skill.code_generation", payload={"spec": "x"})
    assert t.status == "pending"
    assert t.depends_on == []
    assert t.confidence is None


def test_project_node_defaults():
    p = ProjectNode(goal_id=uuid.uuid4(), title="API layer")
    assert p.description == ""
    assert isinstance(p.project_id, uuid.UUID)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/goals/test_contracts_goals.py -v`
Expected: FAIL — `ImportError: cannot import name 'GoalContract'`

- [ ] **Step 3: Add the models to `core/contracts/contracts.py`**

Append after the existing `TaskContract` block (keep imports — `Literal`, `UUID`, `uuid4`, `Field`, `field_validator`, `datetime`, `utc_now` are already imported):

```python
GoalStatus = Literal["planning", "ready", "running", "paused", "complete", "failed"]
PlannedTaskStatus = Literal["pending", "running", "complete", "failed", "escalated"]


class GoalContract(BaseModel):
    goal_id: UUID = Field(default_factory=uuid4)
    origin: str
    objective: str
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    status: GoalStatus = "planning"
    plan_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("origin", "objective")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class ProjectNode(BaseModel):
    project_id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    title: str
    description: str = ""

    @field_validator("title")
    @classmethod
    def _non_empty_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class PlannedTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    goal_id: UUID
    skill: str
    payload: dict
    depends_on: list[UUID] = Field(default_factory=list)
    status: PlannedTaskStatus = "pending"
    confidence: float | None = None
    result: dict | None = None
    error: str | None = None
```

- [ ] **Step 4: Export from `core/contracts/__init__.py`**

Add `GoalContract`, `ProjectNode`, `PlannedTask`, `GoalStatus`, `PlannedTaskStatus` to both the `from .contracts import (...)` list and `__all__`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest test/goals/test_contracts_goals.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Full suite still green**

Run: `python -m pytest -q`
Expected: `135 passed, 5 skipped` (130 prior + 5 new)

- [ ] **Step 7: Commit**

```bash
git add core/contracts/contracts.py core/contracts/__init__.py test/goals/test_contracts_goals.py
git commit -m "feat: add GoalContract, ProjectNode, PlannedTask contracts"
```

---

## Task 2: GoalStore — persistence

**Files:**
- Create: `core/goals/__init__.py`
- Create: `core/goals/store.py`
- Test: `test/goals/test_goal_store.py`

**Interfaces:**
- Consumes: `GoalContract`, `ProjectNode`, `PlannedTask` from Task 1.
- Produces:
  - `GoalStore(db_path: str = "data/goals.db")`
  - `.create_goal(goal: GoalContract) -> None`
  - `.save_plan(goal_id: UUID, projects: list[ProjectNode], tasks: list[PlannedTask], plan_confidence: float, gated: bool) -> None` — inserts projects+tasks, sets `goals.plan_confidence`, and sets `goals.status` to `"paused"` if `gated` else `"ready"`.
  - `.get_goal(goal_id: UUID) -> GoalContract | None`
  - `.list_goals() -> list[GoalContract]` — newest `created_at` first
  - `.goal_tree(goal_id: UUID) -> dict` — `{"goal": {...}, "projects": [{...project, "tasks": [{...task}]}]}` (UUIDs as `str`, `depends_on` as `list[str]`)
  - `.get_tasks(goal_id: UUID) -> list[PlannedTask]`
  - `.update_task(task_id: UUID, **fields) -> None` — allowed keys: `status`, `confidence`, `result`, `error`
  - `.set_goal_status(goal_id: UUID, status: str) -> None`
  - `.try_claim(goal_id: UUID) -> bool` — compare-and-set `status IN ('ready','paused') -> 'running'`; returns whether it won
  - `.rollup(goal_id: UUID) -> dict` — `{"status": str, "completed": int, "total": int, "min_confidence": float | None}`

- [ ] **Step 1: Write the failing test**

```python
# test/goals/test_goal_store.py
import uuid
import pytest
from core.contracts import GoalContract, ProjectNode, PlannedTask
from core.goals.store import GoalStore


@pytest.fixture
def store(tmp_path):
    return GoalStore(db_path=str(tmp_path / "goals.db"))


def _goal():
    return GoalContract(origin="test", objective="build X", confidence_threshold=0.65)


def _plan(goal_id):
    p = ProjectNode(goal_id=goal_id, title="proj")
    t1 = PlannedTask(project_id=p.project_id, goal_id=goal_id, skill="s.a", payload={})
    t2 = PlannedTask(project_id=p.project_id, goal_id=goal_id, skill="s.b", payload={}, depends_on=[t1.task_id])
    return [p], [t1, t2]


def test_create_and_get_goal(store):
    g = _goal()
    store.create_goal(g)
    got = store.get_goal(g.goal_id)
    assert got is not None
    assert got.objective == "build X"
    assert got.status == "planning"


def test_save_plan_sets_ready_and_confidence(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    got = store.get_goal(g.goal_id)
    assert got.status == "ready"
    assert got.plan_confidence == 0.8
    tree = store.goal_tree(g.goal_id)
    assert len(tree["projects"]) == 1
    assert len(tree["projects"][0]["tasks"]) == 2
    assert tree["projects"][0]["tasks"][1]["depends_on"] == [str(tasks[0].task_id)]


def test_save_plan_gated_sets_paused(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.3, gated=True)
    assert store.get_goal(g.goal_id).status == "paused"


def test_update_task_and_rollup(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    store.update_task(tasks[0].task_id, status="complete", confidence=0.9)
    store.update_task(tasks[1].task_id, status="complete", confidence=0.7)
    r = store.rollup(g.goal_id)
    assert r == {"status": "ready", "completed": 2, "total": 2, "min_confidence": 0.7}


def test_try_claim_is_single_winner(store):
    g = _goal()
    store.create_goal(g)
    projects, tasks = _plan(g.goal_id)
    store.save_plan(g.goal_id, projects, tasks, plan_confidence=0.8, gated=False)
    assert store.try_claim(g.goal_id) is True
    assert store.try_claim(g.goal_id) is False  # already running
    assert store.get_goal(g.goal_id).status == "running"


def test_list_goals_newest_first(store):
    a, b = _goal(), _goal()
    store.create_goal(a)
    store.create_goal(b)
    ids = [g.goal_id for g in store.list_goals()]
    assert set(ids) == {a.goal_id, b.goal_id}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/goals/test_goal_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.goals'`

- [ ] **Step 3: Create `core/goals/__init__.py`**

```python
from core.goals.store import GoalStore

__all__ = ["GoalStore"]
```

- [ ] **Step 4: Create `core/goals/store.py`**

```python
from __future__ import annotations

import json
import os
import sqlite3
import threading
from uuid import UUID

from core.contracts import GoalContract, PlannedTask, ProjectNode

_CREATE_GOALS = """
CREATE TABLE IF NOT EXISTS goals (
    goal_id              TEXT PRIMARY KEY,
    origin               TEXT NOT NULL,
    objective            TEXT NOT NULL,
    confidence_threshold REAL NOT NULL,
    status               TEXT NOT NULL,
    plan_confidence      REAL,
    created_at           TEXT NOT NULL
)
"""

_CREATE_PROJECTS = """
CREATE TABLE IF NOT EXISTS projects (
    project_id  TEXT PRIMARY KEY,
    goal_id     TEXT NOT NULL,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    ordinal     INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_TASKS = """
CREATE TABLE IF NOT EXISTS planned_tasks (
    task_id         TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL,
    goal_id         TEXT NOT NULL,
    skill           TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    depends_on_json TEXT NOT NULL DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'pending',
    confidence      REAL,
    result_json     TEXT,
    error           TEXT,
    ordinal         INTEGER NOT NULL DEFAULT 0
)
"""

_UPDATABLE_TASK_FIELDS = {"status", "confidence", "result", "error"}


class GoalStore:
    def __init__(self, db_path: str = "data/goals.db"):
        self._lock = threading.Lock()
        dirname = os.path.dirname(db_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        for ddl in (_CREATE_GOALS, _CREATE_PROJECTS, _CREATE_TASKS):
            self._conn.execute(ddl)
        self._conn.commit()

    # ---- goals -----------------------------------------------------------
    def create_goal(self, goal: GoalContract) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO goals (goal_id, origin, objective, confidence_threshold, "
                "status, plan_confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(goal.goal_id), goal.origin, goal.objective,
                    goal.confidence_threshold, goal.status, goal.plan_confidence,
                    goal.created_at.isoformat(),
                ),
            )
            self._conn.commit()

    def get_goal(self, goal_id: UUID) -> GoalContract | None:
        cur = self._conn.execute("SELECT * FROM goals WHERE goal_id = ?", (str(goal_id),))
        row = cur.fetchone()
        if row is None:
            return None
        return GoalContract(
            goal_id=UUID(row["goal_id"]),
            origin=row["origin"],
            objective=row["objective"],
            confidence_threshold=row["confidence_threshold"],
            status=row["status"],
            plan_confidence=row["plan_confidence"],
            created_at=row["created_at"],
        )

    def list_goals(self) -> list[GoalContract]:
        cur = self._conn.execute("SELECT goal_id FROM goals ORDER BY created_at DESC, rowid DESC")
        return [self.get_goal(UUID(r["goal_id"])) for r in cur.fetchall()]

    def set_goal_status(self, goal_id: UUID, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE goals SET status = ? WHERE goal_id = ?", (status, str(goal_id))
            )
            self._conn.commit()

    def try_claim(self, goal_id: UUID) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE goals SET status = 'running' "
                "WHERE goal_id = ? AND status IN ('ready', 'paused')",
                (str(goal_id),),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ---- plan -----------------------------------------------------------
    def save_plan(
        self,
        goal_id: UUID,
        projects: list[ProjectNode],
        tasks: list[PlannedTask],
        plan_confidence: float,
        gated: bool,
    ) -> None:
        with self._lock:
            for i, p in enumerate(projects):
                self._conn.execute(
                    "INSERT INTO projects (project_id, goal_id, title, description, ordinal) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(p.project_id), str(p.goal_id), p.title, p.description, i),
                )
            for i, t in enumerate(tasks):
                self._conn.execute(
                    "INSERT INTO planned_tasks (task_id, project_id, goal_id, skill, "
                    "payload_json, depends_on_json, status, confidence, result_json, error, ordinal) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(t.task_id), str(t.project_id), str(t.goal_id), t.skill,
                        json.dumps(t.payload), json.dumps([str(d) for d in t.depends_on]),
                        t.status, t.confidence,
                        json.dumps(t.result) if t.result is not None else None,
                        t.error, i,
                    ),
                )
            self._conn.execute(
                "UPDATE goals SET plan_confidence = ?, status = ? WHERE goal_id = ?",
                (plan_confidence, "paused" if gated else "ready", str(goal_id)),
            )
            self._conn.commit()

    # ---- tasks ---------------------------------------------------------
    def _row_to_task(self, row: sqlite3.Row) -> PlannedTask:
        return PlannedTask(
            task_id=UUID(row["task_id"]),
            project_id=UUID(row["project_id"]),
            goal_id=UUID(row["goal_id"]),
            skill=row["skill"],
            payload=json.loads(row["payload_json"]),
            depends_on=[UUID(d) for d in json.loads(row["depends_on_json"])],
            status=row["status"],
            confidence=row["confidence"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"],
        )

    def get_tasks(self, goal_id: UUID) -> list[PlannedTask]:
        cur = self._conn.execute(
            "SELECT * FROM planned_tasks WHERE goal_id = ? ORDER BY ordinal", (str(goal_id),)
        )
        return [self._row_to_task(r) for r in cur.fetchall()]

    def update_task(self, task_id: UUID, **fields) -> None:
        bad = set(fields) - _UPDATABLE_TASK_FIELDS
        if bad:
            raise ValueError(f"cannot update task fields: {bad}")
        col_map = {"result": "result_json"}
        sets, params = [], []
        for key, value in fields.items():
            sets.append(f"{col_map.get(key, key)} = ?")
            if key == "result":
                params.append(json.dumps(value) if value is not None else None)
            else:
                params.append(value)
        params.append(str(task_id))
        with self._lock:
            self._conn.execute(
                f"UPDATE planned_tasks SET {', '.join(sets)} WHERE task_id = ?", params
            )
            self._conn.commit()

    # ---- read models -------------------------------------------------
    def goal_tree(self, goal_id: UUID) -> dict:
        goal = self.get_goal(goal_id)
        if goal is None:
            raise KeyError(f"no goal {goal_id}")
        tasks_by_project: dict[str, list[dict]] = {}
        for t in self.get_tasks(goal_id):
            tasks_by_project.setdefault(str(t.project_id), []).append(
                {
                    "task_id": str(t.task_id),
                    "project_id": str(t.project_id),
                    "goal_id": str(t.goal_id),
                    "skill": t.skill,
                    "payload": t.payload,
                    "depends_on": [str(d) for d in t.depends_on],
                    "status": t.status,
                    "confidence": t.confidence,
                    "result": t.result,
                    "error": t.error,
                }
            )
        pcur = self._conn.execute(
            "SELECT * FROM projects WHERE goal_id = ? ORDER BY ordinal", (str(goal_id),)
        )
        projects = [
            {
                "project_id": pr["project_id"],
                "goal_id": pr["goal_id"],
                "title": pr["title"],
                "description": pr["description"],
                "tasks": tasks_by_project.get(pr["project_id"], []),
            }
            for pr in pcur.fetchall()
        ]
        return {
            "goal": {
                "goal_id": str(goal.goal_id),
                "origin": goal.origin,
                "objective": goal.objective,
                "confidence_threshold": goal.confidence_threshold,
                "status": goal.status,
                "plan_confidence": goal.plan_confidence,
                "created_at": goal.created_at.isoformat(),
            },
            "projects": projects,
        }

    def rollup(self, goal_id: UUID) -> dict:
        tasks = self.get_tasks(goal_id)
        goal = self.get_goal(goal_id)
        confidences = [t.confidence for t in tasks if t.confidence is not None]
        return {
            "status": goal.status if goal else "unknown",
            "completed": sum(1 for t in tasks if t.status == "complete"),
            "total": len(tasks),
            "min_confidence": min(confidences) if confidences else None,
        }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest test/goals/test_goal_store.py -v`
Expected: PASS (7 passed)

- [ ] **Step 6: Commit**

```bash
git add core/goals/ test/goals/test_goal_store.py
git commit -m "feat: add GoalStore for goal/project/task persistence"
```

---

## Task 3: GoalPlanner

**Files:**
- Create: `agents/andromeda/planner.py`
- Test: `test/goals/test_goal_planner.py`

**Interfaces:**
- Consumes: `GoalContract`, `ProjectNode`, `PlannedTask`; `PulsarRegistry.get_all_skills()`; `core.llm.provider.call_llm` (signature `call_llm(messages: list[dict], config: ProviderConfig, system_prompt: str="") -> tuple[str, int, int]`), `load_provider_config()`.
- Produces:
  - `PlanValidationError(Exception)`
  - `PlanResult` — dataclass with `.projects: list[ProjectNode]`, `.tasks: list[PlannedTask]`, `.plan_confidence: float`
  - `GoalPlanner(registry, llm=call_llm, config_loader=load_provider_config)`
  - `.plan(goal: GoalContract) -> PlanResult`

The LLM is expected to return JSON of shape:
```json
{
  "plan_confidence": 0.82,
  "projects": [
    {"title": "API layer", "description": "...",
     "tasks": [
       {"skill": "rigel.skill.code_generation", "payload": {"spec": "...", "language": "python"}, "depends_on": []},
       {"skill": "rigel.skill.write_tests_placeholder", "payload": {...}, "depends_on": [0]}
     ]}
  ]
}
```
`depends_on` entries are integer indices into the **flattened** task list (project order, then task order within project).

- [ ] **Step 1: Write the failing test**

```python
# test/goals/test_goal_planner.py
import json
import pytest
from core.contracts import GoalContract
from core.pulsar.registry import PulsarRegistry
from core.contracts import SkillDefinition, SkillManifest
from agents.andromeda.planner import GoalPlanner, PlanValidationError


@pytest.fixture
def registry(tmp_path):
    r = PulsarRegistry(db_path=str(tmp_path / "pulsar.db"))
    r.register(SkillManifest(
        agent_id="rigel", agent_name="Rigel", version="1.0.0",
        skills=[
            SkillDefinition(skill_id="rigel.skill.code_generation", description="gen code", input_schema={}, output_schema={}),
            SkillDefinition(skill_id="rigel.skill.test_writing", description="write tests", input_schema={}, output_schema={}),
        ],
        health_endpoint="/health",
    ))
    return r


def _planner(registry, payload: dict):
    def fake_llm(messages, config, system_prompt=""):
        return json.dumps(payload), 0, 0
    return GoalPlanner(registry, llm=fake_llm, config_loader=lambda: object())


def _goal():
    return GoalContract(origin="test", objective="build a todo API with tests", confidence_threshold=0.65)


def test_plan_resolves_dependency_indices_to_uuids(registry):
    payload = {
        "plan_confidence": 0.8,
        "projects": [{
            "title": "API", "description": "",
            "tasks": [
                {"skill": "rigel.skill.code_generation", "payload": {"spec": "todo API"}, "depends_on": []},
                {"skill": "rigel.skill.test_writing", "payload": {"code": "..."}, "depends_on": [0]},
            ],
        }],
    }
    result = _planner(registry, payload).plan(_goal())
    assert result.plan_confidence == 0.8
    assert len(result.tasks) == 2
    assert result.tasks[1].depends_on == [result.tasks[0].task_id]
    assert result.tasks[0].goal_id == result.tasks[1].goal_id


def test_plan_rejects_unknown_skill(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "nope.skill.unknown", "payload": {}, "depends_on": []}]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_rejects_out_of_range_dependency(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": [5]}]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_rejects_cycle(registry):
    payload = {"plan_confidence": 0.9, "projects": [{"title": "x", "description": "",
        "tasks": [
            {"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": [1]},
            {"skill": "rigel.skill.test_writing", "payload": {}, "depends_on": [0]},
        ]}]}
    with pytest.raises(PlanValidationError):
        _planner(registry, payload).plan(_goal())


def test_plan_defaults_missing_confidence_to_half(registry):
    payload = {"projects": [{"title": "x", "description": "",
        "tasks": [{"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": []}]}]}
    assert _planner(registry, payload).plan(_goal()).plan_confidence == 0.5


def test_plan_handles_fenced_json(registry):
    payload_str = "```json\n" + json.dumps({
        "plan_confidence": 0.7,
        "projects": [{"title": "x", "description": "", "tasks": [
            {"skill": "rigel.skill.code_generation", "payload": {}, "depends_on": []}]}],
    }) + "\n```"
    def fake_llm(messages, config, system_prompt=""):
        return payload_str, 0, 0
    planner = GoalPlanner(registry, llm=fake_llm, config_loader=lambda: object())
    assert planner.plan(_goal()).plan_confidence == 0.7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/goals/test_goal_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.andromeda.planner'`

- [ ] **Step 3: Create `agents/andromeda/planner.py`**

```python
from __future__ import annotations

import json
from dataclasses import dataclass

from core.contracts import GoalContract, PlannedTask, ProjectNode
from core.llm.provider import call_llm, load_provider_config

_SYSTEM_PROMPT = (
    "You are Andromeda's goal planner. Decompose the user's objective into a small "
    "set of projects, each containing concrete tasks. Every task must target exactly "
    "one of the registered skills listed below, with a payload matching that skill's "
    "input. Express ordering with `depends_on`: a list of integer indices into the "
    "flattened task list (projects in order, tasks in order within each project). "
    "Keep the plan minimal — no speculative work. Respond with ONLY a JSON object:\n"
    '{"plan_confidence": <0..1>, "projects": [{"title": str, "description": str, '
    '"tasks": [{"skill": str, "payload": object, "depends_on": [int]}]}]}'
)


class PlanValidationError(Exception):
    pass


@dataclass
class PlanResult:
    projects: list[ProjectNode]
    tasks: list[PlannedTask]
    plan_confidence: float


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        return "\n".join(body).strip()
    return text


def _has_cycle(edges: dict[int, list[int]], n: int) -> bool:
    WHITE, GREY, BLACK = 0, 1, 2
    color = [WHITE] * n

    def visit(u: int) -> bool:
        color[u] = GREY
        for v in edges.get(u, []):
            if color[v] == GREY:
                return True
            if color[v] == WHITE and visit(v):
                return True
        color[u] = BLACK
        return False

    return any(color[i] == WHITE and visit(i) for i in range(n))


class GoalPlanner:
    def __init__(self, registry, llm=call_llm, config_loader=load_provider_config):
        self._registry = registry
        self._llm = llm
        self._config_loader = config_loader

    def _known_skills(self) -> set[str]:
        return {s.skill_id for s in self._registry.get_all_skills()}

    def plan(self, goal: GoalContract) -> PlanResult:
        known = self._known_skills()
        skill_hint = "\n".join(
            f"- {s.skill_id}: {s.description}" for s in self._registry.get_all_skills()
        )
        user_msg = (
            f"Objective:\n{goal.objective}\n\nRegistered skills:\n{skill_hint}"
        )
        config = self._config_loader()
        raw, _, _ = self._llm(
            [{"role": "user", "content": user_msg}], config, system_prompt=_SYSTEM_PROMPT
        )
        try:
            data = json.loads(_strip_fence(raw))
        except json.JSONDecodeError as e:
            raise PlanValidationError(f"planner returned non-JSON: {e}") from e

        raw_projects = data.get("projects")
        if not isinstance(raw_projects, list) or not raw_projects:
            raise PlanValidationError("plan has no projects")

        plan_confidence = data.get("plan_confidence", 0.5)
        try:
            plan_confidence = max(0.0, min(1.0, float(plan_confidence)))
        except (TypeError, ValueError):
            plan_confidence = 0.5

        projects: list[ProjectNode] = []
        flat_specs: list[dict] = []          # {"project_idx": int, "skill", "payload", "depends_on"}
        for rp in raw_projects:
            proj = ProjectNode(
                goal_id=goal.goal_id,
                title=str(rp.get("title") or "Untitled project"),
                description=str(rp.get("description") or ""),
            )
            projects.append(proj)
            for rt in rp.get("tasks", []):
                flat_specs.append(
                    {
                        "project": proj,
                        "skill": rt.get("skill"),
                        "payload": rt.get("payload") or {},
                        "depends_on": rt.get("depends_on") or [],
                    }
                )

        if not flat_specs:
            raise PlanValidationError("plan has no tasks")

        n = len(flat_specs)
        edges: dict[int, list[int]] = {}
        for i, spec in enumerate(flat_specs):
            if spec["skill"] not in known:
                raise PlanValidationError(f"unknown skill: {spec['skill']!r}")
            deps = spec["depends_on"]
            if not isinstance(deps, list) or any(
                not isinstance(d, int) or d < 0 or d >= n or d == i for d in deps
            ):
                raise PlanValidationError(f"task {i} has invalid depends_on: {deps!r}")
            edges[i] = deps

        if _has_cycle(edges, n):
            raise PlanValidationError("plan dependency graph has a cycle")

        tasks: list[PlannedTask] = [
            PlannedTask(
                project_id=spec["project"].project_id,
                goal_id=goal.goal_id,
                skill=spec["skill"],
                payload=spec["payload"],
            )
            for spec in flat_specs
        ]
        for i, spec in enumerate(flat_specs):
            tasks[i] = tasks[i].model_copy(
                update={"depends_on": [tasks[d].task_id for d in edges[i]]}
            )

        return PlanResult(projects=projects, tasks=tasks, plan_confidence=plan_confidence)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/goals/test_goal_planner.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add agents/andromeda/planner.py test/goals/test_goal_planner.py
git commit -m "feat: add GoalPlanner (LLM goal decomposition + plan validation)"
```

---

## Task 4: GoalRunner

**Files:**
- Create: `agents/andromeda/goal_runner.py`
- Test: `test/goals/test_goal_runner.py`

**Interfaces:**
- Consumes: `GoalStore` (Task 2) — `try_claim`, `get_goal`, `get_tasks`, `update_task`, `set_goal_status`, `goal_tree`; an `Andromeda`-like object exposing `.route(task=TaskContract) -> dict` and `.review_queue` with `.enqueue(...)` accepting `goal_id=`; `TaskContract`.
- Produces:
  - `GoalRunner(andromeda, store: GoalStore)`
  - `.run(goal_id: UUID) -> None` — guarded, synchronous body (callers wrap in a thread)
  - `.run_async(goal_id: UUID) -> None` — spawns `threading.Thread(target=self.run, args=(goal_id,), daemon=True)`
  - `.resolve_escalated_task(goal_id: UUID, task_id: UUID, approved: bool) -> None` — approve → mark task `complete`, re-run; reject → mark task `failed`, goal `failed`

Route-result classification (from `Andromeda.route()` return dict): `status == "complete"` and `confidence >= goal.confidence_threshold` → complete; `status in ("escalated",)` or `review_pending` truthy → escalate+pause; `status in ("failed", "no_agent_found")` → fail.

- [ ] **Step 1: Write the failing test**

```python
# test/goals/test_goal_runner.py
import uuid
import pytest
from core.contracts import GoalContract, ProjectNode, PlannedTask
from core.goals.store import GoalStore
from agents.andromeda.goal_runner import GoalRunner


class FakeReviewQueue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)


class FakeAndromeda:
    def __init__(self, script):
        # script: dict skill -> route() return dict
        self._script = script
        self.review_queue = FakeReviewQueue()
        self.calls = []

    def route(self, task=None):
        self.calls.append(task.skill)
        return dict(self._script[task.skill])


@pytest.fixture
def store(tmp_path):
    return GoalStore(db_path=str(tmp_path / "goals.db"))


def _seed(store, deps_second_on_first=True, threshold=0.65):
    g = GoalContract(origin="t", objective="x", confidence_threshold=threshold)
    store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    t1 = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    d = [t1.task_id] if deps_second_on_first else []
    t2 = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.b", payload={}, depends_on=d)
    store.save_plan(g.goal_id, [p], [t1, t2], plan_confidence=0.9, gated=False)
    return g, t1, t2


def test_linear_chain_completes(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "complete", "confidence": 0.9},
        "s.b": {"status": "complete", "confidence": 0.8},
    })
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == ["s.a", "s.b"]
    assert store.get_goal(g.goal_id).status == "complete"
    assert [t.status for t in store.get_tasks(g.goal_id)] == ["complete", "complete"]


def test_failure_pauses_goal_and_enqueues_review(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "escalated", "confidence": 0.3, "review_pending": True},
        "s.b": {"status": "complete", "confidence": 0.9},
    })
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == ["s.a"]                       # stopped, never ran s.b
    assert store.get_goal(g.goal_id).status == "paused"
    tasks = store.get_tasks(g.goal_id)
    assert tasks[0].status == "escalated"
    assert andro.review_queue.enqueued[0]["goal_id"] == str(g.goal_id)


def test_hard_failure_fails_goal(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({"s.a": {"status": "no_agent_found", "confidence": 0.0}})
    GoalRunner(andro, store).run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "failed"


def test_subthreshold_complete_is_escalation(store):
    g, t1, t2 = _seed(store, threshold=0.9)
    andro = FakeAndromeda({"s.a": {"status": "complete", "confidence": 0.7}})
    GoalRunner(andro, store).run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "paused"
    assert store.get_tasks(g.goal_id)[0].status == "escalated"


def test_run_is_not_reentrant(store):
    g, t1, t2 = _seed(store)
    store.try_claim(g.goal_id)   # simulate another runner already owning it
    andro = FakeAndromeda({"s.a": {"status": "complete", "confidence": 0.9}})
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls == []


def test_resume_after_approve_continues(store):
    g, t1, t2 = _seed(store)
    andro = FakeAndromeda({
        "s.a": {"status": "escalated", "confidence": 0.3, "review_pending": True},
        "s.b": {"status": "complete", "confidence": 0.9},
    })
    runner = GoalRunner(andro, store)
    runner.run(g.goal_id)
    assert store.get_goal(g.goal_id).status == "paused"
    runner.resolve_escalated_task(g.goal_id, t1.task_id, approved=True)
    assert store.get_goal(g.goal_id).status == "complete"
    assert andro.calls == ["s.a", "s.b"]


def test_diamond_dag_runs_all_nodes(store):
    g = GoalContract(origin="t", objective="x", confidence_threshold=0.5)
    store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    a = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    b = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.b", payload={}, depends_on=[a.task_id])
    c = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.c", payload={}, depends_on=[a.task_id])
    d = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.d", payload={}, depends_on=[b.task_id, c.task_id])
    store.save_plan(g.goal_id, [p], [a, b, c, d], plan_confidence=0.9, gated=False)
    andro = FakeAndromeda({k: {"status": "complete", "confidence": 0.9} for k in ["s.a", "s.b", "s.c", "s.d"]})
    GoalRunner(andro, store).run(g.goal_id)
    assert andro.calls[0] == "s.a"
    assert andro.calls[-1] == "s.d"
    assert set(andro.calls) == {"s.a", "s.b", "s.c", "s.d"}
    assert store.get_goal(g.goal_id).status == "complete"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest test/goals/test_goal_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agents.andromeda.goal_runner'`

- [ ] **Step 3: Create `agents/andromeda/goal_runner.py`**

```python
from __future__ import annotations

import logging
import threading
from uuid import UUID

from core.contracts import TaskContract

logger = logging.getLogger(__name__)


class GoalRunner:
    def __init__(self, andromeda, store):
        self._andromeda = andromeda
        self._store = store

    def run_async(self, goal_id: UUID) -> None:
        threading.Thread(
            target=self.run, args=(goal_id,), name=f"goal-{goal_id}", daemon=True
        ).start()

    def run(self, goal_id: UUID) -> None:
        if not self._store.try_claim(goal_id):
            logger.info("goal %s already running or not runnable — skipping", goal_id)
            return
        try:
            self._drive(goal_id)
        except Exception:
            logger.exception("goal %s runner crashed", goal_id)
            self._store.set_goal_status(goal_id, "failed")

    def _drive(self, goal_id: UUID) -> None:
        goal = self._store.get_goal(goal_id)
        threshold = goal.confidence_threshold

        while True:
            tasks = self._store.get_tasks(goal_id)
            by_id = {t.task_id: t for t in tasks}
            pending = [t for t in tasks if t.status == "pending"]
            if not pending:
                self._store.set_goal_status(goal_id, "complete")
                return

            ready = [
                t for t in pending
                if all(by_id[d].status == "complete" for d in t.depends_on)
            ]
            if not ready:
                # unmet deps means an upstream task failed/escalated; goal already
                # set to paused/failed by the branch that stopped us. Safety net:
                self._store.set_goal_status(goal_id, "paused")
                return

            task = ready[0]
            self._store.update_task(task.task_id, status="running")
            contract = TaskContract(
                origin=f"goal:{goal_id}",
                skill=task.skill,
                payload=task.payload,
                confidence_threshold=threshold,
            )
            result = self._andromeda.route(task=contract)
            status = result.get("status")
            confidence = result.get("confidence")

            if status == "complete" and (confidence or 0.0) >= threshold:
                self._store.update_task(
                    task.task_id, status="complete", confidence=confidence,
                    result=result.get("result") if isinstance(result.get("result"), dict) else None,
                )
                continue

            if status in ("failed", "no_agent_found"):
                self._store.update_task(
                    task.task_id, status="failed", confidence=confidence,
                    error=result.get("failure_reason") or status,
                )
                self._store.set_goal_status(goal_id, "failed")
                return

            # escalated, or sub-threshold complete, or review_pending
            self._store.update_task(
                task.task_id, status="escalated", confidence=confidence,
                result=result.get("result") if isinstance(result.get("result"), dict) else None,
            )
            self._andromeda.review_queue.enqueue(
                task_id=str(task.task_id),
                task_type=task.skill,
                confidence=confidence or 0.0,
                payload=task.payload,
                skill_id=task.skill,
                agent_output=result.get("result") if isinstance(result.get("result"), dict) else {},
                goal_id=str(goal_id),
            )
            self._store.set_goal_status(goal_id, "paused")
            return

    def resolve_escalated_task(self, goal_id: UUID, task_id: UUID, approved: bool) -> None:
        if approved:
            self._store.update_task(task_id, status="complete")
            self.run(goal_id)
        else:
            self._store.update_task(task_id, status="failed", error="rejected by reviewer")
            self._store.set_goal_status(goal_id, "failed")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest test/goals/test_goal_runner.py -v`
Expected: PASS (7 passed)

Note on `test_run_is_not_reentrant`: after `try_claim` the status is `running`, so the second `run()`'s own `try_claim` returns `False`. Good. On `test_resume_after_approve_continues`: after pause, status is `paused`; `resolve_escalated_task(approved=True)` marks t1 complete then calls `run()`, whose `try_claim` flips `paused -> running`, then the drive loop finds t2 ready.

- [ ] **Step 5: Commit**

```bash
git add agents/andromeda/goal_runner.py test/goals/test_goal_runner.py
git commit -m "feat: add GoalRunner (dependency-ordered goal execution + escalation)"
```

---

## Task 5: ReviewQueue — goal_id column

**Files:**
- Modify: `agents/andromeda/review_queue.py`
- Test: `test/agents/test_review_queue_goal_id.py`

**Interfaces:**
- Produces: `ReviewQueue.enqueue(..., goal_id: str | None = None)`; `get_by_task_id` / `get_pending` rows include `"goal_id"`.

- [ ] **Step 1: Write the failing test**

```python
# test/agents/test_review_queue_goal_id.py
from agents.andromeda.review_queue import ReviewQueue


def test_enqueue_records_goal_id(tmp_path):
    q = ReviewQueue(db_path=str(tmp_path / "rq.db"))
    q.enqueue(task_id="t1", task_type="s.a", confidence=0.3, payload={}, goal_id="g1")
    item = q.get_by_task_id("t1")
    assert item["goal_id"] == "g1"


def test_goal_id_defaults_none(tmp_path):
    q = ReviewQueue(db_path=str(tmp_path / "rq.db"))
    q.enqueue(task_id="t2", task_type="s.b", confidence=0.3, payload={})
    assert q.get_by_task_id("t2")["goal_id"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/agents/test_review_queue_goal_id.py -v`
Expected: FAIL — `TypeError: enqueue() got an unexpected keyword argument 'goal_id'`

- [ ] **Step 3: Edit `agents/andromeda/review_queue.py`**

1. In `_CREATE_TABLE` add `    goal_id        TEXT,` before `reviewer_notes`.
2. Add to `_MIGRATE_STMTS`: `"ALTER TABLE review_queue ADD COLUMN goal_id TEXT",`
3. Add `"goal_id"` to `_COLUMNS` (append at the end so existing positional mapping is unaffected).
4. `enqueue` signature: add `goal_id: Optional[str] = None`.
5. `enqueue` INSERT: add `goal_id` to the column list and `?` + `goal_id` to values:

```python
self._conn.execute(
    """
    INSERT OR IGNORE INTO review_queue
        (task_id, task_type, skill_id, agent_id, agent_output, sla_deadline,
         confidence, payload, status, created_at, goal_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
    """,
    (
        task_id, task_type, skill_id, agent_id,
        json.dumps(agent_output or {}), sla_deadline,
        confidence, json.dumps(payload), now, goal_id,
    ),
)
```

Because `goal_id` is appended last in `_COLUMNS`, and both `get_pending` / `get_by_task_id` build their SELECT from `_COLUMNS`, `_row_to_dict` maps it automatically. Verify `_COLUMNS` order now matches the SELECT column order (it builds `SELECT {', '.join(_COLUMNS)}`), so ordering is internally consistent regardless of physical table column order.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest test/agents/test_review_queue_goal_id.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Regression — existing review-queue tests**

Run: `python -m pytest -q -k review_queue`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add agents/andromeda/review_queue.py test/agents/test_review_queue_goal_id.py
git commit -m "feat: add nullable goal_id column to ReviewQueue"
```

---

## Task 6: Andromeda boot wiring

**Files:**
- Modify: `agents/andromeda/orchestrator.py`
- Test: `test/goals/test_andromeda_goal_wiring.py`

**Interfaces:**
- Consumes: `GoalStore`, `GoalPlanner`, `GoalRunner`.
- Produces: `Andromeda(..., goal_store: GoalStore | None = None)`; attributes `.goal_store`, `.goal_planner`, `.goal_runner` available after construction.

- [ ] **Step 1: Write the failing test**

```python
# test/goals/test_andromeda_goal_wiring.py
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.task_log import TaskLog
from agents.andromeda.goal_runner import GoalRunner
from core.artifacts.store import ArtifactStore
from core.goals.store import GoalStore
from core.pulsar.registry import PulsarRegistry


def test_andromeda_exposes_goal_components(tmp_path):
    a = Andromeda(
        registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
        task_log=TaskLog(db_path=str(tmp_path / "t.db")),
        agents={},
        artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
        goal_store=GoalStore(db_path=str(tmp_path / "g.db")),
    )
    assert isinstance(a.goal_store, GoalStore)
    assert isinstance(a.goal_runner, GoalRunner)
    assert a.goal_planner is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/goals/test_andromeda_goal_wiring.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'goal_store'`

- [ ] **Step 3: Edit `agents/andromeda/orchestrator.py`**

Add imports near the other `agents.andromeda` / `core` imports:

```python
from agents.andromeda.goal_runner import GoalRunner
from agents.andromeda.planner import GoalPlanner
from core.goals.store import GoalStore
```

In `Andromeda.__init__` signature add `goal_store: Optional[GoalStore] = None,` after `artifact_store`. In the body, after `self.artifact_store = ...`:

```python
self.goal_store = goal_store or GoalStore()
self.goal_planner = GoalPlanner(registry)
self.goal_runner = GoalRunner(self, self.goal_store)
```

(`GoalPlanner` loads the provider config lazily inside `.plan()`, so construction never touches `config/providers.yaml` — existing tests that build `Andromeda` without that file keep working.)

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest test/goals/test_andromeda_goal_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Full suite**

Run: `python -m pytest -q`
Expected: all green (existing + new goal tests)

- [ ] **Step 6: Commit**

```bash
git add agents/andromeda/orchestrator.py test/goals/test_andromeda_goal_wiring.py
git commit -m "feat: wire GoalStore/GoalPlanner/GoalRunner into Andromeda"
```

---

## Task 7: API endpoints

**Files:**
- Modify: `services/andromeda_service.py`
- Test: `test/api/test_goals_api.py`

**Interfaces:**
- Consumes: `_andromeda.goal_planner`, `_andromeda.goal_runner`, `_andromeda.goal_store`; existing `PlanValidationError`.
- Produces HTTP:
  - `POST /goals` body `{"objective": str, "confidence_threshold": float = 0.65}` → `202`, body = `goal_tree` + `{"plan_pending_review": bool}`. On `PlanValidationError` → `422`.
  - `GET /goals` → `[GoalContract-ish dict]`
  - `GET /goals/{goal_id}` → `goal_tree` + `{"rollup": {...}}`; `404` if unknown
  - `POST /goals/{goal_id}/resume` → `202` + goal_tree; `404` unknown; `409` if status not in `{ready, paused}`

- [ ] **Step 1: Write the failing test**

```python
# test/api/test_goals_api.py
import uuid
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
    import services.andromeda_service as svc
    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.task_log import TaskLog
    from core.artifacts.store import ArtifactStore
    from core.goals.store import GoalStore
    from core.pulsar.registry import PulsarRegistry
    from core.contracts import SkillDefinition, SkillManifest

    reg = PulsarRegistry(db_path=str(tmp_path / "p.db"))
    reg.register(SkillManifest(
        agent_id="rigel", agent_name="Rigel", version="1.0.0",
        skills=[SkillDefinition(skill_id="rigel.skill.code_generation", description="gen",
                                input_schema={}, output_schema={})],
        health_endpoint="/health"))
    a = Andromeda(registry=reg, task_log=TaskLog(db_path=str(tmp_path / "t.db")),
                  agents={}, artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
                  goal_store=GoalStore(db_path=str(tmp_path / "g.db")))

    # deterministic planner + runner
    from agents.andromeda.planner import PlanResult
    from core.contracts import ProjectNode, PlannedTask

    def fake_plan(goal):
        p = ProjectNode(goal_id=goal.goal_id, title="proj")
        t = PlannedTask(project_id=p.project_id, goal_id=goal.goal_id,
                        skill="rigel.skill.code_generation", payload={"spec": "x"})
        return PlanResult(projects=[p], tasks=[t], plan_confidence=0.9)

    a.goal_planner.plan = fake_plan
    a.goal_runner.run_async = lambda gid: None  # don't actually execute
    monkeypatch.setattr(svc, "_andromeda", a)
    return TestClient(svc.app)


def test_post_goal_returns_202_and_tree(client):
    r = client.post("/goals", json={"objective": "build a todo API"})
    assert r.status_code == 202
    body = r.json()
    assert body["goal"]["objective"] == "build a todo API"
    assert len(body["projects"][0]["tasks"]) == 1
    assert body["plan_pending_review"] is False


def test_post_goal_low_plan_confidence_is_gated(client, monkeypatch):
    import services.andromeda_service as svc
    from agents.andromeda.planner import PlanResult
    from core.contracts import ProjectNode, PlannedTask

    def low_plan(goal):
        p = ProjectNode(goal_id=goal.goal_id, title="p")
        t = PlannedTask(project_id=p.project_id, goal_id=goal.goal_id,
                        skill="rigel.skill.code_generation", payload={})
        return PlanResult(projects=[p], tasks=[t], plan_confidence=0.2)

    svc._andromeda.goal_planner.plan = low_plan
    r = client.post("/goals", json={"objective": "vague thing", "confidence_threshold": 0.65})
    assert r.status_code == 202
    assert r.json()["plan_pending_review"] is True
    assert r.json()["goal"]["status"] == "paused"


def test_get_goal_404(client):
    assert client.get(f"/goals/{uuid.uuid4()}").status_code == 404


def test_get_and_list_goal(client):
    gid = client.post("/goals", json={"objective": "x"}).json()["goal"]["goal_id"]
    got = client.get(f"/goals/{gid}")
    assert got.status_code == 200
    assert "rollup" in got.json()
    assert any(g["goal_id"] == gid for g in client.get("/goals").json())


def test_resume_409_when_running(client):
    gid = client.post("/goals", json={"objective": "x"}).json()["goal"]["goal_id"]
    svc_gid = uuid.UUID(gid)
    import services.andromeda_service as svc
    svc._andromeda.goal_store.set_goal_status(svc_gid, "running")
    assert client.post(f"/goals/{gid}/resume").status_code == 409
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/api/test_goals_api.py -v`
Expected: FAIL — 404s (routes don't exist)

- [ ] **Step 3: Edit `services/andromeda_service.py`**

Add near the other imports:

```python
from uuid import UUID
from agents.andromeda.planner import PlanValidationError
```

Add a request model near the other Pydantic models (search for `class TaskRequest`):

```python
class GoalRequest(BaseModel):
    objective: str
    confidence_threshold: float = 0.65
```

Add the endpoints (place them after the `/artifacts/rollback` handler, before `/status`):

```python
@app.post("/goals", status_code=202)
def create_goal(req: GoalRequest):
    from core.contracts import GoalContract

    goal = GoalContract(
        origin="api",
        objective=req.objective,
        confidence_threshold=req.confidence_threshold,
    )
    _andromeda.goal_store.create_goal(goal)
    try:
        plan = _andromeda.goal_planner.plan(goal)
    except PlanValidationError as e:
        _andromeda.goal_store.set_goal_status(goal.goal_id, "failed")
        raise HTTPException(status_code=422, detail=f"planning failed: {e}")

    gated = plan.plan_confidence < goal.confidence_threshold
    _andromeda.goal_store.save_plan(
        goal.goal_id, plan.projects, plan.tasks, plan.plan_confidence, gated=gated
    )
    if gated:
        _andromeda.review_queue.enqueue(
            task_id=f"plan:{goal.goal_id}",
            task_type="goal.plan_review",
            confidence=plan.plan_confidence,
            payload={"objective": goal.objective},
            skill_id="goal.plan_review",
            goal_id=str(goal.goal_id),
        )
    else:
        _andromeda.goal_runner.run_async(goal.goal_id)

    tree = _andromeda.goal_store.goal_tree(goal.goal_id)
    tree["plan_pending_review"] = gated
    return tree


@app.get("/goals")
def list_goals():
    return [
        {
            "goal_id": str(g.goal_id),
            "origin": g.origin,
            "objective": g.objective,
            "confidence_threshold": g.confidence_threshold,
            "status": g.status,
            "plan_confidence": g.plan_confidence,
            "created_at": g.created_at.isoformat(),
        }
        for g in _andromeda.goal_store.list_goals()
    ]


@app.get("/goals/{goal_id}")
def get_goal(goal_id: str):
    try:
        gid = UUID(goal_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="goal not found")
    if _andromeda.goal_store.get_goal(gid) is None:
        raise HTTPException(status_code=404, detail="goal not found")
    tree = _andromeda.goal_store.goal_tree(gid)
    tree["rollup"] = _andromeda.goal_store.rollup(gid)
    return tree


@app.post("/goals/{goal_id}/resume", status_code=202)
def resume_goal(goal_id: str):
    try:
        gid = UUID(goal_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="goal not found")
    goal = _andromeda.goal_store.get_goal(gid)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    if goal.status not in ("ready", "paused"):
        raise HTTPException(status_code=409, detail=f"goal is {goal.status}, cannot resume")
    _andromeda.goal_runner.run_async(gid)
    return _andromeda.goal_store.goal_tree(gid)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest test/api/test_goals_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Regression — API + auth suites**

Run: `python -m pytest -q test/api`
Expected: all pass (existing 10+ unaffected — new routes are protected and not in `_EXEMPT_ROUTES`; a separate check: `python -m pytest test/api -q -k auth` still green)

- [ ] **Step 6: Commit**

```bash
git add services/andromeda_service.py test/api/test_goals_api.py
git commit -m "feat: add /goals plan/list/get/resume endpoints"
```

---

## Task 8: Review-queue resume hook

**Files:**
- Modify: `services/andromeda_service.py` (the `/review/queue/{task_id}/approve` and `/reject` handlers)
- Test: `test/api/test_goals_review_resume.py`

**Interfaces:**
- Consumes: `_andromeda.goal_runner.resolve_escalated_task(goal_id: UUID, task_id: UUID, approved: bool)`.
- Behaviour: after the existing `resolve(...)` call in `approve_task` / `reject_task`, if `item.get("goal_id")` is set and the queue `task_id` is a task UUID (not a `plan:` sentinel), call `resolve_escalated_task`. For a `plan:` sentinel (goal-plan review), approve → `run_async(goal_id)`; reject → `set_goal_status(goal_id, "failed")`.

- [ ] **Step 1: Write the failing test**

```python
# test/api/test_goals_review_resume.py
import uuid
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXZ_API_KEY", raising=False)
    import services.andromeda_service as svc
    from agents.andromeda.orchestrator import Andromeda
    from agents.andromeda.task_log import TaskLog
    from core.artifacts.store import ArtifactStore
    from core.goals.store import GoalStore
    from core.pulsar.registry import PulsarRegistry
    from core.contracts import GoalContract, ProjectNode, PlannedTask

    a = Andromeda(registry=PulsarRegistry(db_path=str(tmp_path / "p.db")),
                  task_log=TaskLog(db_path=str(tmp_path / "t.db")), agents={},
                  artifact_store=ArtifactStore(db_path=str(tmp_path / "a.db")),
                  goal_store=GoalStore(db_path=str(tmp_path / "g.db")))
    calls = []
    a.goal_runner.resolve_escalated_task = lambda gid, tid, approved: calls.append((gid, tid, approved))
    monkeypatch.setattr(svc, "_andromeda", a)

    g = GoalContract(origin="t", objective="x", confidence_threshold=0.6)
    a.goal_store.create_goal(g)
    p = ProjectNode(goal_id=g.goal_id, title="p")
    t = PlannedTask(project_id=p.project_id, goal_id=g.goal_id, skill="s.a", payload={})
    a.goal_store.save_plan(g.goal_id, [p], [t], plan_confidence=0.9, gated=False)
    a.review_queue.enqueue(task_id=str(t.task_id), task_type="s.a", confidence=0.3,
                           payload={}, goal_id=str(g.goal_id))
    return TestClient(svc.app), calls, g.goal_id, t.task_id


def test_approve_resumes_goal(setup):
    client, calls, gid, tid = setup
    r = client.post(f"/review/queue/{tid}/approve")
    assert r.status_code == 200
    assert calls == [(gid, tid, True)]


def test_reject_fails_goal_task(setup):
    client, calls, gid, tid = setup
    client.post(f"/review/queue/{tid}/reject")
    assert calls == [(gid, tid, False)]
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest test/api/test_goals_review_resume.py -v`
Expected: FAIL — `calls` stays empty.

- [ ] **Step 3: Edit the two handlers in `services/andromeda_service.py`**

In `approve_task`, after `_andromeda.task_log.update_status(...)` and before building the `FeedbackEvent`:

```python
    goal_id = item.get("goal_id")
    if goal_id:
        _resume_goal_from_review(item["task_id"], goal_id, approved=True)
```

In `reject_task`, same spot:

```python
    goal_id = item.get("goal_id")
    if goal_id:
        _resume_goal_from_review(item["task_id"], goal_id, approved=False)
```

Add the helper near the top-level functions (after `_orion_db_path`):

```python
def _resume_goal_from_review(queue_task_id: str, goal_id: str, approved: bool) -> None:
    from uuid import UUID

    gid = UUID(goal_id)
    if queue_task_id.startswith("plan:"):
        if approved:
            _andromeda.goal_runner.run_async(gid)
        else:
            _andromeda.goal_store.set_goal_status(gid, "failed")
        return
    _andromeda.goal_runner.resolve_escalated_task(gid, UUID(queue_task_id), approved)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest test/api/test_goals_review_resume.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Regression — review-queue API**

Run: `python -m pytest -q test/api -k "review or queue or goals"`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add services/andromeda_service.py test/api/test_goals_review_resume.py
git commit -m "feat: resume/fail goal when its escalated task is reviewed"
```

---

## Task 9: Prism Goals page

**Files:**
- Create: `prism/src/pages/Goals.tsx`
- Modify: `prism/src/App.tsx`
- Modify: `prism/src/components/Sidebar.tsx`

**Interfaces:** consumes `GET/POST /api/goals`, `GET /api/goals/{id}`, `POST /api/goals/{id}/resume`. No backend interface produced.

- [ ] **Step 1: Add the route in `prism/src/App.tsx`**

Add import beside the others: `import { Goals } from './pages/Goals';`
Add route beside the others: `<Route path="/goals" element={<Goals />} />`

- [ ] **Step 2: Add nav entry in `prism/src/components/Sidebar.tsx`**

- In `NAV_ROUTES`: add `goals: '/goals',`
- In the `NavId` union: add `| 'goals'`
- In `buildNavSections`, in the `Platform` section items array, after `task-queue`:
  `{ id: 'goals', label: 'Goals', icon: <IconActivity /> },`

- [ ] **Step 3: Create `prism/src/pages/Goals.tsx`**

```tsx
import React, { useEffect, useRef, useState } from 'react';
import { Sidebar } from '../components/Sidebar';
import '../styles/tokens.css';

const mono = "'Geist Mono', monospace";

interface TaskNode {
  task_id: string;
  skill: string;
  status: string;
  confidence: number | null;
  depends_on: string[];
  error: string | null;
}
interface ProjectNode {
  project_id: string;
  title: string;
  description: string;
  tasks: TaskNode[];
}
interface GoalTree {
  goal: { goal_id: string; objective: string; status: string; plan_confidence: number | null };
  projects: ProjectNode[];
  plan_pending_review?: boolean;
  rollup?: { completed: number; total: number; min_confidence: number | null };
}

const STATUS_COLOR: Record<string, string> = {
  pending: 'var(--t4)',
  running: '#4f8eff',
  complete: '#3fb950',
  failed: '#f85149',
  escalated: '#d29922',
  ready: '#4f8eff',
  paused: '#d29922',
  planning: 'var(--t4)',
};

export function Goals() {
  const [objective, setObjective] = useState('');
  const [tree, setTree] = useState<GoalTree | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<number | null>(null);

  function stopPoll() {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }
  useEffect(() => stopPoll, []);

  async function refresh(goalId: string) {
    try {
      const res = await fetch(`/api/goals/${goalId}`);
      if (!res.ok) throw new Error(`goal HTTP ${res.status}`);
      const data: GoalTree = await res.json();
      setTree(data);
      if (!['running', 'ready'].includes(data.goal.status)) stopPoll();
    } catch (err) {
      setError(String(err));
      stopPoll();
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    stopPoll();
    try {
      const res = await fetch('/api/goals', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ objective }),
      });
      if (!res.ok) throw new Error(`plan HTTP ${res.status}: ${await res.text()}`);
      const data: GoalTree = await res.json();
      setTree(data);
      if (data.goal.status === 'running' || data.goal.status === 'ready') {
        pollRef.current = window.setInterval(() => refresh(data.goal.goal_id), 3000);
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function resume() {
    if (!tree) return;
    const res = await fetch(`/api/goals/${tree.goal.goal_id}/resume`, { method: 'POST' });
    if (!res.ok) {
      setError(`resume HTTP ${res.status}: ${await res.text()}`);
      return;
    }
    pollRef.current = window.setInterval(() => refresh(tree.goal.goal_id), 3000);
  }

  return (
    <div className="app-shell" style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar activeId="goals" />
      <div className="app-main" style={{ flex: 1, padding: 24, overflow: 'auto' }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--t1)', marginBottom: 4 }}>Goals</div>
        <div style={{ fontFamily: mono, fontSize: 11, color: 'var(--t4)', marginBottom: 16 }}>
          — submit an objective · Andromeda plans and runs a Goal → Project → Task DAG
        </div>

        <textarea
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          rows={3}
          placeholder="e.g. Build a Python REST API for a todo list, with pytest tests and a README"
          style={{
            width: '100%', maxWidth: 720, fontFamily: mono, fontSize: 12, padding: 10,
            background: 'var(--bg1)', color: 'var(--t1)', border: '1px solid var(--b1)', borderRadius: 6,
          }}
        />
        <div style={{ marginTop: 8 }}>
          <button
            onClick={submit}
            disabled={busy || objective.trim().length === 0}
            style={{
              fontFamily: mono, fontSize: 11, padding: '6px 14px', borderRadius: 5,
              border: '1px solid var(--b1)', background: '#4f8eff', color: '#fff',
              cursor: busy ? 'default' : 'pointer', opacity: busy ? 0.6 : 1,
            }}
          >
            {busy ? 'Planning…' : 'Plan & run'}
          </button>
        </div>

        {error && (
          <div style={{ color: '#f85149', fontFamily: mono, fontSize: 11, marginTop: 12 }}>{error}</div>
        )}

        {tree && (
          <div style={{ marginTop: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
              <span style={{ fontSize: 13, color: 'var(--t1)' }}>{tree.goal.objective}</span>
              <span style={{ fontFamily: mono, fontSize: 10, color: STATUS_COLOR[tree.goal.status] ?? 'var(--t3)' }}>
                {tree.goal.status.toUpperCase()}
              </span>
              {tree.goal.plan_confidence !== null && (
                <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                  plan {tree.goal.plan_confidence.toFixed(2)}
                </span>
              )}
              {tree.rollup && (
                <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                  {tree.rollup.completed}/{tree.rollup.total} tasks
                </span>
              )}
            </div>

            {tree.plan_pending_review && (
              <div style={{ fontFamily: mono, fontSize: 11, color: '#d29922', marginBottom: 12 }}>
                Plan confidence below threshold — sent to the review queue. Approve it there, then Resume.
              </div>
            )}

            {(tree.goal.status === 'paused' || tree.goal.status === 'ready') && (
              <button
                onClick={resume}
                style={{
                  fontFamily: mono, fontSize: 11, padding: '4px 10px', borderRadius: 5,
                  border: '1px solid var(--b1)', background: 'transparent', color: 'var(--t2)',
                  cursor: 'pointer', marginBottom: 12,
                }}
              >
                Resume
              </button>
            )}

            {tree.projects.map((p) => (
              <div key={p.project_id} style={{ border: '1px solid var(--b1)', borderRadius: 8, marginBottom: 12 }}>
                <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--b1)' }}>
                  <div style={{ fontSize: 12.5, color: 'var(--t1)' }}>{p.title}</div>
                  {p.description && (
                    <div style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>{p.description}</div>
                  )}
                </div>
                {p.tasks.map((t) => (
                  <div
                    key={t.task_id}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 12, padding: '9px 12px',
                      borderBottom: '1px solid var(--b1)',
                    }}
                  >
                    <span style={{ fontFamily: mono, fontSize: 11, color: 'var(--t2)' }}>{t.skill}</span>
                    <span style={{ flex: 1 }} />
                    {t.confidence !== null && (
                      <span style={{ fontFamily: mono, fontSize: 10, color: 'var(--t4)' }}>
                        {t.confidence.toFixed(2)}
                      </span>
                    )}
                    <span style={{ fontFamily: mono, fontSize: 10, color: STATUS_COLOR[t.status] ?? 'var(--t3)' }}>
                      {t.status}
                    </span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Goals;
```

- [ ] **Step 4: Type-check and build**

Run: `cd prism && npm run build`
Expected: `tsc` passes, `vite build` succeeds.

- [ ] **Step 5: Commit**

```bash
git add prism/src/pages/Goals.tsx prism/src/App.tsx prism/src/components/Sidebar.tsx
git commit -m "feat: add Prism Goals page"
```

---

## Task 10: Eval scenario + contract docs

**Files:**
- Modify: `evals/run_evals.py`
- Modify: `CLAUDE.md`
- Test: the eval harness itself

**Interfaces:** none produced.

- [ ] **Step 1: Inspect the eval harness**

Run: `grep -n "def test_\|def scenario\|Andromeda(\|route(" evals/run_evals.py | head -40`
Identify the pattern used for an existing Andromeda routing scenario (it constructs an `Andromeda` with fake/real agents and asserts on `route()` output).

- [ ] **Step 2: Add a deterministic goal scenario**

Following the file's existing style, add a scenario that:
1. builds an `Andromeda` with an isolated `GoalStore` and a registry containing one echo skill,
2. monkeypatches `andromeda.goal_planner.plan` to return a fixed 2-task `PlanResult` (chain),
3. stubs the echo agent so `route()` returns `{"status": "complete", "confidence": 0.9}`,
4. calls `andromeda.goal_runner.run(goal_id)` synchronously,
5. asserts final goal status `complete` and `rollup()["completed"] == 2`.

Use the exact assertion style already in the file (the harness prints `N passed / N failed`).

- [ ] **Step 3: Run the eval harness**

Run: `python evals/run_evals.py`
Expected: the summary line shows one more passing scenario than before (was `8 passed`), `0 failed`.

- [ ] **Step 4: Update `CLAUDE.md` "The Three Core Contracts"**

Rename the section to "The Core Contracts" and add a fourth entry after Refinery Feedback Events:

```markdown
### 4. Goal Contracts (Goal / Project hierarchy) — `GoalContract` / `ProjectNode` / `PlannedTask`

The goal layer sits ABOVE TaskContract — it composes TaskContracts, never bypasses
them. Every task the executor runs is a normal `TaskContract` routed through
`Andromeda.route()`.

# GoalContract — one per submitted objective
{ "goal_id": UUID, "origin": str, "objective": str,
  "confidence_threshold": float, "status": "planning|ready|running|paused|complete|failed",
  "plan_confidence": float | None, "created_at": datetime }

# ProjectNode — a group of related tasks under a goal
{ "project_id": UUID, "goal_id": UUID, "title": str, "description": str }

# PlannedTask — one routed unit of work; depends_on is a DAG edge set
{ "task_id": UUID, "project_id": UUID, "goal_id": UUID, "skill": str, "payload": dict,
  "depends_on": list[UUID], "status": "pending|running|complete|failed|escalated",
  "confidence": float | None, "result": dict | None, "error": str | None }
```

Also flip the priority-list "Goal/project hierarchy" bullet to done, referencing the spec and this plan.

- [ ] **Step 5: Full test suite + eval harness green**

Run: `python -m pytest -q && python evals/run_evals.py`
Expected: all pytest green; eval harness `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add evals/run_evals.py CLAUDE.md
git commit -m "test: add goal-execution eval scenario; docs: document goal contracts"
```

---

## Self-Review

**1. Spec coverage**

| Spec section | Task |
|---|---|
| `GoalContract`/`ProjectNode`/`PlannedTask` + enums | Task 1 |
| `GoalStore` (SQLite, CRUD, tree, rollup, compare-and-set) | Task 2 |
| `GoalPlanner` (one LLM call, skill validation, index→UUID, cycle detection, confidence clamp/default) | Task 3 |
| `GoalRunner` (non-reentrant claim, DAG readiness, sequential, escalate/pause, fail on `no_agent_found`, resume) | Task 4 |
| Daemon-thread execution (`run_async`) | Task 4 (helper) + Task 7 (called by endpoint) |
| ReviewQueue `goal_id` via `ALTER TABLE` | Task 5 |
| Boot wiring in `Andromeda.__init__`, lazy provider config | Task 6 |
| `POST /goals` (202, gate → `plan_pending_review`), `GET /goals`, `GET /goals/{id}` (+rollup), `POST /goals/{id}/resume` (409) | Task 7 |
| Protected routes (not in `_EXEMPT_ROUTES`) | Task 7 Step 5 |
| Review approve/reject → resume/fail goal; `plan:` sentinel handling | Task 8 |
| Prism `Goals.tsx` + route + sidebar, poll while running, resume button | Task 9 |
| `CLAUDE.md` contract doc (section becomes four) | Task 10 Step 4 |
| Eval harness goal scenario | Task 10 Step 2 |
| Testing plan (store/planner/runner/api/eval) | Tasks 2,3,4,7,8,10 |

`boot.py` is untouched by design — `Andromeda.__init__` defaults `goal_store` to a real `GoalStore()`, so the production boot path picks it up with no change. Noted here so the executor doesn't go looking for a missing `boot.py` edit.

**2. Placeholder scan:** Task 10 Steps 1–2 describe adding a scenario "following the file's existing style" without pasted code — this is deliberate because `evals/run_evals.py`'s structure hasn't been read yet; Step 1 is the read step and the acceptance check in Step 3 is concrete (`8 passed` → `9 passed`, `0 failed`). All other code steps contain full implementations.

**3. Type consistency:** `GoalStore` method names (`try_claim`, `save_plan(..., gated=)`, `update_task`, `set_goal_status`, `goal_tree`, `rollup`, `get_tasks`, `get_goal`, `list_goals`, `create_goal`) are used identically in Tasks 4, 6, 7, 8. `PlanResult` fields (`.projects`, `.tasks`, `.plan_confidence`) consistent between Task 3 (def) and Tasks 6–7 (use). `GoalRunner` API (`run`, `run_async`, `resolve_escalated_task`) consistent between Task 4 (def) and Tasks 7–8 (use). Route-result keys read by `GoalRunner` (`status`, `confidence`, `result`, `failure_reason`, `review_pending`) match what `Andromeda.route()` returns per `agents/andromeda/orchestrator.py`.
