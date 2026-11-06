from __future__ import annotations

import re

from .models import Check, Finding


SENSITIVE_NAME = re.compile(r"(?:SECRET|TOKEN|PASSWORD|PRIVATE|ACCESS[_-]?KEY|CLIENT[_-]?SECRET)", re.I)
PLACEHOLDER = re.compile(r"^(?:|placeholder|changeme|example|not[_-]?set|none|null|<[^>]+>)$", re.I)


def audit_env_example(name: str, raw: bytes) -> tuple[list[Check], list[Finding]]:
    checks: list[Check] = []
    findings: list[Finding] = []
    safe_name = name.casefold() == ".env.example"
    checks.append(Check("ENV_FILENAME_PLACEHOLDER_ONLY", safe_name, name))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
        safe_name = False
    assignments: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        assignments.append((key.strip(), value.strip().strip('"\'')))
    bad = []
    for key, value in assignments:
        if SENSITIVE_NAME.search(key) and not PLACEHOLDER.fullmatch(value):
            bad.append(key)
        if re.search(r"-----BEGIN [A-Z ]+PRIVATE KEY-----", value):
            bad.append(key)
        if re.match(r"https?://", value, re.I) and not re.match(r"http://(?:127\.0\.0\.1|localhost)(?::\d+)?(?:/|$)", value, re.I):
            bad.append(key)
    passed = safe_name and not bad
    checks.append(Check("ENV_VALUES_INERT", passed, f"assignments={len(assignments)}; unsafe={sorted(set(bad))}"))
    if not passed:
        findings.append(Finding(
            "D05-P0-004", "P0", "A/F", "Environment example contains a secret-like or external live value",
            name,
            "A frontend/provider example file must contain placeholders only and may not embed credentials or a live external endpoint.",
            "Run the D05 env audit against the exact archive member.",
            "Keep .env.example inert and add package secret scanning; never include .env.",
        ))
    return checks, findings
