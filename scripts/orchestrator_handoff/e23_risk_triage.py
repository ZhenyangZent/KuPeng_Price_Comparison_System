#!/usr/bin/env python3
"""Metadata-only triage of one immutable E23 historical audit checkpoint.

No ZIP member bytes are opened. Decisions are conservative publication gates,
not content approval. Real credentials and private databases remain unread.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "reports/E23/release_audit"
HARD_PRIVATE = {".sqlite", ".sqlite3", ".db", ".db3", ".pem", ".key", ".p12", ".pfx"}
MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf"}


def classify(item: dict) -> dict:
    path = ROOT / "review/releases" / item["filename"]
    if not path.is_file() or path.is_symlink():
        return {"filename": item["filename"], "decision": "ORIGINAL_EXCLUDE",
                "reason": "MISSING_OR_SYMLINK", "payload_open_count": 0}
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != item["expected_sha256"]:
        return {"filename": item["filename"], "decision": "ORIGINAL_EXCLUDE",
                "reason": "SHA_MISMATCH", "payload_open_count": 0}
    with zipfile.ZipFile(path) as z:
        names = [PurePosixPath(i.filename) for i in z.infolist() if not i.is_dir()]
    hard = 0
    media = 0
    nested = 0
    for name in names:
        parts = [p.casefold() for p in name.parts]
        base = parts[-1]
        if (base == ".env" or base.startswith(".env.") or base in {"cookies", "cookies.sqlite", "id_rsa", "id_ed25519"}
                or name.suffix.casefold() in HARD_PRIVATE or any(p in {"cookies", "credentials", "secrets"} for p in parts)):
            hard += 1
        if name.suffix.casefold() in MEDIA:
            media += 1
        if name.suffix.casefold() == ".zip":
            nested += 1
    reasons = item["reasons"]
    if hard:
        decision = "ORIGINAL_EXCLUDE_DERIVATIVE_ONLY"
        next_gate = "Remove restricted members without opening them; review remaining members and create hash-bound derivative"
    elif any(x in reasons for x in ("PERSONAL_PATH_PATTERN", "EMAIL_PATTERN", "PHONE_PATTERN", "CREDENTIAL_PATTERN", "PASSWORD_LITERAL_PATTERN")):
        decision = "DERIVATIVE_REDACTION_REVIEW"
        next_gate = "Identify and redact matching content in an isolated review; never publish original"
    elif nested or media or "NON_TEXT_MEMBER_REVIEW_REQUIRED" in reasons:
        decision = "DEEP_CONTENT_AND_PROVENANCE_REVIEW"
        next_gate = "Inspect only screened synthetic media or nested members in isolation, then verify provenance, manifest and CRC"
    else:
        decision = "DEEP_TEXT_AND_MANIFEST_REVIEW"
        next_gate = "Run bounded content, CRC and manifest checks before publication decision"
    return {"filename": item["filename"], "sha256": h, "decision": decision,
            "reason": sorted(reasons), "hard_private_member_count": hard,
            "media_member_count": media, "nested_member_count": nested,
            "payload_open_count": 0, "next_gate": next_gate}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--batch", type=int, required=True)
    args = p.parse_args()
    if args.batch < 0 or ROOT.name != "酷澎比價系統":
        raise RuntimeError("invalid batch or project root")
    src = AUDIT / f"batch_{args.batch:02d}.json"
    target = AUDIT / f"triage_batch_{args.batch:02d}.json"
    if target.exists():
        print(f"CHECKPOINT_EXISTS={target}")
        return
    batch = json.loads(src.read_text(encoding="utf-8"))
    blocked = [item for item in batch["items"] if item["status"] == "BLOCKED_FOR_UPLOAD"]
    rows = [classify(item) for item in blocked]
    result = {"schema": "CDH-E23-RISK-TRIAGE-1", "source_checkpoint": src.name,
              "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
              "blocked_count": len(rows), "rows": rows,
              "publication_approved_count": 0,
              "payload_open_count": 0}
    target.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    counts = {k: sum(r["decision"] == k for r in rows) for k in sorted({r["decision"] for r in rows})}
    print(json.dumps({"batch": args.batch, "blocked_count": len(rows), "decisions": counts,
                      "publication_approved_count": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
