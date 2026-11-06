"""Build and independently verify the H01 review handoff."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "review" / "H01"
STAGING = REVIEW / "package" / "CDH_H01_001_REVIEW"
ARCHIVE = REVIEW / "CDH_H01_001_REVIEW.zip"
RELEASE = ROOT / "review" / "releases" / ARCHIVE.name
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / ARCHIVE.name
VERIFY = REVIEW / "verify_extracted" / "CDH_H01_001_REVIEW"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_member(name: str) -> bool:
    value = PurePosixPath(name)
    return not value.is_absolute() and ".." not in value.parts and not (value.parts and ":" in value.parts[0])


def copy_tree(relative: str) -> None:
    source = ROOT / relative
    target = STAGING / relative
    if not source.is_dir():
        raise RuntimeError(f"missing handoff source: {relative}")
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime", "package", "verify_extracted", "CDH_H01_001_REVIEW.zip"))


def main() -> int:
    if STAGING.exists() or VERIFY.exists() or ARCHIVE.exists():
        raise RuntimeError("H01 package outputs already exist; preserve prior evidence and use a clean handoff revision")
    STAGING.mkdir(parents=True)
    for relative in ("tools/web_journey_e2e", "tests/web/journey_e2e", "reports/H01"):
        copy_tree(relative)
    package_info = {
        "schema": "CDH-H01-PACKAGE-INFO-V1",
        "task_id": "CDH-H01-WEB-JOURNEY-E2E-001",
        "role": "H",
        "status": "READY_FOR_REVIEW",
        "mvp_readiness": "WAITING_A06",
        "data_classification": "SYNTHETIC_DEMO_ONLY",
        "authority_sha256": "08fb652c86647d15b624cb8e785bafd8b2ee065932966c24ab7932b1754de280",
        "a05_release_sha256": "66652edfd641869ac63ea44c0254e712441fceccd77ea3bb78f706120cb14d0e",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (STAGING / "PACKAGE_INFO.json").write_text(json.dumps(package_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payloads = []
    for file in sorted(item for item in STAGING.rglob("*") if item.is_file()):
        relative = file.relative_to(STAGING).as_posix()
        if relative in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        if file.name == ".env" or ".env/" in relative:
            raise RuntimeError("real .env is forbidden")
        payloads.append({"path": relative, "sha256": digest(file), "size": file.stat().st_size})
    manifest = {
        "schema": "CDH-H01-MANIFEST-V1",
        "algorithm": "SHA-256",
        "payload_count": len(payloads),
        "files": payloads,
    }
    (STAGING / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (STAGING / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in payloads), encoding="utf-8")
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(item for item in STAGING.rglob("*") if item.is_file()):
            archive.write(file, file.relative_to(STAGING).as_posix())
    with zipfile.ZipFile(ARCHIVE) as archive:
        bad_crc = archive.testzip()
        names = archive.namelist()
        if bad_crc is not None or len(names) != len(set(names)) or not all(safe_member(name) for name in names):
            raise RuntimeError(f"ZIP safety/CRC failed: {bad_crc}")
        archive.extractall(VERIFY)
    extracted_manifest = json.loads((VERIFY / "MANIFEST.json").read_text(encoding="utf-8"))
    mismatches = []
    declared = {item["path"] for item in extracted_manifest["files"]}
    for item in extracted_manifest["files"]:
        file = VERIFY / Path(*PurePosixPath(item["path"]).parts)
        if not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
            mismatches.append(item["path"])
    actual_payloads = {
        file.relative_to(VERIFY).as_posix()
        for file in VERIFY.rglob("*") if file.is_file() and file.relative_to(VERIFY).as_posix() not in {"MANIFEST.json", "SHA256SUMS.txt"}
    }
    undeclared = sorted(actual_payloads - declared)
    missing = sorted(declared - actual_payloads)
    if mismatches or undeclared or missing:
        raise RuntimeError(f"manifest verification failed: mismatch={mismatches} undeclared={undeclared} missing={missing}")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ARCHIVE, RELEASE)
    shutil.copyfile(ARCHIVE, UPLOAD)
    archive_hash = digest(ARCHIVE)
    if digest(RELEASE) != archive_hash or digest(UPLOAD) != archive_hash:
        raise RuntimeError("release/upload byte identity failed")
    summary = {
        "status": "PASS",
        "archive": str(ARCHIVE),
        "release": str(RELEASE),
        "upload": str(UPLOAD),
        "sha256": archive_hash,
        "manifest_sha256": digest(STAGING / "MANIFEST.json"),
        "payload_count": len(payloads),
        "entry_count": len(names),
        "crc": "PASS",
        "safe_extract": "PASS",
        "missing": len(missing),
        "mismatch": len(mismatches),
        "undeclared": len(undeclared),
        "duplicates": len(names) - len(set(names)),
        "byte_identical_copies": True,
    }
    (REVIEW / "FINAL_READBACK.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001 - terminal packager must surface exact failure
        print(f"PACKAGE_ERROR: {error}", file=sys.stderr)
        raise

