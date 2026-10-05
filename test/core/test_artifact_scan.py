import pytest

from core.security import ArtifactScanOverride, scan_artifacts
from core.security.artifact_scan import ArtifactSafetyError, require_safe_artifacts


def test_secret_and_unsafe_artifacts_are_versioned_and_blocked():
    scan = scan_artifacts([
        {"filename": "config.py", "content": "api_key = 'abcdefghijklmnop'"},
        {"filename": "payload.zip", "content": "archive"},
    ])
    assert scan.status == "blocked"
    assert scan.tool == "galaxz-artifact-scan"
    assert scan.version == "1.1"
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


def _status(code, filename="output.py"):
    return scan_artifacts([{"filename": filename, "content": code}]).status


@pytest.mark.parametrize(
    "code",
    [
        "api_key = os.environ.get('API_KEY')",
        "token = os.environ['TOKEN']",
        "token = os.getenv(\"GITHUB_TOKEN\")",
        "token = generate_session_token(user)",
        "password = request.form['password']",
        "api_key = config.api_key",
        "secret = secrets.token_hex(32)",
        "token = token_provider_function_name",
        "def get_env_vars():\n    api_key = os.environ.get('API_KEY')\n    token = os.environ.get('TOKEN')\n    return {'api_key': api_key, 'token': token}",
        "password = \"\"",
        "def add(a, b):\n    return a + b",
    ],
)
def test_reading_secrets_from_the_environment_is_not_a_leak(code):
    assert _status(code) == "passed"


@pytest.mark.parametrize(
    "code",
    [
        "SECRET_KEY = 'change-me-please-12345'",
        "DB_PASSWORD = \"p@ssw0rd-very-long\"",
        "api_key = \"sk-abcdef1234567890\"",
        "config = {\"token\": \"abcdefghijklmnop\"}",
        "API_KEY=sk1234567890abcdefgh",
        "password: hunter2hunter2hunter2",
        "-----BEGIN RSA PRIVATE KEY-----",
        "aws = 'AKIAABCDEFGHIJKLMNOP'",
    ],
)
def test_hardcoded_secrets_are_still_blocked(code):
    assert _status(code) == "blocked"


def test_safety_error_names_rule_and_file_but_not_content():
    with pytest.raises(ArtifactSafetyError) as exc:
        require_safe_artifacts([{"filename": "cfg.py", "content": "api_key = 'abcdefghijklmnop'"}])
    message = str(exc.value)
    assert message.startswith("artifact safety review required: blocked")
    assert "generic-secret" in message and "cfg.py" in message
    assert "abcdefghijklmnop" not in message
