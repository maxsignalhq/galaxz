from core.security import ArtifactScanOverride, scan_artifacts


def test_secret_and_unsafe_artifacts_are_versioned_and_blocked():
    scan = scan_artifacts([
        {"filename": "config.py", "content": "api_key = 'abcdefghijklmnop'"},
        {"filename": "payload.zip", "content": "archive"},
    ])
    assert scan.status == "blocked"
    assert scan.tool == "galaxz-artifact-scan"
    assert scan.version == "1.0"
    assert {item["rule"] for item in scan.findings} == {"generic-secret", "unsafe-file-type"}


def test_large_files_escalate_without_leaking_content():
    scan = scan_artifacts([{"filename": "model.bin", "content": "x" * 20}], max_bytes=10)
    assert scan.status == "escalate"
    assert {item["rule"] for item in scan.findings} == {"file-too-large", "unsafe-file-type"}
    assert all("content" not in item for item in scan.findings)


def test_false_positive_override_requires_recorded_approval():
    finding = "config.py:generic-secret"
    scan = scan_artifacts(
        [{"filename": "config.py", "content": "token = 'abcdefghijklmnop'"}],
        override=ArtifactScanOverride("reviewer-1", "approved", (finding,)),
    )
    assert scan.status == "passed"
    assert scan.overridden[0]["rule"] == "generic-secret"
    assert scan.reviewer_override["reviewer"] == "reviewer-1"
