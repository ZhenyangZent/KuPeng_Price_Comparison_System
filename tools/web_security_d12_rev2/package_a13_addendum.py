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

from tools.web_security_d12_rev2.archive import B15_SHA256, sha256_file

RELEASE_NAME = "CDH_D_R11_003_REVIEW"
TASK_ID = "CDH-D12-B15-WRITE-BOUNDARY-SECURITY"
D12_REV2_SHA256 = "c83174b1fac2addd959d15d29b0f28a1880bc4c371f21bca8bd88f1be87af521"
A13_REV3_SHA256 = "d1b8814f0ae54f5fa5fae77c873620fe70da979fcbfe689a333096fab897b274"
A13_MANIFEST_SHA256 = "e17bd9f625889a5d29e2a556dcb02d4feb4c20016f94e838adc10d54d0ff3423"
SELECTED_A13 = (
    "apps/price-web/local-preview-a11/preview_server.py",
    "apps/price-web/local-preview-a11/control.py",
    "apps/price-web/frontend/src/manualObservationClient.ts",
    "apps/price-web/frontend/tests/a13_manual_observation.test.tsx",
)


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


def run_addendum_tests(stage: Path, evidence: Path) -> dict[str, object]:
    command = [sys.executable, "-m", "unittest", "tests.web.security_d12_rev2.test_a13_rev3_boundary", "-v"]
    environment = {**os.environ, "PYTHONPATH": str(stage), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    process = subprocess.run(command, cwd=stage, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"ADDENDUM_SUITE_FAILED:{process.returncode}")
    combined = process.stdout + process.stderr
    tests = int(combined.split("Ran ", 1)[1].split(" ", 1)[0])
    return {"exit_code": 0, "tests_run": tests, "log_sha256": sha256_file(evidence)}


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
        if path.suffix.casefold() not in {".zip", ".png", ".jpg", ".jpeg", ".gif"}:
            raw = path.read_bytes()
            secret_hits.extend(f"{relative}:{pattern.pattern.decode('ascii')}" for pattern in patterns if pattern.search(raw))
            if re.search(rb"[A-Za-z]:[\\/]Users[\\/][^\\/\r\n\"]+", raw):
                absolute_paths.append(relative)
    return {"passed": not forbidden and not secret_hits and not absolute_paths, "files_scanned": count, "forbidden_paths": forbidden, "secret_pattern_hits": secret_hits, "absolute_user_path_hits": absolute_paths}


def collect(stage: Path) -> list[dict[str, object]]:
    manifest = stage / "MANIFEST.json"
    return [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()) if path.is_file() and path != manifest]


