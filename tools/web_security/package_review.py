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


RELEASE_NAME = "CDH_D02_WEB_001_REVIEW"
RELEVANT_INPUTS = (
    "00_START_HERE.md",
    "01_SHARED_RULES.md",
    "02_PROJECT_STATUS.md",
    "03_SHARED_WEB_CONTRACT_V1.md",
    "04_RELEASE_WORKFLOW.md",
    "ASSIGNMENTS.json",
    "ROLES/D.md",
    "MANIFEST_SHA256.json",
)
IGNORED_NAMES = {"__pycache__", ".pytest_cache"}


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
    return (
        bool(normalized)
        and "\\" not in name
        and not normalized.startswith("/")
        and not path.is_absolute()
        and ".." not in path.parts
        and not (len(normalized) > 1 and normalized[1] == ":")
    )


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=lambda _directory, names: [
            name
            for name in names
            if name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))
        ],
    )


def extract_and_validate_input(bundle: Path, destination: Path) -> dict[str, Any]:
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if any(not safe_name(name) for name in names):
            raise ValueError("INPUT_UNSAFE_PATH")
        lowered = [name.casefold() for name in names]
        if len(lowered) != len(set(lowered)):
            raise ValueError("INPUT_DUPLICATE_PATH")
        if archive.testzip() is not None:
            raise ValueError("INPUT_CRC_FAILURE")
        manifest = json.loads(archive.read("MANIFEST_SHA256.json"))
        mismatch = []
        for name, expected in manifest.items():
            raw = archive.read(name)
            if len(raw) != expected["size"] or sha256_bytes(raw) != expected["sha256"]:
                mismatch.append(name)
        if mismatch:
            raise ValueError(f"INPUT_MANIFEST_MISMATCH:{mismatch}")
        destination.mkdir(parents=True)
        for name in RELEVANT_INPUTS:
            target = destination / PurePosixPath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return {
        "zip_sha256": sha256_file(bundle),
        "zip_entries": len(names),
        "manifest_declared": len(manifest),
        "manifest_mismatches": 0,
        "crc": "PASS",
        "safe_paths": "PASS",
    }


def run_tests(stage: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(stage)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests/web/security",
        "-p",
        "test_*.py",
        "-v",
    ]
    result = subprocess.run(command, cwd=stage, env=env, text=True, capture_output=True, check=False)
    evidence = stage / "evidence" / "STAGED_TEST_RESULTS.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "COMMAND: " + " ".join(command) + "\n"
        + f"EXIT_CODE: {result.returncode}\n\nSTDOUT\n"
        + result.stdout
        + "\nSTDERR\n"
        + result.stderr,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"STAGED_TEST_FAILURE:{evidence}")
    return {"exit_code": 0, "evidence": "evidence/STAGED_TEST_RESULTS.txt"}


def clean_runtime_caches(stage: Path) -> int:
    removed = 0
    resolved_stage = stage.resolve(strict=True)
    for cache in sorted(stage.rglob("__pycache__"), key=lambda value: len(value.parts), reverse=True):
        resolved = cache.resolve(strict=True)
        if resolved_stage not in resolved.parents:
            raise RuntimeError("CACHE_PATH_ESCAPED_STAGE")
        shutil.rmtree(resolved)
        removed += 1
    for compiled in stage.rglob("*.py[co]"):
        resolved = compiled.resolve(strict=True)
        if resolved_stage not in resolved.parents:
            raise RuntimeError("COMPILED_PATH_ESCAPED_STAGE")
        resolved.unlink()
        removed += 1
    return removed


