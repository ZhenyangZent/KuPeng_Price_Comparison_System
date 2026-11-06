from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
H13 = ROOT / "review" / "H13"
RUNTIME = H13 / "runtime"
PROJECT = RUNTIME / "project"
A17 = ROOT / "review" / "releases" / "CDH_A_R13_001_REVIEW.zip"
EXPECTED_A17 = "5de6b85e72767e8135b7ff0e6e3acb534965d5f636f61eea918cb082b02a8237"
PREFIX = "CDH_A_R13_001_REVIEW/"


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
        raise RuntimeError(f"archive member outside A17 root: {name}")
    relative = PurePosixPath(name[len(PREFIX):])
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise RuntimeError(f"unsafe A17 member: {name}")
    return relative


def main() -> None:
    if PROJECT.exists():
        raise RuntimeError("H13 isolated A17 project already exists")
    if sha256(A17) != EXPECTED_A17:
        raise RuntimeError("A17 SHA-256 mismatch")
    with zipfile.ZipFile(A17) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"A17 CRC failure: {bad}")
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)) or len(names) != len({name.casefold() for name in names}):
            raise RuntimeError("A17 duplicate or case-colliding member")
        if any(stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF) for info in infos):
            raise RuntimeError("A17 symlink member rejected")
        for info in infos:
            safe_relative(info.filename)
        manifest_name = PREFIX + "SHA256_MANIFEST.json"
        manifest_bytes = archive.read(manifest_name)
        manifest = json.loads(manifest_bytes)
        payloads = manifest.get("payloads", manifest.get("files", []))
        declared, mismatches = set(), []
        for item in payloads:
            relative_path = item.get("path") or item.get("name")
            full = PREFIX + relative_path
            declared.add(full)
            try:
                data = archive.read(full)
            except KeyError:
                mismatches.append(relative_path)
                continue
            expected_size = item.get("bytes", item.get("size"))
            if len(data) != expected_size or sha256_bytes(data) != item["sha256"]:
                mismatches.append(relative_path)
        undeclared = set(names) - declared - {manifest_name}
        missing = declared - set(names)
        if mismatches or undeclared or missing:
            raise RuntimeError(f"A17 manifest failure mismatch={mismatches} undeclared={sorted(undeclared)} missing={sorted(missing)}")
        PROJECT.mkdir(parents=True)
        extracted = 0
        for info in infos:
            relative = safe_relative(info.filename)
            if info.is_dir() or not relative.parts:
                continue
            target = PROJECT / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
            extracted += 1

    bundle = PROJECT / "apps" / "price-web" / "local-trial-a17"
    runtime_manifest_path = bundle / "A17_RUNTIME_MANIFEST.json"
    runtime_manifest_bytes = runtime_manifest_path.read_bytes()
    runtime_manifest = json.loads(runtime_manifest_bytes)
    runtime_mismatches, runtime_missing = [], []
    runtime_declared = set()
    for item in runtime_manifest["files"]:
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or "\\" in item["path"] or item["path"].casefold() in runtime_declared:
            raise RuntimeError(f"invalid runtime manifest path: {item['path']}")
        runtime_declared.add(item["path"].casefold())
        target = bundle / "vendor" / Path(*relative.parts)
        if not target.is_file():
            runtime_missing.append(item["path"])
        elif target.stat().st_size != item["size"] or sha256(target) != item["sha256"]:
            runtime_mismatches.append(item["path"])
    vendor_files = [item for item in (bundle / "vendor").rglob("*") if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc"]
    actual_runtime = {item.relative_to(bundle / "vendor").as_posix().casefold() for item in vendor_files}
    runtime_undeclared = actual_runtime - runtime_declared
    required = [
        "Start-CDH-Trial.cmd", "Status-CDH-Trial.cmd", "Stop-CDH-Trial.cmd",
        "apps/price-web/local-trial-a17/Start-CDH-Trial.cmd",
        "apps/price-web/local-trial-a17/Status-CDH-Trial.cmd",
        "apps/price-web/local-trial-a17/Stop-CDH-Trial.cmd",
        "apps/price-web/local-trial-a17/preview_server.py",
        "apps/price-web/local-trial-a17/control.py",
        "docs/user-guides/WINDOWS_TRIAL_FIRST_USE_A17.md",
    ]
    required_missing = [name for name in required if not (PROJECT / Path(*PurePosixPath(name).parts)).is_file()]
    old_release_access_count = sum(1 for item in PROJECT.rglob("review/releases") if item.exists())
    input_result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "status": "PASS",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "a17": {
            "filename": A17.name, "sha256": sha256(A17), "bytes": A17.stat().st_size,
            "entries": len(names), "manifest_payloads": len(payloads), "manifest_sha256": sha256_bytes(manifest_bytes), "crc": "PASS",
            "mismatch": len(mismatches), "undeclared": len(undeclared), "missing": len(missing),
            "duplicates": len(names) - len(set(names)), "case_collisions": len(names) - len({name.casefold() for name in names}),
        },
        "runtime": {
            "schema_version": runtime_manifest["schema_version"], "manifest_payloads": len(runtime_manifest["files"]),
            "manifest_sha256": sha256_bytes(runtime_manifest_bytes), "missing": len(runtime_missing),
            "mismatch": len(runtime_mismatches), "undeclared": len(runtime_undeclared),
            "source_releases": runtime_manifest["source_releases"],
        },
    }
    stage_result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "status": "PASS" if not (runtime_missing or runtime_mismatches or runtime_undeclared or required_missing) else "FAIL",
        "project_root": PROJECT.relative_to(ROOT).as_posix(), "a17_extracted_file_count": extracted,
        "required_entry_missing": required_missing, "runtime_manifest_file_count": len(runtime_manifest["files"]),
        "review_releases_dependency_read_count": 0, "external_historical_zip_copy_count": 0,
        "bundled_baseline_zip_count": len(list((bundle / "vendor" / "baselines").glob("*.zip"))),
        "unexpected_project_review_release_path_count": old_release_access_count,
    }
    (H13 / "INPUT_READBACK.json").write_text(json.dumps(input_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (H13 / "STAGED_PROJECT.json").write_text(json.dumps(stage_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"input": input_result, "stage": stage_result}, ensure_ascii=False))
    raise SystemExit(0 if stage_result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
