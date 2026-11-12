"""PostgreSQL adapters for the operational stores used by Andromeda."""

from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from core.artifacts.object_storage import ArtifactAccessPolicy, ObjectStorage
from core.artifacts.store import identity_key


def _engine(url: str, engine: Engine | None) -> Engine:
    if not url.startswith(("postgres://", "postgresql://", "postgresql+")):
        raise ValueError("PostgreSQL operational stores require a PostgreSQL URL")
    return engine or create_engine(url, pool_pre_ping=True, hide_parameters=True)


class PostgresReviewQueue:
    def __init__(self, database_url: str, *, engine: Engine | None = None):
        self.database, self.engine = database_url, _engine(database_url, engine)

    def close(self):
        self.engine.dispose()

    @staticmethod
    def _row(row):
        if row is None:
            return None
        item = dict(row)
        for key in ("payload", "agent_output"):
            if item.get(key):
                item[key] = json.loads(item[key])
        return item

    def enqueue(self, task_id, task_type, confidence, payload, skill_id="", agent_id="", agent_output=None, sla_deadline=None, goal_id=None, planned_task_id=None, attempt_id=None, organization_id="default"):
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO review_queue
                (task_id,task_type,skill_id,agent_id,agent_output,sla_deadline,confidence,payload,status,created_at,goal_id,planned_task_id,attempt_id,organization_id)
                VALUES (:task,:type,:skill,:agent,:output,:deadline,:confidence,:payload,'pending',:created,:goal,:planned,:attempt,:org)
                ON CONFLICT (task_id) DO NOTHING"""), {"task": task_id, "type": task_type, "skill": skill_id, "agent": agent_id, "output": json.dumps(agent_output or {}), "deadline": sla_deadline, "confidence": confidence, "payload": json.dumps(payload), "created": datetime.now(timezone.utc), "goal": goal_id, "planned": planned_task_id, "attempt": attempt_id, "org": organization_id})

    def get_pending(self, *, organization_id):
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT * FROM review_queue WHERE status='pending' AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org) ORDER BY COALESCE(sla_deadline,'9999') ASC,created_at ASC"), {"org": organization_id}).mappings().all()
        return [self._row(row) for row in rows]

    def get_for(self, task_id, *, organization_id):
        """The item, or None when it is missing *or* another organization's."""
        item = self.get_by_task_id(task_id)
        return item if item is not None and item.get("organization_id") == organization_id else None

    def get_by_task_id(self, task_id):
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM review_queue WHERE task_id=:task"), {"task": task_id}).mappings().first()
        return self._row(row)

    def resolve(self, task_id, new_status, reviewer_notes=None):
        with self.engine.begin() as c:
            result = c.execute(text("UPDATE review_queue SET status=:status,reviewed_at=:now,reviewer_notes=:notes WHERE task_id=:task AND status='pending'"), {"status": new_status, "now": datetime.now(timezone.utc), "notes": reviewer_notes, "task": task_id})
        return result.rowcount > 0

    def get_stats(self, *, organization_id):
        scope = "(CAST(:org AS TEXT) IS NULL OR organization_id=:org)"
        with self.engine.connect() as c:
            rows = c.execute(text(f"SELECT status,COUNT(*) AS count FROM review_queue WHERE {scope} GROUP BY status"), {"org": organization_id}).all()
            oldest = c.execute(text(f"SELECT created_at FROM review_queue WHERE status='pending' AND {scope} ORDER BY created_at LIMIT 1"), {"org": organization_id}).scalar_one_or_none()
            breached = c.execute(text(f"SELECT COUNT(*) FROM review_queue WHERE status='pending' AND sla_deadline IS NOT NULL AND sla_deadline < :now AND {scope}"), {"now": datetime.now(timezone.utc).isoformat(), "org": organization_id}).scalar_one()
        counts = {row[0]: row[1] for row in rows}
        age = None
        if oldest:
            value = oldest if isinstance(oldest, datetime) else datetime.fromisoformat(str(oldest))
            age = int((datetime.now(timezone.utc) - value.replace(tzinfo=timezone.utc) if value.tzinfo is None else datetime.now(timezone.utc) - value).total_seconds() / 60)
        return {"pending": counts.get("pending", 0), "approved": counts.get("approved", 0), "accepted": counts.get("accepted", 0), "rejected": counts.get("rejected", 0), "oldest_pending_age_minutes": age, "sla_breached": breached}


