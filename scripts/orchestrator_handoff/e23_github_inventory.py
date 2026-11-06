#!/usr/bin/env python3
"""E23 read-only publication inventory; never opens private paths or ZIP payloads."""
from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "HANDOFF"
SKIP_PARTS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
    ".vitest-temp", "dist", "build", "coverage", ".next", ".cache",
    "cache", "tmp", "temp", "logs", ".downloads", "site-packages",
}
SECRET_PARTS = {".env", ".ssh", "cookies", "credentials", "secrets", "profile"}
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".md",
            ".json", ".html", ".css", ".ps1", ".cmd", ".toml", ".yaml",
            ".yml", ".txt", ".csv", ".svg", ".ini", ".cfg"}
TOKEN = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|(?:sk-[A-Za-z0-9]{30,}))")
MAX_TEXT = 2_000_000
INDEX_NAMES = {"PROJECT_FILE_INDEX.csv", "GITHUB_UPLOAD_INVENTORY.csv"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def classify(rel: Path, size: int) -> tuple[str, str, str]:
    parts = [p.casefold() for p in rel.parts]
    name = rel.name.casefold()
    top = parts[0]
    if name in {n.casefold() for n in INDEX_NAMES} and top == "docs":
        return "INDEX_SELF", "SELF_GENERATED", "LOCAL_ONLY"
    if any(p in SECRET_PARTS or p.startswith(".env") for p in parts):
        return "SENSITIVE_PATH", "EXCLUDED_SECRET_NAME", "LOCAL_ONLY"
    if rel.suffix.casefold() in {".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12"}:
        return "PRIVATE_OR_BINARY_DATA", "EXCLUDED_PRIVATE_DATA", "LOCAL_ONLY"
    if any(p in SKIP_PARTS for p in parts):
        return "CACHE_OR_DEPENDENCY", "EXCLUDED_GENERATED", "LOCAL_ONLY"
    if top == "review":
        if len(parts) > 1 and parts[1] == "releases" and rel.suffix.casefold() == ".zip":
            return "IMMUTABLE_RELEASE", "RELEASE_REQUIRES_NESTED_REVIEW", "GITHUB_RELEASE_PENDING"
        return "REVIEW_EVIDENCE_OR_WORKSPACE", "EXCLUDED_PENDING_REVIEW", "LOCAL_ONLY"
    if top == "input":
        return "TASK_INPUT", "EXCLUDED_INPUT_AUTHORITY", "LOCAL_ONLY"
    if top == "reports":
        return "HISTORICAL_REPORT", "EXCLUDED_PENDING_CONTENT_REVIEW", "LOCAL_ONLY"
    if top in {"experiments", "research", "source_research", "data", "fixtures"}:
        return "RESEARCH_OR_DATA", "EXCLUDED_PENDING_SOURCE_REVIEW", "LOCAL_ONLY"
    if top not in {"apps", "services", "src", "tests", "scripts", "docs", "tools"} and len(parts) != 1:
        return "UNKNOWN", "EXCLUDED_UNKNOWN_SOURCE", "LOCAL_ONLY"
    if rel.suffix.casefold() not in TEXT_EXT and name not in {".gitignore", ".gitattributes"}:
        return "NON_TEXT", "EXCLUDED_PENDING_BINARY_REVIEW", "LOCAL_ONLY"
    if size > MAX_TEXT:
        return "LARGE_TEXT", "EXCLUDED_PENDING_SIZE_REVIEW", "LOCAL_ONLY"
    return "SOURCE_OR_DOCUMENT", "CANDIDATE_FOR_CONTENT_SCAN", rel.as_posix()


def main() -> int:
    if ROOT.name != "酷澎比價系統":
        raise RuntimeError("wrong project root")
    project_rows = []
    upload_rows = []
    counts: dict[str, int] = {}
    for current, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = sorted(x for x in dirs if x != ".git")
        for name in sorted(files):
            path = Path(current) / name
            rel = path.relative_to(ROOT)
            if path.is_symlink():
                category, decision, target = "SYMLINK", "EXCLUDED_NO_FOLLOW", "LOCAL_ONLY"
                size, sha = 0, "NOT_HASHED"
            else:
                try:
                    size = path.stat().st_size
                    category, decision, target = classify(rel, size)
                    if decision == "CANDIDATE_FOR_CONTENT_SCAN":
                        raw = path.read_bytes()
                        if TOKEN.search(raw):
                            decision, target = "EXCLUDED_POSSIBLE_CREDENTIAL", "LOCAL_ONLY"
                        elif b"\x00" in raw:
                            decision, target = "EXCLUDED_BINARY_CONTENT", "LOCAL_ONLY"
                        else:
                            decision = "SAFE_TEXT_CANDIDATE"
                        sha = hashlib.sha256(raw).hexdigest()
                    elif decision == "RELEASE_REQUIRES_NESTED_REVIEW":
                        sha = digest(path)
                    else:
                        sha = "NOT_HASHED_PROTECTED"
                except (OSError, PermissionError):
                    category, decision, target = "READ_ERROR", "EXCLUDED_READ_ERROR", "LOCAL_ONLY"
                    size, sha = 0, "NOT_HASHED"
            r = rel.as_posix()
            line = rel.parts[1] if rel.parts[0] in {"apps", "services", "reports"} and len(rel.parts)>1 else "UNKNOWN"
            if r.startswith("review/releases/"):
                match = re.match(r"CDH_([A-Z])", rel.name)
                line = match.group(1) if match else "UNKNOWN"
            task = "UNKNOWN"
            if r.startswith("reports/") and len(rel.parts)>1:
                task = rel.parts[1]
            role = "true" if category == "SOURCE_OR_DOCUMENT" else "false"
            release = "true" if category == "IMMUTABLE_RELEASE" else "false"
            evidence = "true" if category in {"HISTORICAL_REPORT", "REVIEW_EVIDENCE_OR_WORKSPACE"} else "false"
            secret = "true" if decision.startswith("EXCLUDED_POSSIBLE_CREDENTIAL") or category in {"SENSITIVE_PATH", "PRIVATE_OR_BINARY_DATA"} else "UNKNOWN"
            row = [r, rel.name, size, sha, line, task, category, role, release, evidence, secret, target, "UNKNOWN", decision, decision]
            project_rows.append(row)
            upload_rows.append([r, sha, size, category, decision, target])
            counts[decision] = counts.get(decision, 0) + 1
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "PROJECT_FILE_INDEX.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["original_relative_path", "filename", "bytes", "sha256", "workline", "task_id", "functional_category", "official_source", "official_release", "historical_evidence", "sensitive_or_private", "proposed_github_path", "same_content_exists", "final_result", "reason"]); w.writerows(project_rows)
    with (OUT / "GITHUB_UPLOAD_INVENTORY.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["original_relative_path", "sha256", "bytes", "category", "upload_decision", "proposed_github_path"]); w.writerows(upload_rows)
    for key in sorted(counts): print(f"{key}={counts[key]}")
    print(f"TOTAL={len(project_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
