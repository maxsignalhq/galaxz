from core.security import AuditLog, ExecutionPolicy, PolicyDenied, ReviewEvidencePackage


def test_execution_policy_is_default_deny_and_structured():
    policy = ExecutionPolicy()
    policy.validate_command(["python", "runner.py"])
    try:
        policy.validate_command(["sh", "-c", "cat secret"])
    except PolicyDenied as exc:
        assert exc.as_dict()["policy"] == "command"
    else:
        raise AssertionError("arbitrary shell command should be denied")


def test_execution_policy_rejects_path_escape(tmp_path):
    policy = ExecutionPolicy()
    try:
        policy.validate_path(tmp_path, tmp_path.parent / "outside")
    except PolicyDenied as exc:
        assert exc.as_dict()["error"] == "policy_denied"
    else:
        raise AssertionError("path escape should be denied")


def test_review_evidence_package_is_hash_verifiable():
    package = ReviewEvidencePackage({}, {}, "a" * 40, "b" * 64, [], {}, {}, "rigel", "model", "prompt", "attempt").as_dict()
    assert ReviewEvidencePackage.verify(package)
    package["artifacts"] = [{"filename": "changed.py"}]
    assert not ReviewEvidencePackage.verify(package)


def test_audit_log_is_hash_chained_and_tamper_evident(tmp_path):
    log = AuditLog(tmp_path / "audit.db")
    log.append(actor="reviewer", action="approve", reason="ok", evidence_version="v1")
    log.append(actor="operator", action="push", reason="approved", evidence_version="v1")
    events = log.export()
    assert AuditLog.verify(events)
    events[1]["event"]["reason"] = "tampered"
    assert not AuditLog.verify(events)
