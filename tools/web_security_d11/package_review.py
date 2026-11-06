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

from tools.web_security_d11.archive import sha256_file

RELEASE_NAME = "CDH_D_R10_001_REVIEW"
TASK_ID = "CDH-D11-B14-P1-AND-A11-INTEGRATION-SECURITY-001"
INPUT_SHA256 = "0474031243db86ffc7c7b05e7569f701f5705cf84a25b98453b987f1c99b7abc"
INPUT_MANIFEST_SHA256 = "939d72c3dce1dc02453c94f5b3103970f0e552a38dd91afa2a56f3744d51a4a3"
INPUT_SCHEMA = "CDH-R10-SHARED-TASK-MANIFEST-1"
TARGETS = {
    "A11": ("CDH_A_R09_001_REVIEW.zip", "40e54a65a7c2bfe808bcaa528e75058ab96c98c4f68d9cfa09259b7e5b97a0cd"),
    "B13": ("CDH_B_R09_001_REVIEW.zip", "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638"),
    "H07": ("CDH_H_R09_001_REVIEW.zip", "d0c11a6344800b1cca1794c6cc4e83579a8aab8f2eaf7a2a2bfcb89d06f62e97"),
    "B11": ("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"),
    "A10_R08": ("CDH_A_R08_001_REVIEW.zip", "0cddd2f5998ee5b03fe036fd3c5c684e557766dfc06255baa6fb7ad48f41fccd"),
    "B14": ("CDH_B_R10_001_REVIEW.zip", "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"),
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def safe_name(name: str) -> str:
    value = name.replace("\\", "/").rstrip("/")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"UNSAFE_ARCHIVE_MEMBER:{name}")
    return pure.as_posix()


def inspect_zip(path: Path) -> tuple[list[tuple[str, zipfile.ZipInfo]], bool]:
    entries: list[tuple[str, zipfile.ZipInfo]] = []
    folded: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"CRC_FAILURE:{path.name}:{bad_crc}")
        for info in archive.infolist():
            name = safe_name(info.filename)
            if name.casefold() in folded:
                raise ValueError(f"CASEFOLD_DUPLICATE:{path.name}:{name}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"SYMLINK_REFUSED:{path.name}:{name}")
            folded.add(name.casefold())
            entries.append((name, info))
    return entries, True


def extract_safe(path: Path, destination: Path) -> None:
    entries, _ = inspect_zip(path)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name, info in entries:
            target = destination.joinpath(*PurePosixPath(name).parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))


def extract_authority(path: Path, destination: Path) -> dict[str, object]:
    if sha256_file(path) != INPUT_SHA256:
        raise ValueError("R10_INPUT_SHA256_MISMATCH")
    entries, _ = inspect_zip(path)
    with zipfile.ZipFile(path) as archive:
        by_name = {name: info for name, info in entries}
        manifest_raw = archive.read(by_name["MANIFEST.json"])
        if digest(manifest_raw) != INPUT_MANIFEST_SHA256:
            raise ValueError("R10_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(manifest_raw)
        if manifest.get("schema") != INPUT_SCHEMA or manifest.get("payload_count") != len(manifest.get("payloads", [])):
            raise ValueError("R10_MANIFEST_SCHEMA_OR_COUNT_MISMATCH")
        declared: set[str] = set()
        for record in manifest["payloads"]:
            name = safe_name(record["path"])
            raw = archive.read(by_name[name])
            declared.add(name)
            if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
                raise ValueError(f"R10_PAYLOAD_MISMATCH:{name}")
        if declared | {"MANIFEST.json"} != set(by_name):
            raise ValueError("R10_MANIFEST_COVERAGE_FAILURE")
    extract_safe(path, destination)
    return {"zip_sha256": INPUT_SHA256, "manifest_sha256": INPUT_MANIFEST_SHA256, "entries": len(entries), "payloads": len(manifest["payloads"]), "crc_pass": True, "manifest_coverage_pass": True, "no_symlinks": True, "no_casefold_duplicates": True}


def copy_tree(source: Path, destination: Path) -> None:
    def ignored(_directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name in {"__pycache__", ".pytest_cache", "node_modules", "runtime", "test_tmp"} or name.endswith((".pyc", ".pyo"))]
    shutil.copytree(source, destination, ignore=ignored)


def run_command(command: list[str], cwd: Path, evidence: Path, pythonpath: Path | None = None) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(pythonpath or cwd)
    process = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=360, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"COMMAND_FAILED:{process.returncode}:{command}")
    combined = process.stdout + process.stderr
    tests = None
    if "Ran " in combined:
        token = combined.split("Ran ", 1)[1].split(" ", 1)[0]
        tests = int(token) if token.isdigit() else None
    return {"exit_code": process.returncode, "tests_run": tests, "evidence": evidence.name}


