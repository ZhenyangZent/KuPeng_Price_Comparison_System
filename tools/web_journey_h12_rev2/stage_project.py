from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV2"
RUNTIME = H12 / "runtime"
PROJECT = RUNTIME / "project"
RELEASES = ROOT / "review" / "releases"
A16 = RELEASES / "CDH_A_R12_004_REVIEW.zip"
PREFIX = "CDH_A_R12_004_REVIEW/"
EXPECTED_A16 = "8eba2b5059c92fcd71897ee345527c78741ebe6c3230c45eab87dd4921b339e4"
PINNED = {
    "CDH_A_R08_001_REVIEW.zip": "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
    "CDH_B_R11_002_REVIEW.zip": "48ec4cefbe5d4840fbe5201d602e552eb53d03a8f7d60b503b1cf4a6503cb0fe",
    "CDH_B_R12_003_REVIEW.zip": "f03b2463b3f6fc2d933fa8a75f78b9ae6da43b04125ee427e422fae0b04cf0d7",
}
B16_EXAMPLE_PREFIX = "CDH_B_R12_003_REVIEW/services/private_batch_import_b16/examples/"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(name: str) -> PurePosixPath:
    if not name.startswith(PREFIX):
        raise RuntimeError(f"member outside expected root: {name}")
    relative = PurePosixPath(name[len(PREFIX):])
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise RuntimeError(f"unsafe archive member: {name}")
    return relative


def extract_b16_examples(archive_path: Path, destination: Path) -> int:
    count = 0
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("B16 example archive CRC failure")
        for info in archive.infolist():
            if info.is_dir() or not info.filename.startswith(B16_EXAMPLE_PREFIX):
                continue
            relative = PurePosixPath(info.filename[len(B16_EXAMPLE_PREFIX):])
            if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
                raise RuntimeError(f"unsafe B16 example path: {info.filename}")
            target = destination / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            count += 1
    return count


def main() -> None:
    if PROJECT.exists():
        raise RuntimeError("H12 isolated project already exists")
    if sha256(A16) != EXPECTED_A16:
        raise RuntimeError("A16 SHA-256 mismatch")
    with zipfile.ZipFile(A16) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("A16 CRC failure")
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("A16 duplicate or case-colliding names")
        for info in infos:
            safe_relative(info.filename)
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                raise RuntimeError(f"A16 symlink member: {info.filename}")
        manifest_name = PREFIX + "SHA256_MANIFEST.json"
        manifest_bytes = archive.read(manifest_name)
        manifest = json.loads(manifest_bytes)
        payloads = manifest.get("payloads", manifest.get("files", []))
        declared = set()
        mismatches = []
        for item in payloads:
            path = item.get("path") or item.get("name")
            full = PREFIX + path
            declared.add(full)
            try:
                data = archive.read(full)
            except KeyError:
                mismatches.append(path)
                continue
            expected_size = item.get("bytes", item.get("size"))
            expected_hash = item.get("sha256")
            if (expected_size is not None and len(data) != expected_size) or sha256_bytes(data) != expected_hash:
                mismatches.append(path)
        undeclared = set(names) - declared - {manifest_name}
        missing = declared - set(names)
        if mismatches or undeclared or missing:
            raise RuntimeError(f"A16 manifest failure mismatch={mismatches} undeclared={sorted(undeclared)} missing={sorted(missing)}")
        PROJECT.mkdir(parents=True)
        extracted = 0
        for info in infos:
            relative = safe_relative(info.filename)
            if info.is_dir() or not relative.parts or relative.parts[0] == "dependencies":
                continue
            target = PROJECT / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            extracted += 1
    release_root = PROJECT / "review" / "releases"
    release_root.mkdir(parents=True)
    pinned_result = {}
    for filename, expected in PINNED.items():
        source = RELEASES / filename
        actual = sha256(source)
        if actual != expected:
            raise RuntimeError(f"pinned release mismatch: {filename}")
        shutil.copyfile(source, release_root / filename)
        pinned_result[filename] = actual
    example_count = extract_b16_examples(
        RELEASES / "CDH_B_R12_003_REVIEW.zip",
        RUNTIME / "examples",
    )
    required = [
        "Start-CDH-MVP.cmd", "Status-CDH-MVP.cmd", "Stop-CDH-MVP.cmd",
        "docs/user-guides/WINDOWS_LOCAL_MVP_FIRST_USE.md",
        "scripts/windows-mvp/Start-CDH-MVP.ps1",
        "scripts/windows-mvp/Status-CDH-MVP.ps1",
        "scripts/windows-mvp/Stop-CDH-MVP.ps1",
    ]
    missing_required = [name for name in required if not (PROJECT / Path(*PurePosixPath(name).parts)).is_file()]
    h_loader_count = sum(1 for item in PROJECT.rglob("*") if item.is_file() and item.name in {"preview_server_h11.py", "preview_server_h12.py", "preview_server_a15.py"})
    input_result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "status": "PASS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "a16": {
            "filename": A16.name,
            "sha256": sha256(A16),
            "bytes": A16.stat().st_size,
            "entries": len(names),
            "manifest_payloads": len(payloads),
            "manifest_sha256": sha256_bytes(manifest_bytes),
            "crc": "PASS",
            "mismatch": len(mismatches),
            "undeclared": len(undeclared),
            "missing": len(missing),
            "duplicates": len(names) - len(set(names)),
            "case_collisions": len(names) - len({name.casefold() for name in names}),
        },
        "pinned_releases": pinned_result,
    }
    stage_result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "status": "PASS" if not missing_required and h_loader_count == 0 else "FAIL",
        "project_root": PROJECT.relative_to(ROOT).as_posix(),
        "a16_extracted_file_count": extracted,
        "nested_dependency_zip_execution_count": 0,
        "required_entry_missing": missing_required,
        "h_test_loader_file_count": h_loader_count,
        "pinned_release_count": len(pinned_result),
        "b16_example_file_count": example_count,
    }
    (H12 / "INPUT_READBACK.json").write_text(json.dumps(input_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (H12 / "STAGED_PROJECT.json").write_text(json.dumps(stage_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"input": input_result, "stage": stage_result}, ensure_ascii=False))
    raise SystemExit(0 if stage_result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()

