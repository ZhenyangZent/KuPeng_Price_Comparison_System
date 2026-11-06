#!/usr/bin/env python3
"""Create the non-overwriting E08/R07 independent review ZIP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "review/E08/CDH_E_R07_002_HANDOFF"
OUTPUT = ROOT / "review/releases/CDH_E_R07_002_REVIEW.zip"
PAYLOADS = [
    "scripts/orchestrator_handoff/handoff_batch.py",
    "scripts/orchestrator_handoff/flat_queue.py",
    "scripts/orchestrator_handoff/handoff_continuity.py",
    "scripts/orchestrator_handoff/project_file_index.py",
    "scripts/orchestrator_handoff/package_dependency_audit.py",
    "scripts/orchestrator_handoff/package_e08_release.py",
    "tests/handoff/test_handoff_batch.py",
    "tests/handoff/test_flat_queue.py",
    "tests/handoff/test_handoff_continuity.py",
    "tests/handoff/test_project_file_index.py",
    "tests/handoff/test_e06_ack_handoff.py",
    "tests/handoff/test_e07_ack_continuity.py",
    "tests/handoff/test_package_dependency_audit.py",
    "review/E06/R05_EXACT_ACKS.json",
    "review/E07/R06_EXACT_ACKS.json",
    "review/E08/R07_EXACT_ACKS.json",
    "review/E08/PROJECT_FILE_INDEX_PRE_E08.csv",
    "review/E08/PACKAGE_README.md",
    "docs/HANDOFF/MASTER_HANDOFF.md",
    "docs/HANDOFF/versions/MASTER_HANDOFF_PRE_E08_20261105.md",
    "docs/HANDOFF/versions/PROJECT_FILE_INDEX_PRE_E08_20261105.csv",
    "docs/HANDOFF/UPLOAD_QUEUE_PROTOCOL.md",
    "docs/HANDOFF/WINDOWS_USAGE.md",
    "docs/HANDOFF/PROJECT_FILE_INDEX.csv",
    "docs/HANDOFF/EXTERNAL_PATH_LEDGER.csv",
    "docs/HANDOFF/RECEIPT_LEDGER.jsonl",
    "docs/HANDOFF/R05_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/R06_RECEIPT_STATUS_LEDGER.json",
    "docs/HANDOFF/WORKLINE_STATUS.md",
    "docs/HANDOFF/NEXT_ACTIONS.md",
    "docs/HANDOFF/CROSSLINE_STATUS_INDEX.md",
    "docs/HANDOFF/TASK_STATUS_INDEX.json",
    "docs/HANDOFF/LATEST_HANDOFF_STATUS.json",
    "docs/HANDOFF/PROTECTED_HASH_INVENTORY.json",
    "docs/HANDOFF/FIVE_MINUTE_STATUS.md",
    "reports/E08/INPUT_VALIDATION.json",
    "reports/E08/QUEUE_BEFORE.json",
    "reports/E08/QUEUE_AFTER_ARCHIVE.json",
    "reports/E08/ARCHIVE_EVIDENCE.json",
    "reports/E08/MODIFICATION_LIST.md",
    "reports/E08/RISK_REPORT.md",
    "reports/E08/TEST_EVIDENCE.md",
    "reports/E08/LOCAL_BUILD_REJECTION.json",
    "review/90_UPLOADED_ARCHIVE/20261105_R06_HANDOFF_ACK_20261105/ARCHIVE_RECEIPT.json",
]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_name(name: str, seen: set[str]) -> None:
    path = PurePosixPath(name)
    if not name or "\\" in name or name.startswith("/") or ".." in path.parts:
        raise RuntimeError(f"unsafe package path: {name}")
    key = name.casefold()
    if key in seen:
        raise RuntimeError(f"duplicate package path: {name}")
    seen.add(key)


def main() -> int:
    if OUTPUT.exists() or STAGING.exists():
        raise RuntimeError("E08 release or staging already exists; refusing overwrite")
    missing = [relative for relative in PAYLOADS if not (ROOT / relative).is_file()]
    if missing:
        raise RuntimeError(f"missing payloads: {missing}")
    STAGING.mkdir(parents=True)
    records: list[dict] = []
    for relative in PAYLOADS:
        source = ROOT / relative
        destination = STAGING / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append({"path": relative, "bytes": destination.stat().st_size, "sha256": digest(destination)})
    manifest = {
        "schema": "CDH-E08-R07-REVIEW-MANIFEST-2",
        "task_id": "CDH-E08-R06-ACK-ARCHIVE-AND-INDEX-001",
        "revision": 2,
        "supersedes_local_rejected_build": {
            "filename": "CDH_E_R07_001_REVIEW.zip",
            "sha256": "677f657c00d301f30cc88cd0dec83f4a23efc8090ac7970a659944f7eed95205"
        },
        "payload_count": len(records),
        "payloads": records,
    }
    manifest_path = STAGING / "REVIEW_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())
    seen: set[str] = set()
    with zipfile.ZipFile(OUTPUT, "r") as archive:
        for info in archive.infolist():
            validate_name(info.filename, seen)
        if archive.testzip() is not None:
            raise RuntimeError("release CRC failure")
        expected = {record["path"] for record in records} | {"REVIEW_MANIFEST.json"}
        if set(archive.namelist()) != expected:
            raise RuntimeError("release declared/actual path mismatch")
        for record in records:
            if hashlib.sha256(archive.read(record["path"])).hexdigest() != record["sha256"]:
                raise RuntimeError(f"payload hash mismatch: {record['path']}")
    print(json.dumps({
        "release": str(OUTPUT),
        "release_sha256": digest(OUTPUT),
        "release_bytes": OUTPUT.stat().st_size,
        "zip_entries": len(records) + 1,
        "manifest_payloads": len(records),
        "crc": "PASS",
        "path_safety": "PASS",
        "manifest_gate": "PASS",
    }, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        sys.exit(2)