class PostgresTaskLog:
    def __init__(self, database_url: str, *, engine: Engine | None = None):
        self.database, self.engine = database_url, _engine(database_url, engine)

    def close(self):
        self.engine.dispose()

    def write(self, state):
        value = state.model_dump(mode="python")
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO tasks(task_id,task_type,assigned_agent,status,confidence,retry_count,escalated_to_human,failure_reason,issued_at,completed_at,payload_json,result_json,organization_id)
                VALUES (:id,:type,:agent,:status,:confidence,:retry,:escalated,:failure,:issued,:completed,:payload,:result,:org)
                ON CONFLICT (task_id,status) DO UPDATE SET task_type=EXCLUDED.task_type,assigned_agent=EXCLUDED.assigned_agent,confidence=EXCLUDED.confidence,retry_count=EXCLUDED.retry_count,escalated_to_human=EXCLUDED.escalated_to_human,failure_reason=EXCLUDED.failure_reason,issued_at=EXCLUDED.issued_at,completed_at=EXCLUDED.completed_at,payload_json=EXCLUDED.payload_json,result_json=EXCLUDED.result_json"""), {"id": value["task_id"], "type": value.get("task_type"), "agent": value.get("assigned_agent"), "status": value.get("status"), "confidence": value.get("confidence"), "retry": value.get("retry_count", 0), "escalated": 1 if value.get("escalated_to_human") else 0, "failure": value.get("failure_reason"), "issued": value.get("issued_at"), "completed": value.get("completed_at"), "payload": json.dumps(value.get("payload", {})), "result": json.dumps(value.get("result") or {}), "org": value.get("organization_id") or "default"})

    def get(self, task_id, *, organization_id):
        """The latest row, or None when missing or another organization's (``None`` = platform internals)."""
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM tasks WHERE task_id=:id AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org) ORDER BY issued_at DESC LIMIT 1"), {"id": task_id, "org": organization_id}).mappings().first()
        return dict(row) if row else None

    def update_status(self, task_id, task_type, new_status):
        with self.engine.begin() as c:
            c.execute(text("""INSERT INTO tasks(task_id,task_type,status,issued_at,completed_at,payload_json,result_json,retry_count,escalated_to_human,organization_id)
                VALUES (:id,:type,:status,:now,:now,'{}','{}',0,0,COALESCE((SELECT organization_id FROM tasks WHERE task_id=:id LIMIT 1),'default')) ON CONFLICT (task_id,status) DO NOTHING"""), {"id": task_id, "type": task_type, "status": new_status, "now": datetime.now(timezone.utc)})

    def recent(self, limit=50, *, organization_id):
        with self.engine.connect() as c:
            return [dict(row) for row in c.execute(text("SELECT * FROM tasks WHERE (CAST(:org AS TEXT) IS NULL OR organization_id=:org) ORDER BY issued_at DESC LIMIT :limit"), {"limit": limit, "org": organization_id}).mappings()]

    def throughput(self, hours=24, *, organization_id):
        with self.engine.connect() as c:
            rows = c.execute(text("""SELECT to_char(date_trunc('hour', issued_at::timestamptz), 'YYYY-MM-DD"T"HH24:00') AS bucket,
                COUNT(*) AS count FROM tasks
                WHERE issued_at::timestamptz >= now() - (:hours * INTERVAL '1 hour')
                  AND status IN ('complete','failed','escalated')
                  AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org)
                GROUP BY 1 ORDER BY 1"""), {"hours": hours, "org": organization_id}).all()
        return [{"bucket": row[0], "count": row[1]} for row in rows]

    def stats(self, *, organization_id):
        with self.engine.connect() as c:
            row = c.execute(text("SELECT COUNT(*) AS total,COUNT(*) FILTER (WHERE status='complete') AS complete,COUNT(*) FILTER (WHERE status='failed') AS failed,COUNT(*) FILTER (WHERE status='escalated') AS escalated FROM tasks WHERE (CAST(:org AS TEXT) IS NULL OR organization_id=:org)"), {"org": organization_id}).mappings().one()
        return dict(row)


