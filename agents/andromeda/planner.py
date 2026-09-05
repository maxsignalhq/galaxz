from __future__ import annotations

import json
from dataclasses import dataclass

from core.contracts import GoalContract, PlannedTask, ProjectNode
from core.llm.provider import call_llm, load_provider_config

_SYSTEM_PROMPT = (
    "You are Andromeda's goal planner. Decompose the user's objective into a small "
    "set of projects, each containing concrete tasks. Every task must target exactly "
    "one of the registered skills listed below. The task payload MUST use exactly the "
    "keys named in that skill's `payload=` schema (all `required` keys, `optional` "
    "keys only when useful) - do not invent or rename keys. Express ordering with "
    "`depends_on`: a list of integer indices into the "
    "flattened task list (projects in order, tasks in order within each project). "
    "Keep the plan minimal - no speculative work. Respond with ONLY a JSON object:\n"
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
            f"- {s.skill_id}: {s.description}"
            + (f"  payload={json.dumps(s.input_schema)}" if s.input_schema else "")
            for s in self._registry.get_all_skills()
        )
        user_msg = f"Objective:\n{goal.objective}\n\nRegistered skills:\n{skill_hint}"
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
        flat_specs: list[dict] = []
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
        for i in range(n):
            tasks[i] = tasks[i].model_copy(
                update={"depends_on": [tasks[d].task_id for d in edges[i]]}
            )

        return PlanResult(projects=projects, tasks=tasks, plan_confidence=plan_confidence)
