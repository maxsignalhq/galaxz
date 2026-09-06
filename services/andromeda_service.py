import json
import hashlib
import hmac
import logging
import os
import re
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from boot import boot
from agents.andromeda.middleware.auth import ApiKeyMiddleware
from agents.andromeda.orchestrator import Andromeda
from agents.andromeda.planner import PlanValidationError
from core.contracts import GoalContract
from services.file_writer import FileWriter
from core.aether.client import AetherClient, get_aether_client
from core.artifacts.store import identity_key
from core.contracts import TaskContract
from core.contracts import RetryPolicy
from core.jobs import InvalidJobState
from core.jobs import PostgresJobRepository, SqliteJobRepository
from core.goals import DurableGoalCoordinator
from core.repositories import RepositoryAccessError, RepositoryStore
from core.github import GitHubAppClient, GitHubClient, PullRequestEvidence, WebhookStore
from core.security import ArtifactScanOverride, scan_artifacts
from core.contracts.contracts import FeedbackEvent, OutcomeType
from core.llm.provider import call_llm, load_provider_config
from core.storage.manage import validate_runtime_database_configuration
from orion.core.candidate_client import CandidateClient, CandidateNotFoundError
from orion.core.dataset_store import DatasetStore

STREAM_FEEDBACK = "aether:task.feedback"
STREAM_FINETUNE = "aether:orion.finetune"

logger = logging.getLogger(__name__)


def _read_workspace_path() -> str:
    import yaml as _yaml
    path = Path("config/providers.yaml")
    if not path.exists():
        return ""
    with path.open(encoding="utf-8") as f:
        data = _yaml.safe_load(f) or {}
    return data.get("workspace_path", "") or ""


def _orion_db_path() -> str:
    orion = getattr(_andromeda, "orion", None)
    config = getattr(orion, "_cfg", None)
    return getattr(config, "db_path", "orion/data/events.db")


_andromeda: Andromeda = None
_aether: AetherClient = None
_candidate_client: CandidateClient = None
_start_time: float = 0.0
_job_repository: SqliteJobRepository | PostgresJobRepository | None = None
_repository_store = RepositoryStore()


def _github_app() -> GitHubAppClient:
    app_id = os.getenv("GALAXZ_GITHUB_APP_ID")
    private_key = os.getenv("GALAXZ_GITHUB_APP_PRIVATE_KEY")
    if not app_id or not private_key:
        raise HTTPException(status_code=503, detail="GitHub App integration is not configured")
    return GitHubAppClient(app_id, private_key, base_url=os.getenv("GALAXZ_GITHUB_API_URL", "https://api.github.com"))


