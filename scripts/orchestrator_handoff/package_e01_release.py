#!/usr/bin/env python3
"""Create the non-overwriting E01 review staging directory and release ZIP."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / "review/E01/CDH_E01_001_HANDOFF"
OUTPUT = ROOT / "review/releases/CDH_E01_001_REVIEW.zip"
PAYLOADS = [
    "scripts/orchestrator_handoff/handoff_batch.py",
    "scripts/orchestrator_handoff/package_e01_release.py",
    "tests/handoff/test_handoff_batch.py",
    "docs/HANDOFF/WINDOWS_USAGE.md",
    "docs/HANDOFF/CONTRACT_PROPOSAL.md",
    "reports/E01/CHANGELOG.md",
    "reports/E01/MODIFICATION_LIST.md",
    "reports/E01/RISK_REPORT.md",
    "reports/E01/TEST_EVIDENCE.md",
    "reports/E01/HISTORICAL_RELEASE_INTEGRITY.json",
    "reports/E01/INPUT_VALIDATION.json",
    "experiments/E01/SYNTHETIC_DEMO_EVIDENCE.json",
    "review/E01/PACKAGE_README.md",
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
        raise RuntimeError("E01 release or staging already exists; refusing overwrite")
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
        records.append(
            {"path": relative, "bytes": destination.stat().st_size, "sha256": digest(destination)}
        )
    manifest = {
        "schema": "CDH-E01-REVIEW-MANIFEST-1",
        "task": "CDH-E01-HANDOFF-BATCH-001",
        "payload_count": len(records),
        "payloads": records,
    }
    manifest_path = STAGING / "REVIEW_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())

    seen: set[str] = set()
    with zipfile.ZipFile(OUTPUT, "r") as archive:
        for info in archive.infolist():
            validate_name(info.filename, seen)
        damaged = archive.testzip()
        if damaged is not None:
            raise RuntimeError(f"release CRC failed: {damaged}")
        saved = json.loads(archive.read("REVIEW_MANIFEST.json"))
        if saved != manifest:
            raise RuntimeError("release manifest readback mismatch")
        names = set(archive.namelist())
        expected = {item["path"] for item in records} | {"REVIEW_MANIFEST.json"}
        if names != expected:
            raise RuntimeError("release declared/actual path mismatch")
        for item in records:
            actual = hashlib.sha256(archive.read(item["path"])).hexdigest()
            if actual != item["sha256"]:
                raise RuntimeError(f"release payload hash mismatch: {item['path']}")

    result = {
        "release": str(OUTPUT),
        "release_sha256": digest(OUTPUT),
        "release_bytes": OUTPUT.stat().st_size,
        "zip_entries": len(records) + 1,
        "manifest_payloads": len(records),
        "crc": "PASS",
        "path_safety": "PASS",
        "manifest_gate": "PASS",
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        sys.exit(2)