class PostgresArtifactStore:
    def __init__(self, database_url: str, *, engine: Engine | None = None, object_storage: ObjectStorage | None = None):
        self.database, self.engine = database_url, _engine(database_url, engine)
        self.object_storage = object_storage

    def close(self):
        self.engine.dispose()

    def record(self, artifacts, workspace_root, task_id, skill, attempt_id=None, project_id=None, organization_id=None):
        results = []
        organization_id = organization_id or "default"
        with self.engine.begin() as c:
            for artifact in artifacts:
                filename, content = artifact["filename"], artifact["content"]
                key, digest = identity_key(workspace_root, filename, organization_id), hashlib.sha256(content.encode()).hexdigest()
                attempt_key = f"{attempt_id}::{key}" if attempt_id else None
                row = c.execute(text("SELECT identity_key,version FROM artifact_versions WHERE attempt_artifact_key=:attempt"), {"attempt": attempt_key}).mappings().first() if attempt_key else None
                if row:
                    results.append({"identity_key": row["identity_key"], "version": row["version"], "recorded": False}); continue
                row = c.execute(text("SELECT version,content_hash FROM artifact_versions WHERE identity_key=:key ORDER BY version DESC LIMIT 1"), {"key": key}).mappings().first()
                if row and row["content_hash"] == digest:
                    version, recorded = row["version"], False
                else:
                    version, recorded = (row["version"] + 1 if row else 1), True
                    object_id = f"{key}/v{version}" if self.object_storage else None
                    metadata = self.object_storage.put(object_id, content.encode(), media_type=artifact.get("media_type")) if object_id else None
                    try:
                        c.execute(text("""INSERT INTO artifact_versions
                            (identity_key,version,content,content_hash,filename,language,artifact_type,task_id,skill,created_at,attempt_artifact_key,object_id,object_size_bytes,media_type,project_id,organization_id)
                            VALUES (:key,:version,:content,:hash,:filename,:language,:kind,:task,:skill,:created,:attempt,:object_id,:size,:media_type,:project,:organization)"""), {"key": key, "version": version, "content": "" if metadata else content, "hash": digest, "filename": filename, "language": artifact.get("language"), "kind": artifact.get("artifact_type"), "task": task_id, "skill": skill, "created": datetime.now(timezone.utc), "attempt": attempt_key, "object_id": metadata.object_id if metadata else None, "size": metadata.size_bytes if metadata else None, "media_type": metadata.media_type if metadata else None, "project": project_id, "organization": organization_id})
                    except Exception:
                        if metadata:
                            self.object_storage.delete(metadata.object_id)
                        raise
                results.append({"identity_key": key, "version": version, "recorded": recorded})
        return results

    def list_files(self, *, organization_id):
        with self.engine.connect() as c:
            rows = c.execute(text("SELECT DISTINCT ON (identity_key) identity_key,filename,version AS latest_version,created_at AS updated_at,task_id FROM artifact_versions WHERE (CAST(:org AS TEXT) IS NULL OR organization_id=:org) ORDER BY identity_key,version DESC"), {"org": organization_id}).mappings().all()
        return [dict(row) for row in rows]

    def history(self, key, *, organization_id=None):
        with self.engine.connect() as c:
            return [dict(row) for row in c.execute(text("SELECT version,task_id,skill,created_at,content_hash FROM artifact_versions WHERE identity_key=:key AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org) ORDER BY version DESC"), {"key": key, "org": organization_id}).mappings()]

    def get_version(self, key, version, *, project_id=None, organization_id=None):
        with self.engine.connect() as c:
            row = c.execute(text("SELECT * FROM artifact_versions WHERE identity_key=:key AND version=:version AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org)"), {"key": key, "version": version, "org": organization_id}).mappings().first()
        result = dict(row) if row else None
        if result and self.object_storage and result.get("object_id"):
            ArtifactAccessPolicy().authorize(artifact_project_id=result.get("project_id"), artifact_organization_id=result.get("organization_id"), project_id=project_id, organization_id=organization_id if organization_id is not None else result.get("organization_id"))
            result["content"] = self.object_storage.get(result["object_id"]).decode()
        return result

    def latest_version_number(self, key, *, organization_id=None):
        with self.engine.connect() as c:
            return c.execute(text("SELECT MAX(version) FROM artifact_versions WHERE identity_key=:key AND (CAST(:org AS TEXT) IS NULL OR organization_id=:org)"), {"key": key, "org": organization_id}).scalar_one_or_none()

    def diff(self, key, from_version, to_version, *, organization_id=None):
        before, after = self.get_version(key, from_version, organization_id=organization_id), self.get_version(key, to_version, organization_id=organization_id)
        if before is None or after is None:
            raise KeyError(key)
        return "".join(difflib.unified_diff(before["content"].splitlines(True), after["content"].splitlines(True), fromfile=f"{key}@v{from_version}", tofile=f"{key}@v{to_version}"))
