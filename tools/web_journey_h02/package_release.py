"""Build and verify the H02 escalation handoff without packaging baselines/runtime."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "review" / "H02"
STAGING = REVIEW / "package" / "CDH_H02_001_REVIEW"
ARCHIVE = REVIEW / "CDH_H02_001_REVIEW.zip"
RELEASE = ROOT / "review" / "releases" / ARCHIVE.name
UPLOAD = ROOT / "review" / "00_TO_UPLOAD" / ARCHIVE.name
VERIFY = REVIEW / "verify_extracted" / "CDH_H02_001_REVIEW"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_name(name: str) -> bool:
    value = PurePosixPath(name)
    return "\\" not in name and not value.is_absolute() and ".." not in value.parts and not (value.parts and ":" in value.parts[0])


def copy_tree(relative: str) -> None:
    shutil.copytree(
        ROOT / relative,
        STAGING / relative,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime", "baselines", "package", "verify_extracted", "CDH_H02_001_REVIEW.zip"),
    )


def main() -> int:
    if any(path.exists() for path in (STAGING, ARCHIVE, RELEASE, UPLOAD, VERIFY)):
        raise RuntimeError("refusing to overwrite an H02 handoff artifact")
    STAGING.mkdir(parents=True)
    for relative in ("tools/web_journey_h02", "tests/web/journey_h02", "reports/H02"):
        copy_tree(relative)
    package_info = {
        "schema": "CDH-H02-PACKAGE-INFO-V1",
        "task_id": "CDH-H02-A06-B06-WEB-E2E-001",
        "status": "ESCALATION_REQUIRED",
        "e2e_gate": "FAIL_CONTRACT_CLASSIFICATION_MISMATCH",
        "a06_sha256": "d9fce75d876b86d5cbb28f77e8ff9354e9d38a5c9389abe10d2a2ddc46adefb5",
        "b06_sha256": "d99284c7e6d422b16255b51d29aacb5034a1d43b254c4aca6fa389cef6caf3ae",
    }
    (STAGING / "PACKAGE_INFO.json").write_text(json.dumps(package_info, indent=2) + "\n", encoding="utf-8")
    payloads = []
    for file in sorted(item for item in STAGING.rglob("*") if item.is_file()):
        relative = file.relative_to(STAGING).as_posix()
        if file.name == ".env":
            raise RuntimeError("real .env is forbidden")
        payloads.append({"path": relative, "sha256": digest(file), "size": file.stat().st_size})
    manifest = {"schema": "CDH-H02-MANIFEST-V1", "algorithm": "SHA-256", "payload_count": len(payloads), "files": payloads}
    (STAGING / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(item for item in STAGING.rglob("*") if item.is_file()):
            archive.write(file, file.relative_to(STAGING).as_posix())
    with zipfile.ZipFile(ARCHIVE) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        lowered = [name.casefold() for name in names]
        symlinks = [item.filename for item in infos if stat.S_ISLNK((item.external_attr >> 16) & 0xFFFF)]
        bad = archive.testzip()
        if bad or len(names) != len(set(names)) or len(lowered) != len(set(lowered)) or symlinks or not all(safe_name(name) for name in names):
            raise RuntimeError("ZIP safety validation failed")
        archive.extractall(VERIFY)
    extracted = json.loads((VERIFY / "MANIFEST.json").read_text(encoding="utf-8"))
    mismatches = []
    for item in extracted["files"]:
        file = VERIFY / Path(*PurePosixPath(item["path"]).parts)
        if not file.is_file() or file.stat().st_size != item["size"] or digest(file) != item["sha256"]:
            mismatches.append(item["path"])
    if mismatches:
        raise RuntimeError(f"extracted manifest mismatch: {mismatches}")
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ARCHIVE, RELEASE)
    shutil.copyfile(ARCHIVE, UPLOAD)
    archive_hash = digest(ARCHIVE)
    if digest(RELEASE) != archive_hash or digest(UPLOAD) != archive_hash:
        raise RuntimeError("delivery copies are not byte-identical")
    readback = {
        "status": "PASS",
        "handoff_status": "ESCALATION_REQUIRED",
        "archive": str(ARCHIVE), "release": str(RELEASE), "upload": str(UPLOAD),
        "sha256": archive_hash,
        "manifest_sha256": digest(STAGING / "MANIFEST.json"),
        "payload_count": len(payloads), "entry_count": len(names),
        "crc": "PASS", "safe_extract": "PASS", "mismatch": 0,
        "duplicates": 0, "case_collisions": 0, "symlinks": 0,
        "byte_identical_copies": True,
    }
    (REVIEW / "FINAL_READBACK.json").write_text(json.dumps(readback, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(readback, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"PACKAGE_ERROR: {error}", file=sys.stderr)
        raise

