from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from tools.web_security_d12_rev2.archive import B15_FILENAME, B15_SHA256, sha256_file, verify_b15

RELEASE_NAME = "CDH_D_R11_002_REVIEW"
TASK_ID = "CDH-D12-B15-WRITE-BOUNDARY-SECURITY"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_name(name: str) -> str:
    value = name.replace("\\", "/").rstrip("/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_ARCHIVE_MEMBER:{name}")
    return pure.as_posix()


def inspect_zip(path: Path) -> list[tuple[str, zipfile.ZipInfo]]:
    result: list[tuple[str, zipfile.ZipInfo]] = []
    folded: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"CRC_FAILURE:{path.name}:{bad}")
        for info in archive.infolist():
            name = safe_name(info.filename)
            if name.casefold() in folded:
                raise ValueError(f"CASEFOLD_DUPLICATE:{name}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"SYMLINK_REFUSED:{name}")
            folded.add(name.casefold())
            result.append((name, info))
    return result


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=lambda _directory, names: [name for name in names if name in {"__pycache__", ".pytest_cache", "tmp_tests"} or name.endswith((".pyc", ".pyo"))])


def run_suite(stage: Path, evidence: Path) -> dict[str, object]:
    environment = {**os.environ, "PYTHONPATH": str(stage), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d12_rev2", "-t", ".", "-v"]
    process = subprocess.run(command, cwd=stage, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"SUITE_FAILED:{process.returncode}")
    combined = process.stdout + process.stderr
    marker = combined.split("Ran ", 1)[1].split(" ", 1)[0]
    return {"exit_code": 0, "tests_run": int(marker), "log_sha256": sha256_file(evidence)}


def audit(stage: Path) -> dict[str, object]:
    forbidden: list[str] = []
    secret_hits: list[str] = []
    absolute_paths: list[str] = []
    patterns = (re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"ghp_[A-Za-z0-9]{30,}"), re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"), re.compile(rb"sk-(?:proj|live)-[A-Za-z0-9_-]{20,}"))
    count = 0
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        count += 1
        relative = path.relative_to(stage).as_posix()
        name = path.name.casefold()
        parts = {part.casefold() for part in PurePosixPath(relative).parts}
        if parts & {"__pycache__", ".git", ".venv", "node_modules"} or name == ".env" or (name.startswith(".env.") and name != ".env.example") or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".reg"}:
            forbidden.append(relative)
        if path.suffix.casefold() not in {".zip", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif"}:
            raw = path.read_bytes()
            secret_hits.extend(f"{relative}:{pattern.pattern.decode('ascii')}" for pattern in patterns if pattern.search(raw))
            if re.search(rb"[A-Za-z]:\\Users\\[^\\\r\n\"]+", raw):
                absolute_paths.append(relative)
    return {"passed": not forbidden and not secret_hits and not absolute_paths, "files_scanned": count, "forbidden_paths": forbidden, "secret_pattern_hits": secret_hits, "absolute_user_path_hits": absolute_paths}


def collect(stage: Path) -> list[dict[str, object]]:
    manifest = stage / "MANIFEST.json"
    return [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()) if path.is_file() and path != manifest]


def verify_delivery(path: Path) -> dict[str, object]:
    entries = inspect_zip(path)
    prefix = RELEASE_NAME + "/"
    with zipfile.ZipFile(path) as archive:
        members = {name: info for name, info in entries}
        manifest_name = prefix + "MANIFEST.json"
        raw_manifest = archive.read(members[manifest_name])
        manifest = json.loads(raw_manifest)
        declared: set[str] = set()
        for record in manifest["payloads"]:
            name = prefix + safe_name(record["path"])
            value = archive.read(members[name])
            declared.add(name)
            if len(value) != record["bytes"] or digest(value) != record["sha256"]:
                raise ValueError(f"DELIVERY_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("DELIVERY_COVERAGE_FAILURE")
    return {"status": "PASS", "zip_sha256": sha256_file(path), "manifest_sha256": digest(raw_manifest), "entries": len(entries), "payloads": len(manifest["payloads"]), "crc_pass": True, "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0}


def build(root: Path) -> dict[str, object]:
    work = root / "review/D12/002"
    stage = work / "package" / RELEASE_NAME
    release = root / "review/releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review/00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    copy_tree(root / "tools/web_security_d12_rev2", stage / "tools/web_security_d12_rev2")
    copy_tree(root / "tests/web/security_d12_rev2", stage / "tests/web/security_d12_rev2")
    copy_tree(root / "reports/D12_REV2", stage / "reports/D12_REV2")
    evidence = stage / "review/D12/002/evidence"
    evidence.mkdir(parents=True)
    for name in ("WINDOWS_JUNCTION_PROBE.json", "ACTUAL_HTTP_PROBE.json", "B15_REV2_UPSTREAM_TESTS.txt", "D12_REV2_TESTS.txt"):
        shutil.copyfile(work / "evidence" / name, evidence / name)
    extracted = root / "review/D12/002/input/CDH_B_R11_002_REVIEW"
    copy_tree(extracted / "services", stage / "review/D12/002/input/CDH_B_R11_002_REVIEW/services")
    copy_tree(extracted / "tests", stage / "review/D12/002/input/CDH_B_R11_002_REVIEW/tests")
    exact_zip = root / "review/releases" / B15_FILENAME
    input_verification = verify_b15(exact_zip)
    target_directory = stage / "review/releases"
    target_directory.mkdir(parents=True)
    shutil.copyfile(exact_zip, target_directory / B15_FILENAME)
    (stage / "README_REVIEW.md").write_text("# D12 B15 REV2 focused security retest\n\nResult: PASS for the exact B15 REV2 bytes. See reports/D12_REV2/SECURITY_RETEST.md. A13 REV3 UI-to-API verification is NOT_RUN_INPUT_UNAVAILABLE.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d12_rev2 -t . -v\n", encoding="utf-8")
    stage_suite = run_suite(stage, stage / "evidence/STAGE_TESTS.txt")
    package_audit = audit(stage)
    (stage / "evidence/PACKAGE_AUDIT.json").write_text(json.dumps(package_audit, indent=2) + "\n", encoding="utf-8")
    if not package_audit["passed"]:
        raise RuntimeError(f"PACKAGE_AUDIT_FAILURE:{package_audit}")
    build_result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "task_id": TASK_ID, "target": input_verification, "stage_suite": stage_suite, "package_audit": package_audit, "a13_rev3_ui_api_gate": "NOT_RUN_INPUT_UNAVAILABLE", "external_request_count": 0, "production_database_write_count": 0}
    (stage / "evidence/BUILD_RESULT.json").write_text(json.dumps(build_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"schema": "CDH-D12-R11-REV2-REVIEW-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_b15_rev2_sha256": B15_SHA256, "payloads": collect(stage)}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_delivery(release)
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    if release.read_bytes() != queue.read_bytes():
        raise RuntimeError("QUEUE_NOT_BYTE_IDENTICAL")
    post = work / f"post_extract_{verification['zip_sha256'][:8]}"
    post.mkdir(parents=True)
    with zipfile.ZipFile(release) as archive:
        archive.extractall(post)
    post_suite = run_suite(post / RELEASE_NAME, work / "post_extract_evidence/D12_REV2_TESTS.txt")
    result = {"release": str(release), "queue_copy": str(queue), "release_sha256": verification["zip_sha256"], "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": verification["manifest_sha256"], "verification": verification, "input": input_verification, "stage_suite": stage_suite, "post_extract_suite": post_suite, "package_audit": package_audit}
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
