"""Deterministic pre-review checks for generated artifacts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


SCANNER_NAME = "galaxz-artifact-scan"
SCANNER_VERSION = "1.1"
# A secret-like name assigned a hardcoded value. Code that merely *reads* a
# secret (os.environ.get(...), generate_token(...), config.api_key) is not a leak.
_SECRET_NAME = r"\b\w*(?:api[_-]?key|secret|password|passwd|token)\w*[\"']?\s*[:=]\s*"
_QUOTED_LITERAL = r"(?:\"[^\s\"']{12,}\"|'[^\s\"']{12,}')"
# Unquoted values (.env / YAML): long, token-like, containing a digit, and not
# the start of a call, attribute or subscript.
_BARE_LITERAL = r"(?<![\w.])(?=[A-Za-z0-9_\-+/=]*\d)[A-Za-z0-9_\-+/=]{16,}(?![\w(.\[])"
_SECRET_RULES = (
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic-secret", re.compile(r"(?i)" + _SECRET_NAME + "(?:" + _QUOTED_LITERAL + "|" + _BARE_LITERAL + ")")),
)
_UNSAFE_EXTENSIONS = {".exe", ".dll", ".so", ".dylib", ".bin", ".pyc", ".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".jar"}


@dataclass(frozen=True)
class ArtifactScanOverride:
    reviewer: str
    decision: str
    findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactScan:
    tool: str
    version: str
    status: str
    findings: tuple[dict, ...]
    overridden: tuple[dict, ...] = ()
    reviewer_override: dict | None = None

    def as_dict(self) -> dict:
        return {
            "tool": self.tool,
            "version": self.version,
            "status": self.status,
            "findings": list(self.findings),
            "overridden": list(self.overridden),
            "reviewer_override": self.reviewer_override,
        }


class ArtifactSafetyError(ValueError):
    def __init__(self, scan: ArtifactScan):
        self.scan = scan
        # Rule and filename only; never the matched content.
        detail = ", ".join(sorted({f"{f['rule']} in {f['filename']}" for f in scan.findings})[:5])
        super().__init__(
            f"artifact safety review required: {scan.status}" + (f" ({detail})" if detail else "")
        )


def require_safe_artifacts(artifacts: list[dict]) -> ArtifactScan:
    scan = scan_artifacts(artifacts)
    if scan.status != "passed":
        raise ArtifactSafetyError(scan)
    return scan


def scan_artifacts(artifacts: list[dict], *, max_bytes: int | None = None, override: ArtifactScanOverride | None = None) -> ArtifactScan:
    limit = max_bytes or int(os.getenv("GALAXZ_ARTIFACT_MAX_BYTES", str(50 * 1024 * 1024)))
    findings: list[dict] = []
    for artifact in artifacts:
        filename = str(artifact.get("filename", ""))
        content = str(artifact.get("content", ""))
        size = len(content.encode("utf-8"))
        if size > limit:
            findings.append({"rule": "file-too-large", "severity": "high", "filename": filename})
        if any(filename.lower().endswith(extension) for extension in _UNSAFE_EXTENSIONS):
            findings.append({"rule": "unsafe-file-type", "severity": "high", "filename": filename})
        for rule, pattern in _SECRET_RULES:
            if pattern.search(content):
                findings.append({"rule": rule, "severity": "critical", "filename": filename})

    overridden: list[dict] = []
    if override is not None and override.reviewer.strip() and override.decision == "approved":
        accepted = set(override.findings)
        remaining = []
        for finding in findings:
            key = f"{finding['filename']}:{finding['rule']}"
            (overridden if key in accepted else remaining).append(finding)
        findings = remaining
    status = "blocked" if any(item["severity"] == "critical" for item in findings) else ("escalate" if findings else "passed")
    return ArtifactScan(SCANNER_NAME, SCANNER_VERSION, status, tuple(findings), tuple(overridden), {
        "reviewer": override.reviewer, "decision": override.decision, "findings": list(override.findings)
    } if override else None)
