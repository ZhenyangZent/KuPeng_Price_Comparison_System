from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[4]
NAME = "CDH_A_R13_001_REVIEW"
STAGE_PARENT = PROJECT / "review" / "A17" / "R13"
STAGE = STAGE_PARENT / NAME
RELEASE = PROJECT / "review" / "releases" / f"{NAME}.zip"
UPLOAD = PROJECT / "review" / "00_TO_UPLOAD" / f"{NAME}.zip"
VERIFIED = STAGE_PARENT / f"{NAME}_verified_extract"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    for item in source.rglob("*"):
        if not item.is_file() or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        copy_file(item, destination / item.relative_to(source))


def safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(path.parts) and not path.is_absolute() and not any(part in {"", ".", ".."} for part in path.parts)


def verify_manifest(root: Path) -> dict[str, int]:
    manifest = json.loads((root / "SHA256_MANIFEST.json").read_text(encoding="utf-8"))
    expected = {entry["path"]: (entry["size"], entry["sha256"]) for entry in manifest["files"]}
    actual = {
        item.relative_to(root).as_posix(): (item.stat().st_size, sha256(item))
        for item in root.rglob("*")
        if item.is_file() and item.name != "SHA256_MANIFEST.json"
    }
    missing = len(set(expected) - set(actual))
    undeclared = len(set(actual) - set(expected))
    mismatch = sum(1 for path in set(expected) & set(actual) if expected[path] != actual[path])
    return {"payloads": len(actual), "missing": missing, "undeclared": undeclared, "mismatch": mismatch}


def main() -> int:
    for path in (STAGE, RELEASE, UPLOAD, VERIFIED):
        if path.exists():
            raise RuntimeError(f"DELIVERY_TARGET_EXISTS: {path}")
    STAGE.mkdir(parents=True)
    copy_file(PROJECT / "reports" / "A17" / "DELIVERY_README.md", STAGE / "README.md")
    for name in ("Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd"):
        copy_file(PROJECT / name, STAGE / name)
    copy_file(
        PROJECT / "docs" / "user-guides" / "WINDOWS_TRIAL_FIRST_USE_A17.md",
        STAGE / "docs" / "user-guides" / "WINDOWS_TRIAL_FIRST_USE_A17.md",
    )
    copy_tree(
        PROJECT / "apps" / "price-web" / "local-trial-a17",
        STAGE / "apps" / "price-web" / "local-trial-a17",
    )
    report_source = PROJECT / "reports" / "A17"
    for item in report_source.rglob("*"):
        if not item.is_file() or "runtime" in item.relative_to(report_source).parts:
            continue
        copy_file(item, STAGE / "reports" / "A17" / item.relative_to(report_source))
    forbidden = {".env", "cookies.sqlite", "logins.json", "key4.db", "private_user_observations.sqlite3"}
    violations = [item.relative_to(STAGE).as_posix() for item in STAGE.rglob("*") if item.is_file() and item.name.lower() in forbidden]
    if violations:
        raise RuntimeError(f"FORBIDDEN_DELIVERY_FILE: {violations}")
    files = [
        {"path": item.relative_to(STAGE).as_posix(), "size": item.stat().st_size, "sha256": sha256(item)}
        for item in sorted(STAGE.rglob("*"))
        if item.is_file()
    ]
    manifest = {"schema_version": "CDH-A17-REVIEW-MANIFEST-1", "task_id": "CDH-A17-WINDOWS-LOCAL-TRIAL-001", "files": files}
    manifest_path = STAGE / "SHA256_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = sha256(manifest_path)
    RELEASE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(RELEASE, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for item in sorted(STAGE.rglob("*")):
            if item.is_file():
                archive.write(item, f"{NAME}/{item.relative_to(STAGE).as_posix()}")
    with zipfile.ZipFile(RELEASE) as archive:
        bad_crc = archive.testzip()
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        if bad_crc is not None:
            raise RuntimeError(f"ZIP_CRC_FAILURE: {bad_crc}")
        if len(names) != len(set(names)) or any(not safe_member(name) for name in names):
            raise RuntimeError("ZIP_MEMBER_SAFETY_FAILURE")
        VERIFIED.mkdir(parents=True)
        archive.extractall(VERIFIED)
    extracted = VERIFIED / NAME
    integrity = verify_manifest(extracted)
    if any(integrity[key] for key in ("missing", "undeclared", "mismatch")):
        raise RuntimeError(f"EXTRACTED_MANIFEST_FAILURE: {integrity}")
    for name in ("Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd"):
        data = (extracted / name).read_bytes()
        if b"\n" in data.replace(b"\r\n", b""):
            raise RuntimeError(f"CMD_NOT_CRLF: {name}")
    release_sha = sha256(RELEASE)
    UPLOAD.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(RELEASE, UPLOAD)
    if sha256(UPLOAD) != release_sha:
        raise RuntimeError("UPLOAD_COPY_MISMATCH")
    result = {
        "schema_version": "CDH-A17-PACKAGE-RESULT-1",
        "status": "PASS",
        "task_id": "CDH-A17-WINDOWS-LOCAL-TRIAL-001",
        "release": str(RELEASE),
        "upload_copy": str(UPLOAD),
        "size": RELEASE.stat().st_size,
        "sha256": release_sha,
        "manifest_sha256": manifest_sha,
        "crc": "PASS",
        "safe_extraction": "PASS",
        "upload_copy_identical": True,
        **integrity,
        "duplicates": 0,
    }
    result_path = PROJECT / "reports" / "A17" / "evidence" / "PACKAGE_RESULT.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
