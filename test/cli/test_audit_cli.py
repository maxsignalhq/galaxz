import sqlite3

from click.testing import CliRunner

from cli.run import galaxz
from core.security.audit import audit_event


def test_audit_verify_command(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXZ_AUDIT_DB", str(tmp_path / "a.db"))
    assert CliRunner().invoke(galaxz, ["audit", "verify"]).exit_code == 0
    audit_event("a", "x", "y")
    ok = CliRunner().invoke(galaxz, ["audit", "verify"])
    assert ok.exit_code == 0 and "valid" in ok.output and "1 event" in ok.output
    with sqlite3.connect(tmp_path / "a.db") as db:
        db.execute("UPDATE audit_events SET event_json = replace(event_json, '\"x\"', '\"z\"')")
    bad = CliRunner().invoke(galaxz, ["audit", "verify"])
    assert bad.exit_code == 1 and "BROKEN" in bad.output