def package_security_audit(stage: Path) -> dict[str, Any]:
    sys.path.insert(0, str(stage))
    prior_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        from tools.web_security.audit import audit_tree

        result = audit_tree(stage, allowed_root=stage, owner="A")
    finally:
        sys.dont_write_bytecode = prior_dont_write
        sys.path.pop(0)
    payload = result.to_dict()
    (stage / "evidence" / "PACKAGE_SECURITY_AUDIT.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if not result.passed:
        raise RuntimeError("PACKAGE_SECURITY_AUDIT_FAILED")
    return payload


def collect_payloads(stage: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()):
        if not path.is_file() or path.name in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        relative = path.relative_to(stage).as_posix()
        records.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return records


def verify_release(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        unsafe = [name for name in names if not safe_name(name)]
        duplicate_count = len(names) - len({name.casefold() for name in names})
        symlinks = [item.filename for item in members if stat.S_ISLNK(item.external_attr >> 16)]
        bad_crc = archive.testzip()
        manifest = json.loads(archive.read(f"{RELEASE_NAME}/MANIFEST.json"))
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = {
            name.removeprefix(f"{RELEASE_NAME}/")
            for name in names
            if not name.endswith("/")
            and name not in {f"{RELEASE_NAME}/MANIFEST.json", f"{RELEASE_NAME}/SHA256SUMS.txt"}
        }
        mismatches = []
        for relative, expected in declared.items():
            raw = archive.read(f"{RELEASE_NAME}/{relative}")
            if len(raw) != expected["bytes"] or sha256_bytes(raw) != expected["sha256"]:
                mismatches.append(relative)
        missing = sorted(set(declared) - actual)
        undeclared = sorted(actual - set(declared))
    return {
        "release_sha256": sha256_file(path),
        "release_bytes": path.stat().st_size,
        "zip_entries": len(names),
        "crc_pass": bad_crc is None,
        "safe_path_pass": not unsafe,
        "symlink_count": len(symlinks),
        "casefold_duplicate_count": duplicate_count,
        "manifest_payload_count": len(declared),
        "manifest_mismatch_count": len(mismatches),
        "manifest_missing_count": len(missing),
        "manifest_undeclared_count": len(undeclared),
        "mismatches": mismatches,
        "missing": missing,
        "undeclared": undeclared,
    }


def build(root: Path, bundle: Path) -> dict[str, Any]:
    stage = root / "review" / "D02" / "WEB_001" / "package" / RELEASE_NAME
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review" / "00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    verification_path = root / "review" / "D02" / "WEB_001" / "RELEASE_VERIFICATION.json"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security", "tests/web/security", "reports/D02/WEB_001"):
        copy_tree(root / relative, stage / relative)
    input_result = extract_and_validate_input(bundle, stage / "input_contract")
    (stage / "RUN_TESTS.ps1").write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "$env:PYTHONPATH = (Resolve-Path '.').Path\n"
        "python -m unittest discover -s tests/web/security -p 'test_*.py' -v\n",
        encoding="utf-8",
    )
    (stage / "README_REVIEW.md").write_text(
        "# CDH D02 Web security review\n\n"
        "Independent offline adversarial harness. Run `RUN_TESTS.ps1`. No live network, real secret, browser profile, Registry, formal database mutation, notification, deployment or transaction is included.\n",
        encoding="utf-8",
    )
    staged_test = run_tests(stage)
    removed_runtime_caches = clean_runtime_caches(stage)
    security_audit = package_security_audit(stage)
    environment = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": sys.platform,
        "input": input_result,
        "staged_test": staged_test,
        "removed_runtime_cache_entries": removed_runtime_caches,
        "package_security_audit": {
            "passed": security_audit["passed"],
            "files_scanned": security_audit["files_scanned"],
            "findings": len(security_audit["findings"]),
        },
        "live_network_count": 0,
        "real_secret_read_count": 0,
        "formal_database_access_count": 0,
    }
    (stage / "evidence" / "BUILD_ENVIRONMENT.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    records = collect_payloads(stage)
    manifest = {
        "contract": "CDH-D02-WEB-REVIEW-MANIFEST-1",
        "release": RELEASE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_bundle_sha256": input_result["zip_sha256"],
        "payload_count": len(records),
        "payloads": records,
        "restrictions": {
            "offline_only": True,
            "live_network": False,
            "real_secret_read": False,
            "target_implementation_pass_claimed": False,
        },
    }
    (stage / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (stage / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in records), encoding="utf-8"
    )
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_release(release)
    if not (
        verification["crc_pass"]
        and verification["safe_path_pass"]
        and verification["symlink_count"] == 0
        and verification["casefold_duplicate_count"] == 0
        and verification["manifest_mismatch_count"] == 0
        and verification["manifest_missing_count"] == 0
        and verification["manifest_undeclared_count"] == 0
    ):
        raise RuntimeError(f"RELEASE_VERIFICATION_FAILED:{verification}")
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    verification.update(
        {
            "release": str(release),
            "queue_copy": str(queue),
            "queue_sha256": sha256_file(queue),
            "queue_bytes": queue.stat().st_size,
            "same_byte_copy": release.read_bytes() == queue.read_bytes(),
        }
    )
    if not verification["same_byte_copy"] or verification["queue_sha256"] != verification["release_sha256"]:
        raise RuntimeError("QUEUE_COPY_IDENTITY_FAILED")
    verification_path.write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return verification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input-bundle", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.root.resolve(), args.input_bundle.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