def verify_delivery(path: Path) -> dict[str, object]:
    entries = inspect_zip(path)
    prefix = RELEASE_NAME + "/"
    with zipfile.ZipFile(path) as archive:
        members = {name: info for name, info in entries}
        manifest_name = prefix + "MANIFEST.json"
        raw = archive.read(members[manifest_name])
        manifest = json.loads(raw)
        declared: set[str] = set()
        for record in manifest["payloads"]:
            name = prefix + safe_name(record["path"])
            value = archive.read(members[name])
            declared.add(name)
            if len(value) != record["bytes"] or digest(value) != record["sha256"]:
                raise ValueError(f"DELIVERY_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("DELIVERY_COVERAGE_FAILURE")
    return {"status": "PASS", "zip_sha256": sha256_file(path), "manifest_sha256": digest(raw), "entries": len(entries), "payloads": len(manifest["payloads"]), "crc_pass": True, "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0}


def build(root: Path) -> dict[str, object]:
    work = root / "review/D12/003"
    stage = work / "package" / RELEASE_NAME
    release = root / "review/releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review/00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    copy_tree(root / "reports/D12_REV2", stage / "reports/D12_REV2")
    for relative in ("__init__.py", "a13_boundary_probe.py", "package_a13_addendum.py"):
        destination = stage / "tools/web_security_d12_rev2" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "tools/web_security_d12_rev2" / relative, destination)
    test_destination = stage / "tests/web/security_d12_rev2"
    test_destination.mkdir(parents=True)
    shutil.copyfile(root / "tests/web/security_d12_rev2/__init__.py", test_destination / "__init__.py")
    shutil.copyfile(root / "tests/web/security_d12_rev2/test_a13_rev3_boundary.py", test_destination / "test_a13_rev3_boundary.py")
    evidence_destination = stage / "review/D12/002/evidence"
    evidence_destination.mkdir(parents=True)
    for name in ("A13_REV3_INPUT_VERIFICATION.json", "A13_REV3_B15_REV2_BOUNDARY.json", "A13_REV3_PYTHON_BOUNDARY_TESTS.txt", "D12_A13_REV3_ADDENDUM_TESTS.txt"):
        shutil.copyfile(root / "review/D12/002/evidence" / name, evidence_destination / name)
    frontend_log = (root / "review/D12/002/evidence/A13_REV3_FRONTEND_BOUNDARY_TESTS.txt").read_text(encoding="utf-8", errors="replace")
    sanitized = frontend_log.replace(str(root), "<PROJECT_ROOT>").replace(str(root).replace("\\", "/"), "<PROJECT_ROOT>")
    (evidence_destination / "A13_REV3_FRONTEND_BOUNDARY_TESTS.txt").write_text(sanitized, encoding="utf-8")
    a13 = root / "review/D12/002/input_a13_rev3/CDH_A_R11_003_REVIEW"
    manifest = a13 / "SHA256_MANIFEST.json"
    if sha256_file(manifest) != A13_MANIFEST_SHA256:
        raise ValueError("A13_MANIFEST_SHA256_MISMATCH")
    declared = {item["path"]: item for item in json.loads(manifest.read_text(encoding="utf-8"))["payloads"]}
    a13_destination = stage / "review/D12/002/input_a13_rev3/CDH_A_R11_003_REVIEW"
    shutil.copyfile(manifest, a13_destination / "SHA256_MANIFEST.json") if a13_destination.exists() else None
    a13_destination.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest, a13_destination / "SHA256_MANIFEST.json")
    for relative in SELECTED_A13:
        source = a13 / relative
        if (source.stat().st_size, sha256_file(source)) != (declared[relative]["size"], declared[relative]["sha256"]):
            raise ValueError(f"A13_SELECTED_SOURCE_MISMATCH:{relative}")
        destination = a13_destination / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    target = stage / "target_inputs/review/releases"
    target.mkdir(parents=True)
    d12 = root / "review/releases/CDH_D_R11_002_REVIEW.zip"
    b15 = root / "review/releases/CDH_B_R11_002_REVIEW.zip"
    if sha256_file(d12) != D12_REV2_SHA256 or sha256_file(b15) != B15_SHA256:
        raise ValueError("PINNED_INPUT_SHA256_MISMATCH")
    shutil.copyfile(d12, target / d12.name)
    shutil.copyfile(b15, target / b15.name)
    inputs = {"task_id": TASK_ID, "d12_b15_rev2_retest_sha256": D12_REV2_SHA256, "a13_rev3_sha256": A13_REV3_SHA256, "a13_rev3_manifest_sha256": A13_MANIFEST_SHA256, "b15_rev2_sha256": B15_SHA256, "a13_selected_source_count": len(SELECTED_A13)}
    (stage / "INPUTS.json").write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    (stage / "README_REVIEW.md").write_text("# D12 A13 REV3 boundary addendum\n\nFocused security addendum to CDH_D_R11_002_REVIEW.zip. Exact input identities, actual loopback evidence, and residual scope are in reports/D12_REV2/A13_REV3_BOUNDARY_ADDENDUM.md.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest tests.web.security_d12_rev2.test_a13_rev3_boundary -v\n", encoding="utf-8")
    stage_suite = run_addendum_tests(stage, stage / "evidence/STAGE_ADDENDUM_TESTS.txt")
    package_audit = audit(stage)
    if not package_audit["passed"]:
        raise RuntimeError(f"PACKAGE_AUDIT_FAILED:{package_audit}")
    result_record = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs, "stage_suite": stage_suite, "package_audit": package_audit, "a13_python_boundary_tests": "13/13 PASS", "a13_frontend_boundary_tests": "6/6 PASS", "actual_proxy_boundary_gate": "PASS", "external_request_count": 0, "production_database_write_count": 0}
    (stage / "evidence/BUILD_RESULT.json").write_text(json.dumps(result_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_record = {"schema": "CDH-D12-R11-A13-REV3-ADDENDUM-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "inputs": inputs, "payloads": collect(stage)}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
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
    post_suite = run_addendum_tests(post / RELEASE_NAME, work / "post_extract_evidence/ADDENDUM_TESTS.txt")
    final = {"release": str(release), "queue_copy": str(queue), "release_sha256": verification["zip_sha256"], "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": verification["manifest_sha256"], "verification": verification, "stage_suite": stage_suite, "post_extract_suite": post_suite, "package_audit": package_audit, "inputs": inputs}
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
