#!/usr/bin/env python3
"""E23 public-release gate, read-only and resumable by stable 20-file batches.

Only text-only ZIPs without nested archives or private-looking member paths are
opened for content/CRC checks. Blocked members are never extracted or read.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import unicodedata
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "E23" / "release_audit"
TEXT_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs", ".md", ".json",
            ".jsonl", ".html", ".css", ".ps1", ".cmd", ".toml", ".yaml", ".yml",
            ".txt", ".csv", ".ini", ".cfg", ".xml", ".sh", ".sql"}
TEXT_NAMES = {"license", "license.txt", "readme", ".gitignore", ".gitattributes"}
FORBIDDEN_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", "profile", "cookies", "secrets", "credentials"}
SENSITIVE_SUFFIX = {".sqlite", ".sqlite3", ".db", ".pem", ".key", ".p12", ".pfx", ".reg", ".log"}
PATTERNS = {
    "CREDENTIAL_PATTERN": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN (?:RSA|OPENSSH|EC|DSA|PRIVATE) KEY-----|sk-[A-Za-z0-9]{30,}|(?:Authorization:\s*Bearer\s+)[A-Za-z0-9._-]{12,})", re.I),
    "EMAIL_PATTERN": re.compile(rb"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "PERSONAL_PATH_PATTERN": re.compile(rb"C:[\\/]Users[\\/][^\\/\s\"']+", re.I),
    "PASSWORD_LITERAL_PATTERN": re.compile(rb"(?:password|passwd|client_secret|api_key|access_token)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.I),
    "PHONE_PATTERN": re.compile(rb"(?<![0-9])09[0-9]{8}(?![0-9])"),
}
MAX_TEXT_MEMBER = 2_000_000
MAX_UNCOMPRESSED = 50_000_000
MAX_ASSET = 2_000_000_000
BATCH_SIZE = 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def member_reason(info: zipfile.ZipInfo) -> str | None:
    name = info.filename
    if info.is_dir():
        return None
    if not name or "\\" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return "UNSAFE_MEMBER_PATH"
    parts = name.split("/")
    if any(p in {"", ".", ".."} or p.rstrip(" .") != p or ":" in p for p in parts):
        return "UNSAFE_MEMBER_PATH"
    if (info.external_attr >> 16) & 0o170000 == 0o120000:
        return "SYMLINK_MEMBER"
    if info.flag_bits & 1:
        return "ENCRYPTED_MEMBER"
    lower = [unicodedata.normalize("NFC", p).casefold() for p in parts]
    basename = lower[-1]
    if any(p in FORBIDDEN_PARTS or p.startswith(".env") for p in lower):
        return "SENSITIVE_MEMBER_PATH"
    if basename in {".env", "id_rsa", "id_ed25519"} or Path(basename).suffix in SENSITIVE_SUFFIX:
        return "SENSITIVE_MEMBER_PATH"
    if basename.endswith(".zip"):
        return "NESTED_ZIP"
    if "vendor" in lower or "third_party" in lower:
        return "THIRD_PARTY_SOURCE_REVIEW_REQUIRED"
    if Path(basename).suffix not in TEXT_EXT and basename not in TEXT_NAMES:
        return "NON_TEXT_MEMBER_REVIEW_REQUIRED"
    if info.file_size > MAX_TEXT_MEMBER:
        return "LARGE_MEMBER_REVIEW_REQUIRED"
    return None


def audit(row: dict) -> dict:
    name = row["filename"]
    path = ROOT / "review" / "releases" / name
    result = {"filename": name, "expected_sha256": row["sha256"], "actual_sha256": "UNKNOWN",
              "status": "BLOCKED_FOR_UPLOAD", "reasons": [], "crc": "NOT_RUN",
              "manifest": "NOT_RUN", "member_count": 0, "nested_zip_count": 0,
              "sensitive_member_count": 0, "content_checked_count": 0,
              "github_download_url": "NOT_PUBLISHED"}
    reasons: set[str] = set()
    if not path.is_file() or path.is_symlink():
        reasons.add("RELEASE_MISSING_OR_SYMLINK")
        result["reasons"] = sorted(reasons)
        return result
    size = path.stat().st_size
    result["bytes"] = size
    if size >= MAX_ASSET:
        reasons.add("GITHUB_RELEASE_ASSET_SIZE_LIMIT")
    actual = sha256_file(path)
    result["actual_sha256"] = actual
    if actual != row["sha256"]:
        reasons.add("LEDGER_SHA_MISMATCH")
        result["reasons"] = sorted(reasons)
        return result
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            result["member_count"] = len(infos)
            if not infos:
                reasons.add("EMPTY_ZIP")
            keys = [unicodedata.normalize("NFC", i.filename).rstrip(" .").casefold() for i in infos]
            if len(keys) != len(set(keys)):
                reasons.add("DUPLICATE_MEMBER_PATH")
            if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
                reasons.add("LARGE_UNCOMPRESSED_REVIEW_REQUIRED")
            for info in infos:
                why = member_reason(info)
                if why:
                    reasons.add(why)
                    if why == "NESTED_ZIP": result["nested_zip_count"] += 1
                    if why == "SENSITIVE_MEMBER_PATH": result["sensitive_member_count"] += 1
            if not reasons:
                for info in infos:
                    if info.is_dir(): continue
                    data = z.read(info)
                    result["content_checked_count"] += 1
                    if b"\x00" in data:
                        reasons.add("BINARY_CONTENT")
                    for label, regex in PATTERNS.items():
                        if regex.search(data): reasons.add(label)
                if not reasons:
                    result["crc"] = "PASS" if z.testzip() is None else "FAIL"
                    if result["crc"] != "PASS": reasons.add("CRC_FAIL")
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
        reasons.add("ZIP_STRUCTURE_ERROR_" + type(exc).__name__)
    if not reasons:
        # Existing strict validator checks path safety and every authoritative
        # manifest record. Import lazily so blocked ZIP payloads are not read.
        try:
            from flat_queue import validate_release
            check = validate_release(path)
            result["manifest"] = check["manifest_gate"]
            if check["manifest_gate"] != "PASS": reasons.add("MANIFEST_FAIL")
        except Exception as exc:
            reasons.add("STRICT_MANIFEST_OR_PATH_FAIL_" + type(exc).__name__)
    result["reasons"] = sorted(reasons)
    if not reasons:
        result["status"] = "ELIGIBLE_FOR_PUBLICATION_REVIEW"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=int, required=True)
    args = parser.parse_args(argv)
    if ROOT.name != "酷澎比價系統": raise RuntimeError("wrong project root")
    rows = list(csv.DictReader((ROOT / "docs/HANDOFF/RELEASE_LEDGER.csv").open(encoding="utf-8", newline="")))
    rows = sorted((r for r in rows if not r["filename"].startswith("CDH_E_R13_00")), key=lambda r: r["filename"].casefold())
    if len(rows) != 140: raise RuntimeError(f"expected 140 historical releases; found {len(rows)}")
    selected = rows[args.batch * BATCH_SIZE:(args.batch + 1) * BATCH_SIZE]
    if not selected: raise RuntimeError("batch outside range")
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"batch_{args.batch:02d}.json"
    if target.exists():
        print(f"CHECKPOINT_EXISTS={target}")
        return 0
    audited = [audit(row) for row in selected]
    payload = {"schema": "CDH-E23-RELEASE-AUDIT-1", "batch": args.batch,
               "batch_size": BATCH_SIZE, "historical_total": len(rows), "items": audited}
    with target.open("x", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n"); f.flush(); os.fsync(f.fileno())
    eligible = sum(x["status"] == "ELIGIBLE_FOR_PUBLICATION_REVIEW" for x in audited)
    print(f"BATCH={args.batch} ITEMS={len(audited)} ELIGIBLE={eligible} BLOCKED={len(audited)-eligible}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
