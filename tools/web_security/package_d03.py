from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


RELEASE_NAME = "CDH_D03_WEB_001_REVIEW"
IGNORED = {"__pycache__", ".pytest_cache"}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and "\\" not in name and not normalized.startswith("/") and not path.is_absolute() and ".." not in path.parts and not (len(normalized) > 1 and normalized[1] == ":")


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=lambda _d, names: [name for name in names if name in IGNORED or name.endswith((".pyc", ".pyo"))])


def extract_input(bundle: Path, destination: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if any(not safe_name(name) for name in names) or len(names) != len({name.casefold() for name in names}):
            raise ValueError("INPUT_PATH_SAFETY_FAILURE")
        if archive.testzip() is not None:
            raise ValueError("INPUT_CRC_FAILURE")
        raw_manifest = archive.read("MANIFEST.json")
        manifest = json.loads(raw_manifest)
        mismatches = []
        for record in manifest["payloads"]:
            raw = archive.read(record["path"])
            if len(raw) != record["bytes"] or sha256_bytes(raw) != record["sha256"]:
                mismatches.append(record["path"])
        declared = {record["path"] for record in manifest["payloads"]} | {"MANIFEST.json"}
        if mismatches or declared != set(names):
            raise ValueError(f"INPUT_MANIFEST_FAILURE:{mismatches}:{sorted(set(names)-declared)}")
        destination.mkdir(parents=True)
        for name in names:
            target = destination / PurePosixPath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return {"zip_sha256": sha256_file(bundle), "manifest_sha256": sha256_bytes(raw_manifest), "entries": len(names), "payloads": len(manifest["payloads"]), "crc_pass": True}


def run_tests(stage: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stage)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security", "-p", "test_*.py", "-v"]
    result = subprocess.run(command, cwd=stage, env=env, text=True, capture_output=True, check=False)
    evidence = stage / "evidence" / "STAGED_TEST_RESULTS.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}", encoding="utf-8")
    if result.returncode:
        raise RuntimeError("STAGED_TEST_FAILURE")
    return {"exit_code": 0, "evidence": "evidence/STAGED_TEST_RESULTS.txt"}


def collect(stage: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_file() and path not in {stage / "MANIFEST.json", stage / "SHA256SUMS.txt"}:
            records.append({"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def verify_release(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        manifest_raw = archive.read(f"{RELEASE_NAME}/MANIFEST.json")
        manifest = json.loads(manifest_raw)
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = {name.removeprefix(f"{RELEASE_NAME}/") for name in names if not name.endswith("/") and name not in {f"{RELEASE_NAME}/MANIFEST.json", f"{RELEASE_NAME}/SHA256SUMS.txt"}}
        mismatches = []
        for relative, expected in declared.items():
            raw = archive.read(f"{RELEASE_NAME}/{relative}")
            if len(raw) != expected["bytes"] or sha256_bytes(raw) != expected["sha256"]:
                mismatches.append(relative)
        result = {
            "release_sha256": sha256_file(path), "release_bytes": path.stat().st_size,
            "zip_entries": len(names), "crc_pass": archive.testzip() is None,
            "safe_path_pass": all(safe_name(name) for name in names),
            "symlink_count": sum(stat.S_ISLNK(item.external_attr >> 16) for item in infos),
            "casefold_duplicate_count": len(names) - len({name.casefold() for name in names}),
            "manifest_sha256": sha256_bytes(manifest_raw), "manifest_payload_count": len(declared),
            "manifest_mismatch_count": len(mismatches), "manifest_missing_count": len(set(declared)-actual),
            "manifest_undeclared_count": len(actual-set(declared)),
        }
    return result


def build(root: Path, bundle: Path) -> dict[str, Any]:
    work = root / "review" / "D03_WEB" / "001"
    stage = work / "package" / RELEASE_NAME
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review" / "00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security", "tests/web/security", "reports/D03_WEB"):
        copy_tree(root / relative, stage / relative)
    input_result = extract_input(bundle, stage / "input_contract")
    target_releases = stage / "target_inputs" / "review" / "releases"
    target_releases.mkdir(parents=True)
    target_hashes = {}
    for name in ("CDH_A05_001_REVIEW.zip", "CDH_B05_001_REVIEW.zip"):
        source = root / "review" / "releases" / name
        shutil.copyfile(source, target_releases / name)
        target_hashes[name] = sha256_file(source)
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security -p 'test_*.py' -v\n", encoding="utf-8")
    (stage / "README_REVIEW.md").write_text("# CDH D03 Web contract security review\n\nOffline, hash-bound A05/B05 counterexamples plus strict F CTA acceptance. Run `RUN_TESTS.ps1`. No live network, real secret, browser profile, production database, notification, deployment or transaction is included.\n", encoding="utf-8")
    staged_test = run_tests(stage)
    sys.path.insert(0, str(stage))
    prior = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from tools.web_security.audit import audit_tree
        package_audit = audit_tree(stage, allowed_root=stage, owner="D")
    finally:
        sys.dont_write_bytecode = prior
        sys.path.pop(0)
    (stage / "evidence" / "PACKAGE_SECURITY_AUDIT.json").write_text(json.dumps(package_audit.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not package_audit.passed:
        raise RuntimeError("PACKAGE_SECURITY_AUDIT_FAILURE")
    build_info = {"generated_at": datetime.now(timezone.utc).isoformat(), "python": sys.version, "input": input_result, "targets": target_hashes, "staged_test": staged_test, "package_security_audit": package_audit.to_dict(), "live_network_count": 0, "real_env_read_count": 0, "formal_database_access_count": 0}
    (stage / "evidence" / "BUILD_ENVIRONMENT.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = collect(stage)
    manifest = {"schema": "CDH-D03-WEB-REVIEW-MANIFEST-1", "task_id": "CDH-D03-WEB-CONTRACT-SECURITY-001", "release": RELEASE_NAME, "generated_at": datetime.now(timezone.utc).isoformat(), "input_bundle_sha256": input_result["zip_sha256"], "target_release_sha256": target_hashes, "payload_count": len(records), "payloads": records, "restrictions": {"offline_only": True, "real_env_read": False, "target_code_mutated": False, "verified_cta_enabled": False}}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stage / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in records), encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_release(release)
    if not all((verification["crc_pass"], verification["safe_path_pass"], verification["symlink_count"] == 0, verification["casefold_duplicate_count"] == 0, verification["manifest_mismatch_count"] == 0, verification["manifest_missing_count"] == 0, verification["manifest_undeclared_count"] == 0)):
        raise RuntimeError(f"RELEASE_VERIFICATION_FAILURE:{verification}")
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    verification.update({"release": str(release), "queue_copy": str(queue), "queue_sha256": sha256_file(queue), "queue_bytes": queue.stat().st_size, "same_byte_copy": release.read_bytes() == queue.read_bytes()})
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input-bundle", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.input_bundle.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
