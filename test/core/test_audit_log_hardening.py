import logging
import sqlite3
import subprocess
import sys
import textwrap
import threading

from core.security import AuditLog
from core.security.audit import audit_event, default_audit_log


def _append(log, n, actor="a"):
    for i in range(n):
        log.append(actor=actor, action="x", reason=str(i))


def test_threads_share_one_log_without_forking_the_chain(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    threads = [threading.Thread(target=_append, args=(log, 25, f"t{i}")) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    result = log.verify_chain()
    assert result["valid"] and result["events"] == 150 and result["broken_at"] is None


def test_two_processes_appending_to_one_file_keep_a_single_chain(tmp_path):
    path = tmp_path / "audit.db"
    AuditLog(path)
    script = textwrap.dedent(
        """
        import sys
        from core.security import AuditLog
        log = AuditLog(sys.argv[1])
        for i in range(40):
            log.append(actor=sys.argv[2], action="x", reason=str(i))
        """
    )
    procs = [subprocess.Popen([sys.executable, "-c", script, str(path), name]) for name in ("p1", "p2", "p3")]
    assert [p.wait(timeout=60) for p in procs] == [0, 0, 0]
    result = AuditLog(path).verify_chain()
    assert result["valid"] and result["events"] == 120


def test_verify_chain_reports_where_a_stored_record_was_altered(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(path)
    _append(log, 5)
    with sqlite3.connect(path) as db:
        text = db.execute("SELECT event_json FROM audit_events WHERE sequence=3").fetchone()[0]
        db.execute("UPDATE audit_events SET event_json=? WHERE sequence=3", (text.replace('"reason":"2"', '"reason":"X"'),))
    result = log.verify_chain()
    assert result["valid"] is False and result["broken_at"] == 3


def test_verify_chain_detects_a_removed_middle_record(tmp_path):
    path = tmp_path / "audit.db"
    log = AuditLog(path)
    _append(log, 5)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM audit_events WHERE sequence=3")
    assert log.verify_chain()["valid"] is False


def test_empty_log_verifies_and_export_pages(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    assert log.verify_chain() == {"valid": True, "events": 0, "head": None, "broken_at": None}
    _append(log, 7)
    page = log.export(after=2, limit=3)
    assert [item["sequence"] for item in page] == [3, 4, 5]
    assert len(log.export()) == 7


def test_evidence_version_is_optional(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    out = log.append(actor="a", action="b", reason="c")
    assert out["event"]["evidence_version"] == "audit-v1"


def test_audit_event_writes_to_the_configured_database(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXZ_AUDIT_DB", str(tmp_path / "configured.db"))
    audit_event("alice", "thing.done", "because", skill="s", n=2)
    events = default_audit_log().export()
    assert len(events) == 1
    event = events[0]["event"]
    assert (event["actor"], event["action"], event["reason"]) == ("alice", "thing.done", "because")
    assert event["extra"] == {"skill": "s", "n": 2}


def test_audit_event_never_raises_and_logs_the_action(tmp_path, monkeypatch, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("GALAXZ_AUDIT_DB", str(blocker / "audit.db"))  # parent is a file
    with caplog.at_level(logging.ERROR):
        audit_event("alice", "thing.done", "because")
    assert "thing.done" in caplog.text