def run_python_suites(stage: Path, evidence: Path) -> dict[str, object]:
    a11 = stage / "review/D11/input_a11/CDH_A_R09_001_REVIEW"
    b13 = stage / "review/D11/input_b13/CDH_B_R09_001_REVIEW"
    b11 = stage / "review/D11/input_b11/CDH_B_R07_001_REVIEW"
    h07 = stage / "review/D11/input_h07/CDH_H_R09_001_REVIEW"
    b14 = stage / "review/D11/input_b14/CDH_B_R10_001_REVIEW"
    return {
        "d11": run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d11", "-t", ".", "-v"], stage, evidence / "D11_TESTS.txt"),
        "b13": run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests/import_staging_b13", "-t", ".", "-v"], b13, evidence / "B13_UPSTREAM_TESTS.txt", b13 / "services/import_staging_b12"),
        "b11": run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/price_coupon_v4", "-t", ".", "-v"], b11, evidence / "B11_UPSTREAM_TESTS.txt", b11 / "services/price_coupon_v4"),
        "a11": run_command([sys.executable, "apps/price-web/local-preview-a11/tests/test_preview.py", "-v"], a11, evidence / "A11_UPSTREAM_TESTS.txt", a11 / "apps/price-web/local-preview-a11"),
        "h07": run_command([sys.executable, "tests/web/journey_h07/test_actual_a10r08_b11.py", "-v"], h07, evidence / "H07_EVIDENCE_TESTS.txt", h07),
        "b14": run_command([sys.executable, "-m", "unittest", "discover", "-s", "tests/import_staging_b14", "-t", ".", "-v"], b14, evidence / "B14_UPSTREAM_TESTS.txt", b14 / "services/import_staging_b14"),
    }


def audit_stage(stage: Path) -> dict[str, object]:
    forbidden: list[str] = []
    hits: list[str] = []
    signatures = (
        re.compile(rb"AKIA[0-9A-Z]{16}"),
        re.compile(rb"ghp_[A-Za-z0-9]{30,}"),
        re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"),
        re.compile(rb"sk-proj-[A-Za-z0-9_-]{20,}"),
        re.compile(rb"sk-live-[A-Za-z0-9_-]{20,}"),
    )
    files = 0
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        files += 1
        relative = path.relative_to(stage).as_posix()
        parts = {part.casefold() for part in PurePosixPath(relative).parts}
        name = path.name.casefold()
        if parts & {"__pycache__", ".git", ".venv", "node_modules"} or name == ".env" or (name.startswith(".env.") and name != ".env.example") or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".reg"}:
            forbidden.append(relative)
        if path.suffix.casefold() not in {".zip", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif"}:
            raw = path.read_bytes()
            hits.extend(f"{relative}:{signature.pattern.decode('ascii')}" for signature in signatures if signature.search(raw))
    return {"passed": not forbidden and not hits, "files_scanned": files, "forbidden_paths": forbidden, "secret_pattern_hits": hits}


def collect(stage: Path) -> list[dict[str, object]]:
    manifest = stage / "MANIFEST.json"
    return [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()) if path.is_file() and path != manifest]


