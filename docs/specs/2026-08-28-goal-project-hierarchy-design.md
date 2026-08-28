# Goal / Project Hierarchy — Design

_Status: draft for review · 2026-08-28_

## Purpose

Today Galaxz routes one `TaskContract` at a time. A caller who wants a multi-step
outcome ("build a REST API for a todo list with tests and a README") has to
decompose it into individual skill calls themselves and track the results by hand.

This feature adds a planning-and-execution layer on top of the existing router:
a caller submits a single natural-language **objective**, Andromeda uses an LLM to
decompose it into a `Goal → Project → Task` tree, then executes the tasks in
dependency order, escalating to the existing review queue on any failure or
sub-threshold result, and reports rolled-up status.

## Scope

**In scope**

- Three new contracts: `GoalContract`, `ProjectNode`, `PlannedTask`.
- A SQLite-backed `GoalStore` (`core/goals/store.py`), Postgres-swappable via the
  same `_DbConnection` pattern Pulsar uses.
- An LLM planner (`agents/andromeda/planner.py`) that turns an objective into a
  project/task tree with a DAG of `depends_on` edges and its own `plan_confidence`.
- A goal executor (`agents/andromeda/goal_runner.py`) that walks the DAG,
  calls the existing `Andromeda.route()` per task, and drives goal state.
- Four HTTP endpoints on the Andromeda service.
- A Prism page (`Goals.tsx`) to submit an objective, watch the tree fill in, and
  resume a paused goal.
- Contract documentation update in `CLAUDE.md`.

**Out of scope**

- Parallel task execution — v1 runs ready tasks sequentially; the DAG only
  determines *order and readiness*, not concurrency.
- Re-planning / plan editing after creation. A rejected plan is abandoned; the
  caller submits a new objective.
- Goal-level Aether events / Orion feedback for the plan itself (task-level
  feedback already flows through `Andromeda.route()` unchanged).
- Cross-goal dependencies.

## Data Model

Added to `core/contracts/contracts.py` (Pydantic v2, immutable, same conventions
as `TaskContract`).

```python
GoalStatus = Literal["planning", "ready", "running", "paused", "complete", "failed"]
PlannedTaskStatus = Literal["pending", "running", "complete", "failed", "escalated"]

class GoalContract(BaseModel):
    goal_id: UUID = Field(default_factory=uuid4)
    origin: str
    objective: str                      # the natural-language ask
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    status: GoalStatus = "planning"
    plan_confidence: float | None = None # planner's self-reported confidence
    created_at: datetime = Field(default_factory=utc_now)

class ProjectNode(BaseModel):
    project_id: UUID = Field(default_factory=uuid4)
    goal_id: UUID
    title: str
    description: str = ""

class PlannedTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    goal_id: UUID
    skill: str                          # must be a Pulsar-registered skill
    payload: dict
    depends_on: list[UUID] = []         # other PlannedTask.task_id in the same goal
    status: PlannedTaskStatus = "pending"
    confidence: float | None = None
    result: dict | None = None
    error: str | None = None
```

### Persistence — `core/goals/store.py`

