"""Release gates for prompt-injection and malicious repository content."""

from __future__ import annotations

import re
from dataclasses import dataclass


_RULES = (
    ("instruction-override", re.compile(r"(?i)(ignore|disregard|override)\s+(all\s+)?(previous|system|security)\s+instructions")),
    ("secret-exfiltration", re.compile(r"(?i)(print|upload|send|post|exfiltrat\w*)\s+.{0,30}(secret|token|credential|environment)")),
    ("policy-bypass", re.compile(r"(?i)(disable|bypass|remove)\s+.{0,20}(sandbox|approval|network|security)")),
)


@dataclass(frozen=True)
class AdversarialFinding:
    rule: str
    severity: str
    source: str


def scan_untrusted_content(content: str, source: str = "untrusted") -> list[AdversarialFinding]:
    return [AdversarialFinding(rule, "critical", source) for rule, pattern in _RULES if pattern.search(content)]


def release_gate(contents: dict[str, str]) -> dict:
    findings = [finding for source, content in contents.items() for finding in scan_untrusted_content(content, source)]
    return {"status": "blocked" if findings else "passed", "findings": [finding.__dict__ for finding in findings], "rules_version": "1.0"}