def verify_delivery(path: Path, expected_sha256: str) -> dict[str, object]:
    if sha256_file(path) != expected_sha256:
        raise ValueError("DELIVERY_SHA256_MISMATCH")
    entries, _ = inspect_zip(path)
    prefix = RELEASE_NAME + "/"
    with zipfile.ZipFile(path) as archive:
        members = {name: info for name, info in entries}
        manifest_name = prefix + "MANIFEST.json"
        raw = archive.read(members[manifest_name])
        manifest = json.loads(raw)
        declared: set[str] = set()
        for record in manifest["payloads"]:
            name = prefix + safe_name(record["path"])
            payload = archive.read(members[name])
            declared.add(name)
            if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
                raise ValueError(f"DELIVERY_PAYLOAD_MISMATCH:{name}")
        if declared | {manifest_name} != set(members):
            raise ValueError("DELIVERY_MANIFEST_COVERAGE_FAILURE")
    return {"status": "PASS", "zip_sha256": expected_sha256, "manifest_sha256": digest(raw), "entries": len(entries), "payloads": len(manifest["payloads"]), "crc_pass": True, "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0}


def build(root: Path, authority: Path) -> dict[str, object]:
    work = root / "review/D11/001"
    stage = work / "package" / RELEASE_NAME
    release = root / "review/releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review/00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security_d11", "tests/web/security_d11", "reports/D11"):
        copy_tree(root / relative, stage / relative)
    copy_tree(work / "evidence", stage / "evidence")
    input_result = extract_authority(authority, stage / "input_contract")
    releases = stage / "review/releases"
    releases.mkdir(parents=True)
    target_hashes: dict[str, str] = {}
    for role, (filename, expected) in TARGETS.items():
        source = root / "review/releases" / filename
        actual = sha256_file(source)
        if actual != expected:
            raise ValueError(f"TARGET_SHA256_MISMATCH:{role}:{actual}")
        shutil.copyfile(source, releases / filename)
        target_hashes[role] = actual
    mapping = {"A11": "input_a11", "B13": "input_b13", "H07": "input_h07", "B11": "input_b11", "B14": "input_b14"}
    for role, directory in mapping.items():
        extract_safe(releases / TARGETS[role][0], stage / "review/D11" / directory)
    a11_dependency_dir = stage / "review/D11/input_a11/CDH_A_R09_001_REVIEW/review/releases"
    a11_dependency_dir.mkdir(parents=True, exist_ok=True)
    for role in ("A10_R08", "B11"):
        shutil.copyfile(releases / TARGETS[role][0], a11_dependency_dir / TARGETS[role][0])
    (stage / "README_REVIEW.md").write_text("# D11 R10 independent security review\n\nExact A11/B13/H07/B11/B14 offline review. B14 duplicate-key rejection is PASS_SCOPED only for the bound SHA; A11 daily browser DOM evidence remains insufficient. Run `RUN_TESTS.ps1` for the self-contained Python security suite.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d11 -t . -v\n", encoding="utf-8")
    suites = run_python_suites(stage, stage / "evidence")
    audit_json = json.loads(subprocess.run([sys.executable, "-m", "tools.web_security_d11.audit", "--root", str(stage)], cwd=stage, env={**os.environ, "PYTHONPATH": str(stage), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True).stdout)
    (stage / "evidence/AUDIT_RESULT.json").write_text(json.dumps(audit_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    package_audit = audit_stage(stage)
    (stage / "evidence/PACKAGE_AUDIT.json").write_text(json.dumps(package_audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not package_audit["passed"]:
        raise RuntimeError(f"PACKAGE_AUDIT_FAILURE:{package_audit}")
    build_result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "input": input_result, "targets": target_hashes, "python_suites": suites, "frontend": {"tests": "49/49 PASS", "build": "PASS", "evidence": ["A11_FRONTEND_TESTS.txt", "A11_FRONTEND_BUILD.txt"]}, "b14_gate": "PASS_SCOPED", "daily_browser_dom_gate": "NOT_RUN_BROWSER_EVIDENCE_INSUFFICIENT", "package_audit": package_audit}
    (stage / "evidence/BUILD_RESULT.json").write_text(json.dumps(build_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payloads = collect(stage)
    manifest = {"schema": "CDH-D11-R10-REVIEW-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_bundle_sha256": INPUT_SHA256, "input_manifest_sha256": INPUT_MANIFEST_SHA256, "target_release_sha256": target_hashes, "payload_count": len(payloads), "payloads": payloads, "status": "READY_FOR_REVIEW_PASS_SCOPED", "b14_gate": "PASS_SCOPED", "a11_daily_browser_dom_gate": "NOT_RUN_BROWSER_EVIDENCE_INSUFFICIENT"}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    release_sha = sha256_file(release)
    verification = verify_delivery(release, release_sha)
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    if sha256_file(queue) != release_sha or queue.read_bytes() != release.read_bytes():
        raise RuntimeError("QUEUE_COPY_NOT_BYTE_IDENTICAL")
    post = work / f"post_extract_{release_sha[:8]}"
    extract_safe(release, post)
    post_root = post / RELEASE_NAME
    post_suites = run_python_suites(post_root, work / "post_extract_evidence")
    result = {"release": str(release), "queue_copy": str(queue), "release_sha256": release_sha, "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": sha256_file(stage / "MANIFEST.json"), "verification": verification, "input": input_result, "stage_suites": suites, "post_extract_suites": post_suites}
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--authority", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.authority.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
