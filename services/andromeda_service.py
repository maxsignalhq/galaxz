import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from boot import boot
from agents.andromeda.middleware.auth import ApiKeyMiddleware
from agents.andromeda.orchestrator import Andromeda
from core.aether.client import AetherClient, get_aether_client
from core.contracts import TaskContract
from core.contracts.contracts import FeedbackEvent, OutcomeType
from orion.core.candidate_client import CandidateClient, CandidateNotFoundError

STREAM_FEEDBACK = "aether:task.feedback"
STREAM_FINETUNE = "aether:orion.finetune"

def _orion_db_path() -> str:
    orion = getattr(_andromeda, "orion", None)
    config = getattr(orion, "_cfg", None)
    return getattr(config, "db_path", "orion/data/events.db")


_andromeda: Andromeda = None
_aether: AetherClient = None
_candidate_client: CandidateClient = None
_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _andromeda, _aether, _candidate_client, _start_time
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


class TaskRequest(BaseModel):
    task: str
    skill_id: str


class ResolveRequest(BaseModel):
    reviewer_notes: Optional[str] = None


class CandidateReviewRequest(BaseModel):
    reviewed_by: str
    reviewer_note: Optional[str] = None


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
    return payload


@app.post("/task")
def post_task(req: TaskRequest):
    skill_id = req.skill_id
    if "." not in skill_id and not _andromeda.registry.get_agents_for_skill(skill_id):
        skill_id = f"rigel.skill.{skill_id}"

    try:
        task = TaskContract(
            task_id=uuid4(),
            origin="andromeda_api",
            skill=skill_id,
            payload=_payload_for_skill(skill_id, req.task),
            confidence_threshold=0.65,
        )
        state = _andromeda.route(task=task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return state


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
                "SELECT COUNT(*) FROM feedback_events WHERE quarantined = 0"
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
