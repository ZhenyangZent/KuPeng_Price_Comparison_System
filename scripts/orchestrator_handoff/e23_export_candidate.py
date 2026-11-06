#!/usr/bin/env python3
"""Create a conservative public Git candidate from the E23 inventory."""
from __future__ import annotations

import csv
import hashlib
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "review" / "E23_GITHUB_CANDIDATE" / "repo"
INDEX = ROOT / "docs" / "HANDOFF" / "GITHUB_UPLOAD_INVENTORY.csv"
TOKEN = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|sk-[A-Za-z0-9]{30,})")
EMAIL = re.compile(rb"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
WIN_USER = re.compile(rb"C:[\\/]Users[\\/][^\\/\s\"']+", re.I)
PASSWORD_ASSIGNMENT = re.compile(rb"(?:password|passwd|client_secret|api_key|access_token)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.I)
SKIP = {
    "docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv",
    "docs/HANDOFF/RECEIPT_LEDGER.jsonl",
    "docs/HANDOFF/PROJECT_FILE_INDEX.csv",
    "docs/HANDOFF/GITHUB_UPLOAD_INVENTORY.csv",
}


def main() -> int:
    if DEST.exists():
        raise RuntimeError("candidate already exists; refusing to replace")
    DEST.mkdir(parents=True)
    accepted, excluded = [], []
    with INDEX.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rel = row["original_relative_path"]
            if row["upload_decision"] != "SAFE_TEXT_CANDIDATE":
                continue
            if rel in SKIP or rel.startswith("docs/HANDOFF/versions/"):
                excluded.append((rel, "PUBLIC_METADATA_OR_HISTORICAL_DUPLICATE")); continue
            source = ROOT / rel
            try:
                raw = source.read_bytes()
            except OSError:
                excluded.append((rel, "READ_ERROR")); continue
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                excluded.append((rel, "SOURCE_CHANGED_AFTER_INVENTORY")); continue
            if rel in {"docs/HANDOFF/MASTER_HANDOFF.md", "docs/HANDOFF/CURRENT_STATE.json", "docs/RULES/PROJECT_GUARDRAILS.md"}:
                raw = WIN_USER.sub(b"LOCAL_USER_HOME", raw)
            if TOKEN.search(raw) or EMAIL.search(raw) or WIN_USER.search(raw) or PASSWORD_ASSIGNMENT.search(raw):
                excluded.append((rel, "POSSIBLE_PERSONAL_OR_CREDENTIAL")); continue
            target = DEST / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            accepted.append((rel, hashlib.sha256(raw).hexdigest(), len(raw)))
    out = ROOT / "reports" / "E23" / "GIT_CHANGE_MANIFEST.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["repository_relative_path", "sha256", "bytes", "action", "source"])
        for rel, sha, size in accepted:
            writer.writerow([rel, sha, size, "ADD", rel])
    exclusions = ROOT / "reports" / "E23" / "EXPORT_EXCLUSIONS.csv"
    with exclusions.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f); writer.writerow(["relative_path", "reason"]); writer.writerows(excluded)
    public_index = DEST / "docs" / "HANDOFF" / "PROJECT_FILE_INDEX.csv"
    with public_index.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_path", "sha256", "bytes", "publication_scope"])
        for rel, sha, size in accepted:
            writer.writerow([rel, sha, size, "PUBLIC_TEXT_CANDIDATE"])
    public_upload = DEST / "docs" / "HANDOFF" / "GITHUB_UPLOAD_INVENTORY.csv"
    with public_upload.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["publication_scope", "file_count", "note"])
        writer.writerow(["PUBLIC_TEXT_CANDIDATE", len(accepted), "See PROJECT_FILE_INDEX.csv"])
        writer.writerow(["LOCAL_ONLY_EXCLUDED", len(excluded), "Detailed exclusions remain in the local E23 report"])
    public_external = DEST / "docs" / "HANDOFF" / "EXTERNAL_PATH_LEDGER.csv"
    with public_external.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["record_id", "publication_status", "reason"])
        writer.writerow(["LOCAL_EXTERNAL_PATH_LEDGER", "REDACTED", "Absolute external paths and historical environment details remain in the local ledger"])
    print(f"CANDIDATE={DEST}")
    print(f"ACCEPTED={len(accepted)} EXCLUDED_SECOND_PASS={len(excluded)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