`GoalStore(db_url: str | None = None)` — default `data/goals.db` (already covered by
`.gitignore`'s `data/*.db`). Reuses Pulsar's `_DbConnection` so a
`postgresql://` URL works unchanged. Tests pass an isolated temp path, exactly like
the `ArtifactStore` isolation in commit `ee17cae`.

Three tables: `goals`, `projects`, `tasks` (columns mirror the contracts; the
tree/DAG is stored as `tasks.depends_on_json`).

Methods:

| method | purpose |
|--------|---------|
| `create_goal(goal: GoalContract)` | insert a goal in `planning` |
| `save_plan(goal_id, projects, tasks, plan_confidence)` | persist the planner output, flip goal → `ready` (or `paused` if the confidence gate trips) |
| `get_goal(goal_id) -> GoalContract` | |
| `list_goals() -> list[GoalContract]` | newest first |
| `goal_tree(goal_id) -> dict` | goal + projects + tasks, for API/UI |
| `update_task(task_id, **fields)` | status/confidence/result/error after a route |
| `set_goal_status(goal_id, status)` | |
| `rollup(goal_id) -> dict` | `{status, completed, total, min_confidence}` |

## Planner — `agents/andromeda/planner.py`

`GoalPlanner(registry: PulsarRegistry, provider_config)`.

`plan(objective: str) -> PlanResult` where `PlanResult` carries `projects`,
`tasks`, and `plan_confidence`.

- One `call_llm()` call. System prompt describes the decomposition job; the user
  message injects the list of **currently registered skills** (from
  `registry`) with their descriptions and input schemas, plus a JSON output
  schema (same injection pattern as Vega's Analyzer stage).
- The model returns projects, each with tasks referencing a `skill` and a
  `payload`, and `depends_on` given as **local integer indices** into the flat
  task list. The planner resolves those to `PlannedTask.task_id` UUIDs and
  rejects any cycle or out-of-range index (raises `PlanValidationError`).
- Every `skill` is validated against the registry; an unknown skill →
  `PlanValidationError`.
- `plan_confidence` is taken from the model output, clamped to `[0, 1]`, and
  recomputed-guarded (never trust it blindly — if absent, default `0.5`).

## Executor — `agents/andromeda/goal_runner.py`

`GoalRunner(andromeda: Andromeda, store: GoalStore)`.

`run(goal_id)`:

1. Load the goal tree. Set goal → `running`.
2. Loop: find all `pending` tasks whose `depends_on` are all `complete`.
   - None ready and tasks still `pending` with unmet deps → this only happens
     if a dependency `failed`/`escalated`; stop (goal already `paused`).
   - None ready and no `pending` left → all done.
3. For each ready task (sequential): build a `TaskContract`
   (`origin=f"goal:{goal_id}"`, `skill`, `payload`,
   `confidence_threshold=goal.confidence_threshold`) and call
   `andromeda.route(task)`.
   - Route returns `complete` with confidence ≥ threshold → `update_task(status="complete", ...)`.
   - Route escalated, failed, or `review_pending` → `update_task(status="escalated"/"failed", ...)`,
     set goal → `paused`, and **stop the loop**. `Andromeda.route()` has
     already enqueued the task to the `ReviewQueue`; `GoalRunner` additionally
     records `goal_id` + `task_id` on that queue item (new optional columns on
     the review-queue store) so the operator UI can link back.
4. When the loop drains with every task `complete`: goal → `complete`.
5. `rollup` sets goal confidence = min task confidence.

### Resuming after escalation

The existing `POST /review/queue/{task_id}/approve|reject` handlers gain a
post-step: if the resolved queue item carries a `goal_id`, then
- **approve** → mark that `PlannedTask` `complete` (using the agent output already
  captured), and call `GoalRunner.run(goal_id)` again to continue the DAG.
- **reject** → mark the `PlannedTask` `failed`, set goal → `failed`.

No new review-queue endpoint; `POST /goals/{id}/resume` is a thin manual trigger
that just calls `GoalRunner.run` (useful if the process restarted mid-goal).

## API — `services/andromeda_service.py`

| method + path | body | behaviour |
|---|---|---|
| `POST /goals` | `{objective, confidence_threshold?}` (default 0.65) | create goal → `GoalPlanner.plan` → `save_plan`. If `plan_confidence < confidence_threshold`: goal stays `paused`, enqueue a review item, return the tree with `plan_pending_review: true`. Else `GoalRunner.run` executes synchronously and the response is the final tree + rollup. |
| `GET /goals` | — | `list_goals()` |
| `GET /goals/{goal_id}` | — | `goal_tree()` + `rollup()` |
| `POST /goals/{goal_id}/resume` | — | `GoalRunner.run(goal_id)`; 409 if goal not `paused`/`ready` |

All four are **protected** routes (not added to `_EXEMPT_ROUTES`).

Synchronous execution matches the existing `POST /task` model (that endpoint also
routes inline). Long goals will hold the request open; acceptable for v1 and
consistent with the rest of the service. A background-job queue is a later concern.

## Boot wiring

`Andromeda.__init__` gains `self.goal_store = GoalStore(<test-isolated path>)`,
`self.goal_planner = GoalPlanner(self.registry, provider_config)`, and
`self.goal_runner = GoalRunner(self, self.goal_store)`. Same test-isolation
treatment as `artifact_store`. No change to the LangGraph routing graph — the goal
layer sits *above* `route()`, not inside it.

## Prism — `src/pages/Goals.tsx`

New route `/goals`, sidebar entry under "Platform". A textarea + "Plan & run"
button posts to `/api/goals`; the returned tree renders as
Project cards each listing their tasks with a status pill and confidence bar
(reuse the `rq-conf-*` styles). A `paused` goal shows a "Resume" button →
`POST /api/goals/{id}/resume`. Poll `GET /api/goals/{id}` every few seconds while
status is `running`. Plain React, no new deps, matches existing page structure.

## Contract doc update

`CLAUDE.md`'s "The Three Core Contracts" section becomes four, adding
`GoalContract` / `ProjectNode` / `PlannedTask` with a note that the goal layer
composes `TaskContract`s and does not bypass any existing contract — every task
the executor runs is a normal `TaskContract` through `Andromeda.route()`.

## Testing

- `core/goals/store.py` — unit tests: create, save_plan, tree round-trip,
  update_task, rollup, DAG with a diamond dependency, Postgres-URL path smoke
  (skipped without psycopg2, mirroring Pulsar tests).
- `planner.py` — with a stubbed `call_llm`: valid plan resolves indices to UUIDs;
  unknown skill raises; cyclic `depends_on` raises; missing `plan_confidence`
  defaults to 0.5.
- `goal_runner.py` — with a fake `Andromeda` whose `route()` returns scripted
  results: linear chain completes; a mid-DAG failure pauses the goal and enqueues
  review; approve-resume continues; reject fails the goal; diamond DAG runs all
  four nodes in a valid order.
- API — `test/api/`: `POST /goals` happy path (stubbed planner + runner),
  low-plan-confidence gate returns `plan_pending_review`, `GET /goals/{id}`
  shape, `resume` 409 on a running goal, all four routes 401 without bearer when
  `GALAXZ_API_KEY` set.
- Eval harness — extend `evals/run_evals.py` with one deterministic goal scenario
  (objective → 2-project plan → all tasks complete → goal complete).

## Files touched

New: `core/goals/__init__.py`, `core/goals/store.py`,
`agents/andromeda/planner.py`, `agents/andromeda/goal_runner.py`,
`prism/src/pages/Goals.tsx`, tests under `test/goals/` and `test/api/`.

Modified: `core/contracts/contracts.py` (+ `core/contracts/__init__.py` exports),
`agents/andromeda/orchestrator.py` (boot wiring),
`agents/andromeda/review_queue.py` (optional `goal_id`/`task_id` columns +
resume hook), `services/andromeda_service.py` (4 endpoints + review-resume hook),
`prism/src/App.tsx`, `prism/src/components/Sidebar.tsx`, `CLAUDE.md`,
`evals/run_evals.py`.

## Risks / open points

- **LLM plan quality** is the main unknown. Mitigation: the `plan_confidence`
  gate routes shaky plans to a human before any task runs, and every task still
  passes through the normal per-task confidence machinery.
- **Synchronous long requests** — accepted for v1 (see API section).
- **Review-queue schema change** — adding nullable `goal_id`/`task_id` columns is
  backwards-compatible; existing rows get `NULL`.