def _github_client(installation_id: int | None = None) -> GitHubClient:
    if installation_id is None and os.getenv("GALAXZ_GITHUB_APP_ID") and os.getenv("GALAXZ_GITHUB_APP_PRIVATE_KEY"):
        installation_id = int(os.getenv("GALAXZ_GITHUB_INSTALLATION_ID", "0")) or None
    if installation_id is not None:
        token = _github_app().installation_token(installation_id)
        return GitHubClient(token, base_url=os.getenv("GALAXZ_GITHUB_API_URL", "https://api.github.com"))
    token = os.getenv("GALAXZ_GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=503, detail="GitHub integration is not configured")
    return GitHubClient(token, base_url=os.getenv("GALAXZ_GITHUB_API_URL", "https://api.github.com"))


def _github_webhooks() -> WebhookStore:
    return WebhookStore(os.getenv("GITHUB_WEBHOOK_DB_PATH", "data/github-webhooks.db"))


def _jobs() -> SqliteJobRepository | PostgresJobRepository:
    global _job_repository
    database = os.getenv("GALAXZ_DATABASE_URL") or os.getenv("JOB_DB_PATH", "data/jobs.db")
    if _job_repository is None or _job_repository.database != database:
        _job_repository = PostgresJobRepository(database) if database.startswith(("postgres://", "postgresql://", "postgresql+")) else SqliteJobRepository(database)
    return _job_repository


def _goal_coordinator() -> DurableGoalCoordinator:
    return DurableGoalCoordinator(
        _andromeda.goal_store,
        _jobs(),
        review_queue=_andromeda.review_queue,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _andromeda, _aether, _candidate_client, _start_time
    validate_runtime_database_configuration()
    _start_time = time.monotonic()
    _andromeda = boot()
    _aether = get_aether_client()
    _candidates_db = str(Path(_orion_db_path()).parent / "candidates.db")
    _candidate_client = CandidateClient(_candidates_db)
    _startup_log = logging.getLogger(__name__)
    _startup_log.warning("Galaxz v1.0 API has no authentication.")
    _startup_log.warning("Do not expose to the public internet without a reverse proxy.")
    _startup_log.warning("See docs/decisions/auth-boundary.md for details.")
    print("[andromeda] ready")
    print(f"[pulsar] health={_andromeda.registry.health_check()}")
    print(f"[rigel] skills_registered={len(_andromeda.registry.get_all_skills())}")
    yield
    _aether.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(ApiKeyMiddleware)


class TaskSessionContextItem(BaseModel):
    role: Optional[str] = None
    content: str
    skill_id: Optional[str] = None
    assigned_agent: Optional[str] = None
    status: Optional[str] = None
    confidence: Optional[float] = None


class TaskRequest(BaseModel):
    task: str
    skill_id: str
    route_mode: Optional[str] = "auto"
    session_context: list[TaskSessionContextItem] = Field(default_factory=list)
    reviewer_override: dict | None = None


class JobRequest(TaskRequest):
    idempotency_key: str
    priority: int = Field(default=0, ge=-100, le=100)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)


class ResolveRequest(BaseModel):
    reviewer_notes: Optional[str] = None


class CandidateReviewRequest(BaseModel):
    reviewed_by: str
    reviewer_note: Optional[str] = None


class TaskFeedbackRequest(BaseModel):
    outcome: str  # "accepted" | "rejected"


class ArtifactRollbackRequest(BaseModel):
    path: str
    workspace_root: str = ""
    version: int
    project_id: str | None = None
    organization_id: str | None = None


class GoalRequest(BaseModel):
    objective: str
    confidence_threshold: float = 0.65
    repository_id: str | None = None
    base_revision: str = "HEAD"


class RepositoryRequest(BaseModel):
    provider: str
    owner: str
    name: str
    installation_scope: str
    local_path: str | None = None


class GoalControlRequest(BaseModel):
    reason: str | None = None


class GitHubPullRequestRequest(BaseModel):
    owner: str
    repository: str
    head: str
    base: str = "main"
    title: str
    goal_id: str
    task_ids: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    validation: str
    review_decision: str
    draft: bool = True
    installation_id: Optional[int] = None


class GitHubCheckRequest(BaseModel):
    owner: str
    repository: str
    head_sha: str
    name: str
    passed: bool
    summary: str
    installation_id: Optional[int] = None


_SHORT_SKILL_ALIASES = {
    "code_generation": "rigel.skill.code_generation",
    "debug_triage": "rigel.skill.debug_triage",
    "pr_review": "rigel.skill.pr_review",
    "refactor": "rigel.skill.refactor",
    "scaffold": "rigel.skill.scaffold",
    "test_writing": "rigel.skill.test_writing",
    "requirements_to_test_cases": "vega.skill.requirements_to_test_cases",
    "test_case_execution": "vega.skill.test_case_execution",
    "defect_reporting": "vega.skill.defect_reporting",
}


def _normalize_skill_id(skill_id: str) -> str:
    if skill_id == "auto" or "." in skill_id:
        return skill_id
    if _andromeda.registry.get_agents_for_skill(skill_id):
        return skill_id
    return _SHORT_SKILL_ALIASES.get(skill_id, f"rigel.skill.{skill_id}")


def _payload_for_skill(skill_id: str, task_text: str) -> dict:
    payload = {"spec": task_text, "task": task_text}
    if skill_id == "rigel.skill.pr_review":
        payload["diff"] = task_text
    elif skill_id == "rigel.skill.debug_triage":
        payload["error_trace"] = task_text
    elif skill_id == "rigel.skill.test_writing":
        payload["code"] = task_text
    elif skill_id == "rigel.skill.refactor":
        payload["code"] = task_text
        payload["refactor_intent"] = task_text
    elif skill_id == "rigel.skill.scaffold":
        payload["project_type"] = "service"
        payload["stack"] = task_text
    elif skill_id in ("requirements_to_test_cases", "vega.skill.requirements_to_test_cases"):
        payload["raw_requirements"] = task_text
        payload["source_type"] = "plain"
    elif skill_id in ("test_case_execution", "vega.skill.test_case_execution"):
        payload["test_results"] = [
            {
                "tc_id": "UI-001",
                "status": "fail",
                "actual_result": task_text,
            }
        ]
    elif skill_id in ("defect_reporting", "vega.skill.defect_reporting"):
        payload["raw_requirements"] = task_text
        payload["test_results"] = [
            {
                "tc_id": "UI-001",
                "status": "fail",
                "actual_result": task_text,
            }
        ]
    return payload


def _truncate_context_value(value: str, limit: int = 5000) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "\n\n[truncated]"


def _format_session_context(session_context: list[TaskSessionContextItem]) -> str:
    parts: list[str] = []
    for index, item in enumerate(session_context[-12:], start=1):
        content = _truncate_context_value(item.content)
        if not content:
            continue

        label = item.role or "message"
        meta = []
        if item.skill_id:
            meta.append(f"skill={item.skill_id}")
        if item.assigned_agent:
            meta.append(f"agent={item.assigned_agent}")
        if item.status:
            meta.append(f"status={item.status}")
        if isinstance(item.confidence, (int, float)):
            meta.append(f"confidence={item.confidence:.2f}")

        suffix = f" ({', '.join(meta)})" if meta else ""
        parts.append(f"[{index}] {label}{suffix}\n{content}")

    return "\n\n".join(parts)


def _task_text_with_session_context(
    task_text: str,
    session_context: list[TaskSessionContextItem],
) -> str:
    formatted_context = _format_session_context(session_context)
    if not formatted_context:
        return task_text

    return (
        "This request is part of an existing Task UI session. Continue the same task unless "
        "the current user message explicitly starts a new one. Use the prior user request "
        "and prior agent output as the subject of revision, redo, threshold, or follow-up requests.\n\n"
        f"Current user message:\n{task_text.strip()}\n\n"
        f"Prior Task UI session context:\n{formatted_context}"
    )


def _classify_skill_with_llm(task_text: str) -> Optional[str]:
    """Use LLM to pick the best skill_id. Short timeout so failures fall through quickly."""
    import os as _os
    prev = _os.environ.get("LITELLM_TIMEOUT_SECONDS")
    _os.environ["LITELLM_TIMEOUT_SECONDS"] = "8"
    try:
        skills = _andromeda.registry.get_all_skills()
        if not skills:
            return None
        lines = [f"- {s.skill_id}: {s.description}" for s in skills]
        skill_list = "\n".join(lines)
        system = (
            "You are a task router. Given a user task and a list of available skills, "
            "respond with ONLY the single best skill_id — nothing else, no explanation, no punctuation."
        )
        user = (
            f"Available skills:\n{skill_list}\n\n"
            f"User task: {task_text.strip()}\n\n"
            "Reply with exactly one skill_id from the list above."
        )
        provider_cfg = load_provider_config()
        raw, _, _ = call_llm([{"role": "user", "content": user}], provider_cfg, system_prompt=system)
        chosen = raw.strip().strip('"').strip("'").split()[0] if raw.strip() else ""
        if any(s.skill_id == chosen for s in skills):
            return chosen
        for s in skills:
            if chosen in s.skill_id or s.skill_id.endswith(f".{chosen}"):
                return s.skill_id
    except Exception:
        pass  # fall through to keyword classifier
    finally:
        if prev is None:
            _os.environ.pop("LITELLM_TIMEOUT_SECONDS", None)
        else:
            _os.environ["LITELLM_TIMEOUT_SECONDS"] = prev
    return None


def _is_auto_route(skill_id: str, route_mode: Optional[str]) -> bool:
    return route_mode == "auto" and skill_id in {
        "auto",
        "rigel.skill.code_generation",
        "code_generation",
    }


_CODE_MARKERS = ("write", "create", "build", "script", "program", "python")
_QA_MARKERS = ("test case", "test cases", "istqb", "qa", "testing")


def _needs_code_then_qa(task_text: str) -> bool:
    text = task_text.lower()
    return any(m in text for m in _CODE_MARKERS) and any(m in text for m in _QA_MARKERS)


def _needs_qa_only(task_text: str) -> bool:
    text = task_text.lower()
    return any(m in text for m in _QA_MARKERS) and not any(m in text for m in _CODE_MARKERS)


# Ordered from most-specific to least-specific. First match wins.
_SKILL_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    # Vega QA
    (("defect report", "bug report", "jira ticket", "failed test"), "vega.skill.defect_reporting"),
    (("execute test", "run test", "test execution", "test results", "pass rate", "pass/fail"), "vega.skill.test_case_execution"),
    (("istqb", "test case", "test cases", "test suite", "write tests for requirement"), "vega.skill.requirements_to_test_cases"),
    # PM
    (("stakeholder brief", "executive brief", "executive summary for", "business case"), "pm.skill.stakeholder_brief"),
    (("prioriti", "moscow", "rice framework", "backlog", "feature list"), "pm.skill.prioritization"),
    (("user stor", "acceptance criteria", "as a user", "gherkin", "given when then"), "pm.skill.user_stories"),
    (("product requirements", "prd", "product requirement", "requirements document", "write a prd"), "pm.skill.prd"),
    # Lumina UI
    (("accessibility", "wcag", "aria", "screen reader", "a11y", "color contrast"), "lumina.skill.accessibility_audit"),
    (("style guide", "brand guide", "brand identity", "visual identity"), "lumina.skill.style_guide"),
    (("ux review", "user experience review", "usability", "user flow review", "ux audit"), "lumina.skill.ux_review"),
    (("design system", "design token", "color token", "typography scale", "spacing token"), "lumina.skill.design_system"),
    (("ui component", "react component", "vue component", "generate component", "component for"), "lumina.skill.component_generation"),
    # Rigel Engineering
    (("debug", "error trace", "stack trace", "typeerror", "exception", "crash", "fix bug", "bug in"), "rigel.skill.debug_triage"),
    (("code review", "pr review", "pull request review", "review this", "review the"), "rigel.skill.pr_review"),
    (("refactor", "clean up", "extract", "decompose", "make composable"), "rigel.skill.refactor"),
    (("unit test", "write test", "testing library", "jest", "pytest", "mocha"), "rigel.skill.test_writing"),
    (("scaffold", "boilerplate", "project structure", "file structure", "set up a project"), "rigel.skill.scaffold"),
]


