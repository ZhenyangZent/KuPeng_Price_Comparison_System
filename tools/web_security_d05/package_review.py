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

from .gate import EXPECTED_TARGETS
from .targets import safe_member_name, sha256_file


RELEASE_NAME = "CDH_D05_WEB_001_REVIEW"
TASK_ID = "CDH-D05-WEB-INTEGRATION-SECURITY-001"
INPUT_SHA256 = "ce7d509b246e7c70a957a395bcfb4c15a7c16717675f3b37868ebd6e9c68e9dc"
INPUT_MANIFEST_SHA256 = "08b6f0199224c7240c6237d5187559797e0578ce1ec517be81d323707b908328"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=lambda _directory, names: [
            name for name in names
            if name in {"__pycache__", ".pytest_cache"} or name.endswith((".pyc", ".pyo"))
        ],
    )


def extract_input(bundle: Path, destination: Path) -> dict[str, Any]:
    if sha256_file(bundle) != INPUT_SHA256:
        raise ValueError("INPUT_ZIP_SHA256_MISMATCH")
    with zipfile.ZipFile(bundle) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if (
            any(not safe_member_name(name) for name in names)
            or len(names) != len({name.casefold() for name in names})
            or any(stat.S_ISLNK(item.external_attr >> 16) for item in infos)
            or archive.testzip() is not None
        ):
            raise ValueError("INPUT_ZIP_SAFETY_FAILURE")
        raw_manifest = archive.read("MANIFEST.json")
        if sha256_bytes(raw_manifest) != INPUT_MANIFEST_SHA256:
            raise ValueError("INPUT_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(raw_manifest)
        records = manifest.get("entries")
        if not isinstance(records, list):
            raise ValueError("INPUT_MANIFEST_FORMAT_FAILURE")
        declared: set[str] = set()
        mismatches: list[str] = []
        for record in records:
            name = record["path"]
            declared.add(name)
            raw = archive.read(name)
            expected_size = record.get("bytes")
            if len(raw) != expected_size or sha256_bytes(raw) != record["sha256"]:
                mismatches.append(name)
        if mismatches or declared | {"MANIFEST.json"} != set(names):
            raise ValueError(f"INPUT_MANIFEST_FAILURE:{mismatches}")
        destination.mkdir(parents=True, exist_ok=False)
        for name in names:
            target = destination / PurePosixPath(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return {
        "zip_sha256": INPUT_SHA256,
        "manifest_sha256": INPUT_MANIFEST_SHA256,
        "entries": len(names),
        "payloads": len(records),
        "crc_pass": True,
        "safe_paths": True,
        "no_symlinks": True,
        "no_casefold_duplicates": True,
    }


def run_command(command: list[str], cwd: Path, evidence: Path, *, expected: set[int]) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(cwd)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, capture_output=True, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
        encoding="utf-8",
    )
    if result.returncode not in expected:
        raise RuntimeError(f"COMMAND_FAILURE:{result.returncode}:{command}")
    return {"exit_code": result.returncode, "evidence": evidence.name}


def audit_stage(stage: Path) -> dict[str, Any]:
    forbidden: list[str] = []
    secret_patterns: list[str] = []
    files = 0
    bytes_total = 0
    signatures = (
        b"AK" + b"IA",
        b"gh" + b"p_",
        b"github" + b"_pat_",
        b"sk-" + b"proj-",
        b"sk-" + b"live-",
        b"AI" + b"za",
    )
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        files += 1
        bytes_total += path.stat().st_size
        relative = path.relative_to(stage).as_posix()
        parts = {part.casefold() for part in PurePosixPath(relative).parts}
        basename = path.name.casefold()
        if (
            parts & {"__pycache__", ".git", ".venv", "node_modules"}
            or basename == ".env"
            or (basename.startswith(".env.") and basename != ".env.example")
            or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".reg"}
        ):
            forbidden.append(relative)
        if path.suffix.casefold() not in {".zip", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif", ".woff", ".woff2"}:
            raw = path.read_bytes()
            for signature in signatures:
                if signature in raw:
                    secret_patterns.append(f"{relative}:{signature.decode('ascii')}")
    return {
        "passed": not forbidden and not secret_patterns,
        "files_scanned": files,
        "bytes_scanned": bytes_total,
        "forbidden_paths": forbidden,
        "secret_pattern_hits": secret_patterns,
    }


def collect(stage: Path) -> list[dict[str, Any]]:
    excluded = {stage / "MANIFEST.json", stage / "SHA256SUMS.txt"}
    return [
        {"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold())
        if path.is_file() and path not in excluded
    ]


def verify_release(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        prefix = f"{RELEASE_NAME}/"
        manifest_raw = archive.read(prefix + "MANIFEST.json")
        sums_raw = archive.read(prefix + "SHA256SUMS.txt").decode("utf-8")
        manifest = json.loads(manifest_raw)
        declared = {item["path"]: item for item in manifest["payloads"]}
        actual = {
            name.removeprefix(prefix)
            for name in names
            if not name.endswith("/") and name not in {prefix + "MANIFEST.json", prefix + "SHA256SUMS.txt"}
        }
        mismatches: list[str] = []
        for relative, expected in declared.items():
            raw = archive.read(prefix + relative)
            if len(raw) != expected["bytes"] or sha256_bytes(raw) != expected["sha256"]:
                mismatches.append(relative)
        expected_sums = "".join(f"{item['sha256']}  {item['path']}\n" for item in manifest["payloads"])
        return {
            "release_sha256": sha256_file(path),
            "release_bytes": path.stat().st_size,
            "zip_entries": len(names),
            "crc_pass": archive.testzip() is None,
            "safe_path_pass": all(safe_member_name(name) for name in names),
            "symlink_count": sum(stat.S_ISLNK(item.external_attr >> 16) for item in infos),
            "casefold_duplicate_count": len(names) - len({name.casefold() for name in names}),
            "manifest_sha256": sha256_bytes(manifest_raw),
            "manifest_payload_count": len(declared),
            "manifest_mismatch_count": len(mismatches),
            "manifest_missing_count": len(set(declared) - actual),
            "manifest_undeclared_count": len(actual - set(declared)),
            "sha256sums_match": sums_raw.splitlines() == expected_sums.splitlines(),
        }


def build(root: Path, bundle: Path) -> dict[str, Any]:
    work = root / "review" / "D05_WEB" / "001"
    stage = work / "package" / RELEASE_NAME
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review" / "00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")

    stage.mkdir(parents=True)
    copy_tree(root / "tools" / "web_security_d05", stage / "tools" / "web_security_d05")
    copy_tree(root / "tests" / "web" / "security_d05", stage / "tests" / "web" / "security_d05")
    copy_tree(root / "reports" / "D05_WEB", stage / "reports" / "D05_WEB")
    input_result = extract_input(bundle, stage / "input_contract")

    target_dir = stage / "target_inputs" / "review" / "releases"
    target_dir.mkdir(parents=True)
    for name, expected in EXPECTED_TARGETS.items():
        source = root / "review" / "releases" / name
        if sha256_file(source) != expected:
            raise ValueError(f"TARGET_IDENTITY_FAILURE:{name}")
        shutil.copyfile(source, target_dir / name)

    (stage / "RUN_TESTS.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d05 -p 'test_*.py' -v\n",
        encoding="utf-8",
    )
    (stage / "RUN_GATE.ps1").write_text(
        "$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m tools.web_security_d05.gate --target-dir target_inputs/review/releases --json-out evidence/GATE_RESULT.json\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    (stage / "README_REVIEW.md").write_text(
        "# CDH D05 Web integration security review\n\nHash-bound offline audit of exact A06/B06/B07/C04/F02 releases. Run `RUN_TESTS.ps1`; run `RUN_GATE.ps1` to reproduce the intentionally blocking P1 acceptance result. This package does not authorize application changes or affiliate activation.\n",
        encoding="utf-8",
    )

    suite = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d05", "-p", "test_*.py", "-v"],
        stage,
        stage / "evidence" / "STAGED_TEST_RESULTS.txt",
        expected={0},
    )
    gate = run_command(
        [sys.executable, "-m", "tools.web_security_d05.gate", "--target-dir", "target_inputs/review/releases", "--json-out", "evidence/GATE_RESULT.json"],
        stage,
        stage / "evidence" / "STAGED_GATE_OUTPUT.txt",
        expected={2},
    )
    gate_result = json.loads((stage / "evidence" / "GATE_RESULT.json").read_text(encoding="utf-8"))
    if gate_result["priority_counts"] != {"P0": 0, "P1": 3, "P2": 2}:
        raise RuntimeError("UNEXPECTED_GATE_FINDINGS")

    stage_audit = audit_stage(stage)
    (stage / "evidence" / "PACKAGE_PATH_AND_SECRET_AUDIT.json").write_text(json.dumps(stage_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not stage_audit["passed"]:
        raise RuntimeError(f"PACKAGE_AUDIT_FAILURE:{stage_audit}")
    build_info = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "input": input_result,
        "targets": EXPECTED_TARGETS,
        "staged_test": suite,
        "staged_gate": gate,
        "stage_audit": stage_audit,
        "full_site_security_acceptance": "BLOCKED",
        "findings": {"P0": 0, "P1": 3, "P2": 2},
        "live_network_count": 0,
        "real_env_read_count": 0,
        "browser_profile_access_count": 0,
        "affiliate_click_count": 0,
        "shopping_action_count": 0,
    }
    (stage / "evidence" / "BUILD_ENVIRONMENT.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    records = collect(stage)
    manifest = {
        "schema": "CDH-D05-WEB-REVIEW-MANIFEST-1",
        "task_id": TASK_ID,
        "release": RELEASE_NAME,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_bundle_sha256": INPUT_SHA256,
        "input_manifest_sha256": INPUT_MANIFEST_SHA256,
        "target_release_sha256": EXPECTED_TARGETS,
        "payload_count": len(records),
        "payloads": records,
        "findings": {"P0": 0, "P1": 3, "P2": 2},
        "restrictions": {
            "offline_only": True,
            "real_env_read": False,
            "target_code_mutated": False,
            "affiliate_click_count": 0,
            "full_website_pass_claimed": False,
        },
    }
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stage / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in records), encoding="utf-8")

    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_release(release)
    required = (
        verification["crc_pass"],
        verification["safe_path_pass"],
        verification["symlink_count"] == 0,
        verification["casefold_duplicate_count"] == 0,
        verification["manifest_mismatch_count"] == 0,
        verification["manifest_missing_count"] == 0,
        verification["manifest_undeclared_count"] == 0,
        verification["sha256sums_match"],
    )
    if not all(required):
        raise RuntimeError(f"RELEASE_VERIFICATION_FAILURE:{verification}")

    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    verification.update({
        "release": str(release),
        "queue_copy": str(queue),
        "queue_sha256": sha256_file(queue),
        "queue_bytes": queue.stat().st_size,
        "same_byte_copy": release.read_bytes() == queue.read_bytes(),
    })
    if not verification["same_byte_copy"] or verification["queue_sha256"] != verification["release_sha256"]:
        raise RuntimeError("QUEUE_COPY_IDENTITY_FAILURE")

    post_extract = work / f"post_extract_{verification['release_sha256'][:8]}"
    if post_extract.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{post_extract}")
    with zipfile.ZipFile(release) as archive:
        archive.extractall(post_extract)
    extracted = post_extract / RELEASE_NAME
    post_suite = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d05", "-p", "test_*.py", "-v"],
        extracted,
        work / "POST_EXTRACT_TEST_RESULTS.txt",
        expected={0},
    )
    post_gate = run_command(
        [sys.executable, "-m", "tools.web_security_d05.gate", "--target-dir", "target_inputs/review/releases"],
        extracted,
        work / "POST_EXTRACT_GATE_OUTPUT.txt",
        expected={2},
    )
    verification["post_extract_test"] = post_suite
    verification["post_extract_gate"] = post_gate
    verification["post_extract_status"] = "PASS_EXPECTED_BLOCKING_FINDINGS_REPRODUCED"
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return verification


def main() -> int:
    parser = argparse.ArgumentParser(description="Build immutable D05 review release")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input-bundle", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.root.resolve(), args.input_bundle.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
