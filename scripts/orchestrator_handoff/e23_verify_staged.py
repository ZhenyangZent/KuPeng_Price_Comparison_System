#!/usr/bin/env python3
"""Fail closed on sensitive staged Git blobs and verify the public SHA index."""
from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "review/E23_GITHUB_CANDIDATE/repo"
INDEX = "docs/HANDOFF/PROJECT_FILE_INDEX.csv"
DENY = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|sk-[A-Za-z0-9]{30,}|[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|C:[\\/]Users[\\/][^\\/\s\"']+|(?:password|passwd|client_secret|api_key|access_token)\s*[:=]\s*[\"'][^\"']{8,}[\"'])", re.I)
FORBIDDEN = {".env", ".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx", ".zip", ".png", ".jpg", ".jpeg"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=DEST)


def main() -> None:
    assert ROOT.name == "酷澎比價系統" and (DEST / ".git").is_dir()
    names = sorted(p.decode("utf-8") for p in git("ls-files", "--cached", "-z").split(b"\0") if p)
    staged = {}
    for name in names:
        path = Path(name)
        if any(part.casefold() in {".git", ".venv", "cookies", "credentials", "secrets"} for part in path.parts):
            raise RuntimeError(f"sensitive staged path: {name}")
        if path.suffix.casefold() in FORBIDDEN or path.name.casefold() == ".env":
            raise RuntimeError(f"forbidden staged file type: {name}")
        data = git("show", ":" + name)
        if DENY.search(data) or b"\x00" in data:
            raise RuntimeError(f"sensitive staged blob: {name}")
        staged[name] = (hashlib.sha256(data).hexdigest(), len(data))
    index_data = git("show", ":" + INDEX).decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(index_data)))
    if len(rows) != len(staged) - 1:
        raise RuntimeError("public index row count mismatch")
    for row in rows:
        name = row["relative_path"]
        if name == INDEX or name not in staged:
            raise RuntimeError(f"public index path mismatch: {name}")
        if (row["sha256"], int(row["bytes"])) != staged[name]:
            raise RuntimeError(f"public index hash or size mismatch: {name}")
    print(f"STAGED_FILES={len(staged)} INDEX_MATCH={len(rows)} SENSITIVE_FINDINGS=0")


if __name__ == "__main__":
    main()