def _keyword_classify_skill(task_text: str) -> Optional[str]:
    text = task_text.lower()
    for keywords, skill_id in _SKILL_KEYWORD_RULES:
        if any(kw in text for kw in keywords):
            return skill_id
    return None


def _implementation_prompt_for_auto_route(task_text: str) -> str:
    implementation_part = re.split(
        r"\bthen\b|\bafter that\b|\busing same requirements\b",
        task_text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    if not implementation_part:
        implementation_part = task_text.strip()
    return (
        "Implement only the Python program requested below. "
        "Do not create test cases, unit tests, QA artifacts, or ISTQB documentation in this step.\n\n"
        f"Implementation request:\n{implementation_part}"
    )


def _truncate_for_agent_context(value: str, limit: int = 12000) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n\n[truncated for downstream QA context]"


def _route_one(
    skill_id: str,
    task_text: str,
    session_context: Optional[list[TaskSessionContextItem]] = None,
) -> dict:
    session_context = session_context or []
    effective_task_text = _task_text_with_session_context(task_text, session_context)
    task = TaskContract(
        task_id=uuid4(),
        origin="andromeda_api",
        skill=skill_id,
        payload=_payload_for_skill(skill_id, effective_task_text),
        confidence_threshold=0.65,
    )
    route_context = {
        "task_ui_session": [
            item.model_dump(exclude_none=True) for item in session_context
        ],
        "current_user_message": task_text,
    } if session_context else None
    if route_context is not None:
        return _andromeda.route(task=task, context=route_context)
    return _andromeda.route(task=task)


def _task_contract(req: TaskRequest) -> TaskContract:
    skill_id = _normalize_skill_id(req.skill_id)
    effective_task_text = _task_text_with_session_context(req.task, req.session_context)
    return TaskContract(
        task_id=uuid4(),
        origin="andromeda_api",
        skill=skill_id,
        payload=_payload_for_skill(skill_id, effective_task_text),
        confidence_threshold=0.65,
    )


def _route_code_then_qa(
    task_text: str,
    session_context: Optional[list[TaskSessionContextItem]] = None,
) -> dict:
    contextual_task_text = _task_text_with_session_context(task_text, session_context or [])
    code_prompt = _implementation_prompt_for_auto_route(contextual_task_text)
    code_state = _route_one("rigel.skill.code_generation", code_prompt)
    if code_state.get("status") != "complete":
        return code_state

    code_result = code_state.get("result") if isinstance(code_state.get("result"), dict) else {}
    generated_code = _truncate_for_agent_context(str(code_result.get("code", "")))
    qa_prompt = (
        "Create ISTQB-style test cases from these requirements and the generated implementation.\n"
        "Do not rewrite the implementation. Produce QA/test-case output only.\n"
        "Create no more than 6 high-value test cases covering positive, negative, and edge paths.\n\n"
        f"Original user request and session context:\n{contextual_task_text}\n\n"
        "Generated implementation from Rigel:\n"
        f"{generated_code}\n\n"
        "Required QA output: ISTQB-style test cases for this implementation and its requirements."
    )
    qa_skill_id = "vega.skill.requirements_to_test_cases"
    qa_state = _route_one(qa_skill_id, qa_prompt)

    status = "complete" if qa_state.get("status") == "complete" else qa_state.get("status", "failed")
    confidence_values = [
        value for value in (code_state.get("confidence"), qa_state.get("confidence"))
        if isinstance(value, (int, float))
    ]
    confidence = min(confidence_values) if confidence_values else 0.0
    qa_result = qa_state.get("result") if isinstance(qa_state.get("result"), dict) else {}

    return {
        "task_id": qa_state.get("task_id") or code_state.get("task_id"),
        "task_type": "code_then_qa",
        "required_skills": ["rigel.skill.code_generation", qa_skill_id],
        "assigned_agent": "rigel+vega",
        "assignment_reason": "auto_route: Rigel code_generation → Vega requirements_to_test_cases",
        "status": status,
        "confidence": confidence,
        "confidence_breakdown": {
            "rigel_code_generation": code_state.get("confidence", 0.0),
            "vega_requirements_to_test_cases": qa_state.get("confidence", 0.0),
        },
        "gaps": [],
        "failure_reason": qa_state.get("failure_reason") if status != "complete" else None,
        "escalated_to_human": bool(code_state.get("escalated_to_human") or qa_state.get("escalated_to_human")),
        "issued_at": code_state.get("issued_at"),
        "completed_at": qa_state.get("completed_at") or code_state.get("completed_at"),
        "result": {
            "code": generated_code,
            "language": code_result.get("language", "python"),
            "notes": "Auto-route completed: Rigel generated the Python program, then Vega generated ISTQB-style test cases.",
            "qa_result": qa_result,
            "steps": [
                {
                    "agent": code_state.get("assigned_agent"),
                    "skill": "rigel.skill.code_generation",
                    "task_id": code_state.get("task_id"),
                    "status": code_state.get("status"),
                    "confidence": code_state.get("confidence"),
                },
                {
                    "agent": qa_state.get("assigned_agent"),
                    "skill": qa_skill_id,
                    "task_id": qa_state.get("task_id"),
                    "status": qa_state.get("status"),
                    "confidence": qa_state.get("confidence"),
                },
            ],
        },
    }


@app.post("/task")
def post_task(req: TaskRequest):
    skill_id = _normalize_skill_id(req.skill_id)
    if _is_auto_route(skill_id, req.route_mode):
        if _needs_code_then_qa(req.task):
            try:
                return _route_code_then_qa(req.task, req.session_context)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
        # Keyword-based classification across all 18 registered skills
        keyword_match = _keyword_classify_skill(req.task)
        if keyword_match:
            skill_id = _normalize_skill_id(keyword_match)
        elif _needs_qa_only(req.task):
            skill_id = "vega.skill.requirements_to_test_cases"
        else:
            skill_id = "rigel.skill.code_generation"

    skill_id = _normalize_skill_id(skill_id)

    try:
        state = _route_one(skill_id, req.task, req.session_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    workspace_path = _read_workspace_path()
    file_results: list[dict] = []
    ran_file_write = False

    override = None
    if req.reviewer_override:
        override = ArtifactScanOverride(
            reviewer=str(req.reviewer_override.get("reviewer", "")),
            decision=str(req.reviewer_override.get("decision", "")),
            findings=tuple(req.reviewer_override.get("findings", ())),
        )
    artifact_scan = scan_artifacts(state.get("artifacts", []), override=override)
    if artifact_scan.status in {"blocked", "escalate"}:
        raise HTTPException(status_code=422, detail={"error": "artifact safety review required", "scan": artifact_scan.as_dict()})

    if workspace_path and state.get("writable") and state.get("artifacts"):
        ran_file_write = True
        try:
            writer = FileWriter(workspace_root=workspace_path)
            file_results = writer.write(artifacts=state["artifacts"])
        except FileNotFoundError:
            logger.warning(
                "workspace_path %s does not exist — skipping file write", workspace_path
            )
            file_results = []

    artifacts_in_response = (
        file_results
        if ran_file_write
        else [{**a, "written": False} for a in state.get("artifacts", [])]
    )

    return {
        **state,
        "artifacts": artifacts_in_response,
        "workspace_path": workspace_path or None,
        "confidence_breakdown": state.get("confidence_breakdown") or {},
        "gaps": state.get("gaps") or [],
        "summary": state.get("summary") or "",
        "artifact_scan": artifact_scan.as_dict(),
    }


@app.post("/jobs", status_code=202)
def post_job(req: JobRequest):
    """Persist a task for execution by a dedicated durable worker."""
    task = _task_contract(req)
    try:
        job = _jobs().enqueue(
            task_id=task.task_id,
            task=task,
            idempotency_key=req.idempotency_key,
            priority=req.priority,
            retry_policy=req.retry_policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job.model_dump(mode="json")


@app.get("/jobs/{job_id}")
def get_job(job_id: UUID):
    repository = _jobs()
    job = repository.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job": job.model_dump(mode="json"),
        "result": repository.get_result(job_id),
        "attempts": [attempt.model_dump(mode="json") for attempt in repository.attempts(job_id)],
        "transitions": repository.transitions(job_id),
    }


@app.get("/jobs")
def list_jobs(limit: int = 50):
    try:
        jobs = _jobs().list_jobs(limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [job.model_dump(mode="json") for job in jobs]


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID):
    try:
        job = _jobs().cancel(job_id=job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        existing = _jobs().get_job(job_id)
        if existing is not None and existing.status.value == "cancelled":
            return existing.model_dump(mode="json")
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidJobState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.model_dump(mode="json")


@app.get("/review/queue")
def get_review_queue():
    return _andromeda.review_queue.get_pending()


@app.get("/review/queue/stats")
def get_review_queue_stats():
    return _andromeda.review_queue.get_stats()


@app.get("/review/queue/{task_id}")
def get_review_queue_item(task_id: str):
    item = _andromeda.review_queue.get_by_task_id(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="task not found in review queue")
    return item


@app.get("/tasks/recent")
def get_recent_tasks(limit: int = 10):
    limit = max(1, min(limit, 50))
    return _andromeda.task_log.recent(limit)


@app.get("/tasks/stats")
def get_task_stats():
    return _andromeda.task_log.stats()


@app.get("/tasks/throughput")
def get_task_throughput(hours: int = 24):
    hours = max(1, min(hours, 168))
    return _andromeda.task_log.throughput(hours)


@app.get("/artifacts")
def list_artifacts():
    return _andromeda.artifact_store.list_files()


@app.get("/artifacts/history")
def get_artifact_history(path: str, workspace_root: str = "", project_id: str | None = None, organization_id: str | None = None):
    key = identity_key(workspace_root, path)
    history = _andromeda.artifact_store.history(key)
    if not history:
        raise HTTPException(status_code=404, detail="no versions found for this path")
    try:
        _andromeda.artifact_store.get_version(key, history[0]["version"], project_id=project_id, organization_id=organization_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return history


@app.get("/artifacts/diff")
def get_artifact_diff(path: str, workspace_root: str = "", from_: int | None = None, to: int | None = None, project_id: str | None = None, organization_id: str | None = None):
    key = identity_key(workspace_root, path)
    latest = _andromeda.artifact_store.latest_version_number(key)
    if latest is None:
        raise HTTPException(status_code=404, detail="no versions found for this path")

    from_version = from_ if from_ is not None else max(latest - 1, 1)
    to_version = to if to is not None else latest

    try:
        _andromeda.artifact_store.get_version(key, to_version, project_id=project_id, organization_id=organization_id)
        diff_text = _andromeda.artifact_store.diff(key, from_version, to_version)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError:
        raise HTTPException(status_code=404, detail="requested version not found")

    return {"diff": diff_text, "from": from_version, "to": to_version}


@app.post("/artifacts/rollback")
def rollback_artifact(req: ArtifactRollbackRequest):
    key = identity_key(req.workspace_root, req.path)
    try:
        row = _andromeda.artifact_store.get_version(key, req.version, project_id=req.project_id, organization_id=req.organization_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="version not found")

    workspace_path = _read_workspace_path()
    written = False
    if workspace_path:
        try:
            writer = FileWriter(workspace_root=workspace_path)
            writer.write(
                artifacts=[
                    {
                        "filename": req.path,
                        "content": row["content"],
                        "artifact_type": row["artifact_type"] or "",
                        "language": row["language"] or "",
                    }
                ]
            )
            written = True
        except FileNotFoundError:
            logger.warning(
                "workspace_path %s does not exist — skipping rollback write", workspace_path
            )

    return {"content": row["content"], "version": req.version, "written": written}


def _resume_goal_from_review(queue_task_id: str, goal_id: str, approved: bool) -> None:
    gid = UUID(goal_id)
    if queue_task_id.startswith("plan:"):
        if approved:
            _goal_coordinator().start(gid, actor="review")
        else:
            _andromeda.goal_store.set_goal_status(gid, "failed")
        return
    item = _andromeda.review_queue.get_by_task_id(queue_task_id)
    planned_task_id = item.get("planned_task_id") if item else None
    resolved_task_id = UUID(planned_task_id or queue_task_id)
    if approved:
        _andromeda.goal_store.update_task(resolved_task_id, status="complete")
        _goal_coordinator().start(gid, actor="review")
    else:
        _andromeda.goal_store.update_task(
            resolved_task_id, status="failed", error="rejected by reviewer"
        )
        _andromeda.goal_store.set_goal_status(gid, "failed")


@app.post("/goals", status_code=202)
def create_goal(req: GoalRequest):
    goal = GoalContract(
        origin="api",
        objective=req.objective,
        confidence_threshold=req.confidence_threshold,
    )
    _andromeda.goal_store.create_goal(goal)
    if req.repository_id:
        try:
            record = _repository_store.get(req.repository_id)
            sha = _repository_store.resolve_base(record.repository_id, req.base_revision)
            _andromeda.goal_store.bind_repository(goal.goal_id, record.repository_id, req.base_revision, sha)
        except (RepositoryAccessError, ValueError) as exc:
            _andromeda.goal_store.set_goal_status(goal.goal_id, "failed")
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        plan = _andromeda.goal_planner.plan(goal)
    except PlanValidationError as e:
        _andromeda.goal_store.set_goal_status(goal.goal_id, "failed")
        raise HTTPException(status_code=422, detail=f"planning failed: {e}")
    except Exception as e:  # LLM/transport errors — don't leave the goal stuck in "planning"
        _andromeda.goal_store.set_goal_status(goal.goal_id, "failed")
        raise HTTPException(status_code=502, detail=f"planner error: {e}")

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
        _goal_coordinator().start(goal.goal_id, actor="api")

    tree = _andromeda.goal_store.goal_tree(goal.goal_id)
    tree["repository"] = _andromeda.goal_store.repository_binding(goal.goal_id)
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
    tree["events"] = _andromeda.goal_store.events(gid)
    tree["repository"] = _andromeda.goal_store.repository_binding(gid)
    for project in tree["projects"]:
        for task in project["tasks"]:
            if task["job_id"]:
                job_id = UUID(task["job_id"])
                task["attempts"] = [
                    attempt.model_dump(mode="json") for attempt in _jobs().attempts(job_id)
                ]
                task["transitions"] = _jobs().transitions(job_id)
    return tree


@app.post("/repositories", status_code=201)
def register_repository(req: RepositoryRequest):
    try:
        return _repository_store.register(**req.model_dump()).__dict__
    except (RepositoryAccessError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/repositories/{repository_id}")
def get_repository(repository_id: str):
    try:
        return _repository_store.get(repository_id).__dict__
    except RepositoryAccessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/github/pull-request")
def create_github_pull_request(req: GitHubPullRequestRequest):
    evidence = PullRequestEvidence(
        goal_id=req.goal_id, task_ids=req.task_ids, artifacts=req.artifacts,
        validation=req.validation, review_decision=req.review_decision,
    )
    return _github_client(req.installation_id).create_pull_request(
        req.owner, req.repository, head=req.head, base=req.base, title=req.title,
        evidence=evidence, draft=req.draft,
    )


@app.post("/github/check-run")
def create_github_check_run(req: GitHubCheckRequest):
    return _github_client(req.installation_id).create_check_run(
        req.owner, req.repository, head_sha=req.head_sha, name=req.name,
        passed=req.passed, summary=req.summary,
    )


@app.get("/github/installations")
def list_github_installations():
    return _github_app().list_installations()


@app.get("/github/installations/{installation_id}/repositories")
def list_github_installation_repositories(installation_id: int):
    return _github_app().list_repositories(installation_id)


@app.post("/github/webhook")
async def github_webhook(request: Request):
    secret = os.getenv("GALAXZ_GITHUB_WEBHOOK_SECRET")
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not secret or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    body = await request.body()
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="invalid webhook signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid webhook JSON") from exc
    delivery_id = request.headers.get("X-GitHub-Delivery")
    event = request.headers.get("X-GitHub-Event", "unknown")
    if not delivery_id:
        raise HTTPException(status_code=400, detail="missing webhook delivery id")
    return _github_webhooks().reconcile(delivery_id, event, payload)


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
    _goal_coordinator().start(gid, actor="api")
    return _andromeda.goal_store.goal_tree(gid)


@app.post("/goals/{goal_id}/pause")
def pause_goal(goal_id: UUID, req: GoalControlRequest = GoalControlRequest()):
    try:
        _goal_coordinator().pause(goal_id, actor="api", reason=req.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _andromeda.goal_store.goal_tree(goal_id)


@app.post("/goals/{goal_id}/cancel")
def cancel_goal(goal_id: UUID, req: GoalControlRequest = GoalControlRequest()):
    try:
        _goal_coordinator().cancel(goal_id, actor="api", reason=req.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="goal not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _andromeda.goal_store.goal_tree(goal_id)


@app.post("/goals/{goal_id}/tasks/{task_id}/rerun", status_code=202)
def rerun_goal_task(
    goal_id: UUID,
    task_id: UUID,
    req: GoalControlRequest = GoalControlRequest(),
):
    try:
        _goal_coordinator().rerun(
            goal_id, task_id, actor="api", reason=req.reason
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="goal or task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _andromeda.goal_store.goal_tree(goal_id)


@app.get("/status")
def get_status():
    registry_health = _andromeda.registry.health_check()
    tasks = _andromeda.task_log.stats()
    review_queue = _andromeda.review_queue.get_pending()
    return {
        "status": "ok",
        "service": "andromeda",
        "version": "0.1.0",
        "pulsar": registry_health,
        "tasks": tasks,
        "review_queue": {
            "pending": len(review_queue),
        },
        "aether": _aether_status(),
        "orion": _orion_status(),
    }


@app.get("/orion/status")
def get_orion_status():
    return _orion_status()


@app.get("/orion/analytics")
def get_orion_analytics(hours: int = 24):
    hours = max(1, min(hours, 168))
    db_path = _orion_db_path()
    if not os.path.exists(db_path):
        return {"event_volume": [], "by_domain": [], "by_agent": [], "outcome_counts": {}}
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                """
                SELECT strftime('%Y-%m-%dT%H:00', created_at) AS bucket, COUNT(*) AS count
                FROM events
                WHERE created_at >= datetime('now', ? || ' hours') AND quarantined = 0
                GROUP BY bucket ORDER BY bucket ASC
                """,
                (f"-{hours}",),
            )
            event_volume = [{"bucket": r[0], "count": r[1]} for r in cur.fetchall()]

            cur = conn.execute(
                "SELECT domain, COUNT(*) FROM events WHERE quarantined=0 GROUP BY domain ORDER BY COUNT(*) DESC"
            )
            by_domain = [{"domain": r[0], "count": r[1]} for r in cur.fetchall()]

            cur = conn.execute(
                """
                SELECT agent_id, COUNT(*) AS total,
                       AVG(confidence) AS avg_conf,
                       SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS success_rate
                FROM events WHERE quarantined=0
                GROUP BY agent_id ORDER BY total DESC
                """
            )
            by_agent = [
                {
                    "agent_id": r[0],
                    "count": r[1],
                    "avg_confidence": round(r[2] or 0, 3),
                    "success_rate": round(r[3] or 0, 3),
                }
                for r in cur.fetchall()
            ]

            cur = conn.execute(
                "SELECT outcome, COUNT(*) FROM events WHERE quarantined=0 GROUP BY outcome"
            )
            outcome_counts = {r[0]: r[1] for r in cur.fetchall()}

        return {
            "event_volume": event_volume,
            "by_domain": by_domain,
            "by_agent": by_agent,
            "outcome_counts": outcome_counts,
        }
    except sqlite3.Error:
        return {"event_volume": [], "by_domain": [], "by_agent": [], "outcome_counts": {}}


@app.get("/agents")
def get_agents():
    return [
        manifest.model_dump(mode="json")
        for manifest in _andromeda.registry.list_agents()
    ]


@app.post("/review/queue/{task_id}/approve")
def approve_task(task_id: str, req: ResolveRequest = ResolveRequest()):
    item = _andromeda.review_queue.get_by_task_id(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="task not found in review queue")

    resolved = _andromeda.review_queue.resolve(task_id, "approved", req.reviewer_notes)
    if not resolved:
        raise HTTPException(status_code=409, detail="task already reviewed")

    _andromeda.task_log.update_status(task_id, item.get("task_type", ""), "approved")

    if item.get("goal_id"):
        _resume_goal_from_review(item["task_id"], item["goal_id"], approved=True)

    event = FeedbackEvent(
        task_id=task_id,
        task_category=item.get("task_type") or "unknown",
        agent_id="human_reviewer",
        outcome=OutcomeType.approved,
        confidence_score=item.get("confidence") or 0.0,
        input_hash=task_id,
        agent_output=item.get("payload") or {},
        human_verified=True,
        latency_ms=0,
    )
    _aether.publish_event(STREAM_FEEDBACK, json.loads(event.model_dump_json()))

    return {"task_id": task_id, "status": "approved"}


@app.post("/review/queue/{task_id}/accept")
def accept_task(task_id: str, req: ResolveRequest = ResolveRequest()):
    item = _andromeda.review_queue.get_by_task_id(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="task not found in review queue")

    resolved = _andromeda.review_queue.resolve(task_id, "accepted", req.reviewer_notes)
    if not resolved:
        raise HTTPException(status_code=409, detail="task already reviewed")

    _andromeda.task_log.update_status(task_id, item.get("task_type", ""), "accepted")

    if item.get("goal_id"):
        _resume_goal_from_review(item["task_id"], item["goal_id"], approved=True)

    event = FeedbackEvent(
        task_id=task_id,
        task_category=item.get("task_type") or "unknown",
        agent_id="human_reviewer",
        outcome=OutcomeType.approved,
        confidence_score=1.0,
        input_hash=task_id,
        agent_output=item.get("agent_output") or {},
        human_verified=True,
        latency_ms=0,
    )
    _aether.publish_event(STREAM_FEEDBACK, json.loads(event.model_dump_json()))

    return {"task_id": task_id, "status": "accepted"}


@app.post("/review/queue/{task_id}/reject")
def reject_task(task_id: str, req: ResolveRequest = ResolveRequest()):
    item = _andromeda.review_queue.get_by_task_id(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail="task not found in review queue")

    resolved = _andromeda.review_queue.resolve(task_id, "rejected", req.reviewer_notes)
    if not resolved:
        raise HTTPException(status_code=409, detail="task already reviewed")

    _andromeda.task_log.update_status(task_id, item.get("task_type", ""), "rejected")

    if item.get("goal_id"):
        _resume_goal_from_review(item["task_id"], item["goal_id"], approved=False)

    event = FeedbackEvent(
        task_id=task_id,
        task_category=item.get("task_type") or "unknown",
        agent_id="human_reviewer",
        outcome=OutcomeType.failed,
        confidence_score=0.0,
        input_hash=task_id,
        agent_output=item.get("agent_output") or {},
        human_verified=True,
        latency_ms=0,
    )
    _aether.publish_event(STREAM_FEEDBACK, json.loads(event.model_dump_json()))

    return {"task_id": task_id, "status": "rejected"}


@app.post("/tasks/{task_id}/feedback")
def submit_task_feedback(task_id: str, req: TaskFeedbackRequest):
    if req.outcome not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="outcome must be 'accepted' or 'rejected'")
    task = _andromeda.task_log.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        result_data = json.loads(task.get("result_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        result_data = {}
    event = FeedbackEvent(
        task_id=task_id,
        task_category=task.get("task_type") or "unknown",
        agent_id="human_reviewer",
        outcome=OutcomeType.approved if req.outcome == "accepted" else OutcomeType.failed,
        confidence_score=1.0 if req.outcome == "accepted" else 0.0,
        input_hash=task_id,
        agent_output=result_data,
        human_verified=True,
        latency_ms=0,
    )
    _aether.publish_event(STREAM_FEEDBACK, json.loads(event.model_dump_json()))
    return {"task_id": task_id, "outcome": req.outcome}


@app.get("/finetune/candidates")
def get_finetune_candidates():
    candidates = _candidate_client.list_pending() if _candidate_client else []
    return {"candidates": [c.model_dump() for c in candidates]}


@app.post("/finetune/candidates/{candidate_id}/approve")
def approve_finetune_candidate(candidate_id: str, req: CandidateReviewRequest):
    candidate = _candidate_client.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=409, detail="candidate already reviewed")
    try:
        _candidate_client.approve(candidate_id, req.reviewed_by, req.reviewer_note)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate not found")
    return {"status": "approved", "candidate_id": candidate_id}


@app.post("/finetune/candidates/{candidate_id}/reject")
def reject_finetune_candidate(candidate_id: str, req: CandidateReviewRequest):
    candidate = _candidate_client.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if candidate.status != "pending":
        raise HTTPException(status_code=409, detail="candidate already reviewed")
    try:
        _candidate_client.reject(candidate_id, req.reviewed_by, req.reviewer_note)
    except CandidateNotFoundError:
        raise HTTPException(status_code=404, detail="candidate not found")
    return {"status": "rejected", "candidate_id": candidate_id}


@app.get("/orion/export")
def export_orion_events():
    db_path = _orion_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="No event database found")
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM events WHERE quarantined = 0 ORDER BY created_at ASC"
            ).fetchall()
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    def _iter():
        for row in rows:
            yield json.dumps(dict(row)) + "\n"

    filename = f"orion_events_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.ndjson"
    return StreamingResponse(
        _iter(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/orion/training/run")
def run_orion_training():
    db_path = _orion_db_path()
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="No event database found")

    orion = getattr(_andromeda, "orion", None)
    config = getattr(orion, "_cfg", None)
    dataset_path = getattr(config, "dataset_path", "orion/data/datasets")

    try:
        store = DatasetStore(base_path=dataset_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not open dataset store: {e}")

    _VALID_DOMAINS = {"vega", "rigel"}

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT task_id, skill_id, agent_id, domain, confidence,
                       human_verified, payload, result, created_at
                FROM events
                WHERE quarantined = 0 AND outcome = 'success'
                ORDER BY created_at ASC
                """
            ).fetchall()
    except sqlite3.Error as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")

    flushed_files: list[str] = []
    examples_written = 0
    skipped = 0
    for row in rows:
        domain = row["domain"]
        if domain not in _VALID_DOMAINS:
            skipped += 1
            continue
        if not row["payload"] or not row["result"]:
            skipped += 1
            continue
        example = {
            "task_id":        row["task_id"],
            "skill_id":       row["skill_id"],
            "confidence":     row["confidence"],
            "human_verified": bool(row["human_verified"]),
            "prompt":         row["payload"],
            "completion":     row["result"],
            "created_at":     row["created_at"] or "",
        }
        store.append_example(domain, example)
        examples_written += 1

    seen_domains: set[str] = set()
    for row in rows:
        d = row["domain"]
        if d in _VALID_DOMAINS and d not in seen_domains:
            seen_domains.add(d)
            if store.should_flush(d):
                path = store.flush(d)
                flushed_files.append(path)

    return {
        "status": "ok",
        "examples_written": examples_written,
        "skipped": skipped,
        "dataset_files_flushed": len(flushed_files),
        "flushed_files": flushed_files,
    }


@app.post("/forge/agent", status_code=201)
def forge_agent(req: dict):
    from core.scaffolder import AgentScaffoldParams, ForgeConflictError, scaffold_agent
    from pydantic import ValidationError
    try:
        params = AgentScaffoldParams(**req)
    except (ValidationError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        result = scaffold_agent(params)
    except ForgeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result.model_dump(exclude_none=True)


@app.post("/forge/skill", status_code=201)
def forge_skill(req: dict):
    from core.scaffolder import ForgeConflictError, SkillScaffoldParams, scaffold_skill
    from pydantic import ValidationError
    try:
        params = SkillScaffoldParams(**req)
    except (ValidationError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        result = scaffold_skill(params)
    except ForgeConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)
    return result.model_dump(exclude_none=True)


@app.get("/config")
def get_config():
    import re as _re
    import yaml as _yaml
    path = Path("config/providers.yaml")
    if not path.exists():
        return {"provider": "", "model": "", "api_key_set": False, "base_url": ""}

    def _resolve(val: str) -> str:
        m = _re.match(r'^\$\{(\w+)\}$', str(val))
        return os.environ.get(m.group(1), "") if m else str(val)

    with path.open(encoding="utf-8") as f:
        data = _yaml.safe_load(f)
    llm = data.get("llm", {})
    return {
        "provider":    _resolve(llm.get("provider", "")),
        "model":       _resolve(llm.get("model", "")),
        "api_key_set": bool(_resolve(llm.get("api_key", ""))),
        "base_url":    _resolve(llm.get("base_url", "")),
    }


class ConfigUpdateRequest(BaseModel):
    model:    str = ""
    base_url: str = ""


@app.post("/config")
def update_config(req: ConfigUpdateRequest):
    import yaml as _yaml
    path = Path("config/providers.yaml")
    if not path.exists():
        raise HTTPException(status_code=404, detail="config/providers.yaml not found")
    with path.open(encoding="utf-8") as f:
        data = _yaml.safe_load(f) or {}
    llm = data.setdefault("llm", {})
    if req.model:
        llm["model"] = req.model
    if req.base_url:
        llm["base_url"] = req.base_url
    with path.open("w", encoding="utf-8") as f:
        _yaml.safe_dump(data, f, default_flow_style=False, allow_unicode=True)
    return {"status": "ok"}


@app.get("/health")
def health():
    checks = {}

    # aether check
    try:
        t0 = time.monotonic()
        _aether.redis.ping()
        latency_ms = int((time.monotonic() - t0) * 1000)
        checks["aether"] = {
            "status": "ok" if latency_ms < 100 else "error",
            "latency_ms": latency_ms,
        }
    except Exception:
        checks["aether"] = {"status": "error", "latency_ms": None}

    # pulsar check
    try:
        agents = _andromeda.registry.list_agents()
        checks["pulsar"] = {
            "status": "ok" if agents else "error",
            "agent_count": len(agents),
        }
    except Exception:
        checks["pulsar"] = {"status": "error", "agent_count": 0}

    # task_log check
    try:
        stats = _andromeda.task_log.stats()
        checks["task_log"] = {"status": "ok", "recent_tasks": stats.get("total", 0)}
    except Exception:
        checks["task_log"] = {"status": "error", "recent_tasks": 0}

    # orion check
    checks["orion"] = _read_orion_health()

    aether_ok = checks["aether"]["status"] == "ok"
    all_ok = all(c["status"] == "ok" for c in checks.values())
    if not aether_ok:
        overall = "unhealthy"
    elif not all_ok:
        overall = "degraded"
    else:
        overall = "healthy"

    finetune_pending = len(_candidate_client.list_pending()) if _candidate_client else 0
    return {
        "service": "andromeda",
        "status": overall,
        "version": "1.0.0",
        "checks": checks,
        "finetune_pending": finetune_pending,
        "uptime_seconds": int(time.monotonic() - _start_time),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _orion_status() -> dict:
    orion = getattr(_andromeda, "orion", None)
    config = getattr(orion, "_cfg", None)
    db_path = getattr(config, "db_path", "orion/data/events.db")
    dataset_path = Path(getattr(config, "dataset_path", "orion/data/datasets"))
    event_count = _count_feedback_events(db_path)
    dataset_files = sorted(dataset_path.glob("*.jsonl")) if dataset_path.exists() else []
    training_examples = 0
    for path in dataset_files:
        try:
            with path.open("r", encoding="utf-8") as f:
                training_examples += sum(1 for _ in f)
        except OSError:
            pass

    return {
        "status": "running" if orion is not None else "not_started",
        "mode": "embedded",
        "db_path": db_path,
        "event_count": event_count,
        "dataset_path": str(dataset_path),
        "dataset_files": [path.name for path in dataset_files],
        "training_examples": training_examples,
    }


def _count_feedback_events(db_path: str) -> int:
    if not os.path.exists(db_path):
        return 0
    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.execute(
                "SELECT COUNT(*) FROM events WHERE quarantined = 0"
            )
            row = cur.fetchone()
            return int(row[0] or 0)
    except sqlite3.Error:
        return 0


def _aether_status() -> dict:
    try:
        _aether.redis.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def _read_orion_health() -> dict:
    orion = getattr(_andromeda, "orion", None)
    config = getattr(orion, "_cfg", None)
    dataset_path = getattr(config, "dataset_path", None)
    if dataset_path:
        health_path = Path(dataset_path).parent / "health.json"
    else:
        health_path = Path("orion/data/health.json")
    try:
        data = json.loads(health_path.read_text(encoding="utf-8"))
        last_cycle = data.get("last_cycle_at", "")
        if last_cycle:
            last_dt = datetime.fromisoformat(last_cycle)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            stale = datetime.now(timezone.utc) - last_dt > timedelta(minutes=5)
            status = "stale" if stale else "ok"
        else:
            status = "stale"
        return {"status": status, "last_cycle_at": last_cycle or None}
    except (OSError, json.JSONDecodeError, ValueError):
        return {"status": "stale", "last_cycle_at": None}


if __name__ == "__main__":
    uvicorn.run("services.andromeda_service:app", host="0.0.0.0", port=8001, reload=False)
