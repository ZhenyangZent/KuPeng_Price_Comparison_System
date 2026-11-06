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

from tools.web_security_d12.archive import B15_FILENAME, B15_SHA256, sha256_file

RELEASE_NAME = "CDH_D_R11_001_REVIEW"
TASK_ID = "CDH-D12-B15-WRITE-BOUNDARY-SECURITY"
INPUT_SHA256 = "8c1f71375dcf08df93f6c50cab35f7e196c641a70ca0f5b8184af3fd448b9bcb"
INPUT_MANIFEST_SHA256 = "9d136dddc77c2a6852d3440671ee456ca2bee05c21776e9a60138af5369abab7"
A13_SHA256 = "e5d8d2a689294a1587fe1d6abfa62a6f0f294bd0cfae717e26abac61bfe747da"
TARGETS = {
    "B15": (B15_FILENAME, B15_SHA256),
    "B14": ("CDH_B_R10_001_REVIEW.zip", "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9"),
    "C11_REV2": ("CDH_C_R10_002_REVIEW.zip", "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa"),
    "B11": ("CDH_B_R07_001_REVIEW.zip", "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a"),
}


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
        if bad is not None: raise ValueError(f"CRC_FAILURE:{path.name}:{bad}")
        for info in archive.infolist():
            name = safe_name(info.filename)
            if name.casefold() in folded: raise ValueError(f"CASEFOLD_DUPLICATE:{name}")
            if stat.S_ISLNK(info.external_attr >> 16): raise ValueError(f"SYMLINK_REFUSED:{name}")
            folded.add(name.casefold()); result.append((name, info))
    return result


def extract_authority(path: Path, destination: Path) -> dict[str, object]:
    if sha256_file(path) != INPUT_SHA256: raise ValueError("R11_INPUT_SHA256_MISMATCH")
    entries = inspect_zip(path)
    with zipfile.ZipFile(path) as archive:
        members = {name: info for name, info in entries}
        manifest_raw = archive.read(members["MANIFEST.json"])
        if digest(manifest_raw) != INPUT_MANIFEST_SHA256: raise ValueError("R11_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(manifest_raw)
        files = manifest.get("files")
        if manifest.get("schema") != "CDH-R11-DELTA-MANIFEST-1" or not isinstance(files, dict) or manifest.get("file_count") != len(files): raise ValueError("R11_MANIFEST_SCHEMA_MISMATCH")
        for name, expected in files.items():
            if digest(archive.read(members[safe_name(name)])) != expected: raise ValueError(f"R11_PAYLOAD_MISMATCH:{name}")
        if set(files) | {"MANIFEST.json"} != set(members): raise ValueError("R11_MANIFEST_COVERAGE_FAILURE")
        destination.mkdir(parents=True, exist_ok=False)
        for name, info in entries:
            target = destination.joinpath(*PurePosixPath(name).parts); target.parent.mkdir(parents=True, exist_ok=True)
            if not info.is_dir(): target.write_bytes(archive.read(info))
    return {"zip_sha256": INPUT_SHA256, "manifest_sha256": INPUT_MANIFEST_SHA256, "entries": len(entries), "payloads": len(files), "crc_pass": True, "manifest_coverage_pass": True}


def extract_b15_source(path: Path, destination: Path) -> None:
    entries = inspect_zip(path)
    prefixes = ("CDH_B_R11_001_REVIEW/services/", "CDH_B_R11_001_REVIEW/tests/")
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(path) as archive:
        for name, info in entries:
            if not name.startswith(prefixes) or info.is_dir(): continue
            target = destination.joinpath(*PurePosixPath(name).parts); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(archive.read(info))


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=lambda _d, names: [name for name in names if name in {"__pycache__", ".pytest_cache", "tmp_tests"} or name.endswith((".pyc", ".pyo"))])


def run(command: list[str], cwd: Path, evidence: Path, *, extra_env: dict[str, str] | None = None) -> dict[str, object]:
    env = {**os.environ, "PYTHONPATH": str(cwd), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **(extra_env or {})}
    process = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
    if process.returncode: raise RuntimeError(f"COMMAND_FAILED:{process.returncode}:{command}")
    combined = process.stdout + process.stderr; count = None
    if "Ran " in combined:
        token = combined.split("Ran ", 1)[1].split(" ", 1)[0]; count = int(token) if token.isdigit() else None
    return {"exit_code": 0, "tests_run": count, "evidence": evidence.name}


def suites(stage: Path, evidence: Path) -> dict[str, object]:
    b15 = stage / "review/D12/input_b15/CDH_B_R11_001_REVIEW"
    baseline = stage / "target_inputs/review/releases"
    return {
        "d12": run([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d12", "-t", ".", "-v"], stage, evidence / "D12_TESTS.txt"),
        "b15": run([sys.executable, "-m", "unittest", "discover", "-s", "tests/private_observation_b15", "-v"], b15, evidence / "B15_UPSTREAM_TESTS.txt", extra_env={"PYTHONPATH": str(b15 / "services/private_observation_b15"), "CDH_B15_BASELINE_ROOT": str(baseline)}),
    }


def audit(stage: Path) -> dict[str, object]:
    forbidden: list[str] = []; hits: list[str] = []; absolute_paths: list[str] = []
    patterns = (re.compile(rb"AKIA[0-9A-Z]{16}"), re.compile(rb"ghp_[A-Za-z0-9]{30,}"), re.compile(rb"github_pat_[A-Za-z0-9_]{40,}"), re.compile(rb"sk-(?:proj|live)-[A-Za-z0-9_-]{20,}"))
    files = 0
    for path in stage.rglob("*"):
        if not path.is_file(): continue
        files += 1; relative = path.relative_to(stage).as_posix(); name = path.name.casefold(); parts = {p.casefold() for p in PurePosixPath(relative).parts}
        if parts & {"__pycache__", ".git", ".venv", "node_modules"} or name == ".env" or (name.startswith(".env.") and name != ".env.example") or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".reg"}: forbidden.append(relative)
        if path.suffix.casefold() not in {".zip", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif"}:
            raw = path.read_bytes(); hits.extend(f"{relative}:{p.pattern.decode('ascii')}" for p in patterns if p.search(raw))
            if not relative.startswith("input_contract/") and re.search(rb"[A-Za-z]:\\Users\\[^\\\r\n\"]+", raw): absolute_paths.append(relative)
    return {"passed": not forbidden and not hits and not absolute_paths, "files_scanned": files, "forbidden_paths": forbidden, "secret_pattern_hits": hits, "absolute_user_path_hits": absolute_paths}


def collect(stage: Path) -> list[dict[str, object]]:
    top = stage / "MANIFEST.json"
    return [{"path": p.relative_to(stage).as_posix(), "bytes": p.stat().st_size, "sha256": sha256_file(p)} for p in sorted(stage.rglob("*"), key=lambda v: v.as_posix().casefold()) if p.is_file() and p != top]


def verify_delivery(path: Path) -> dict[str, object]:
    entries = inspect_zip(path); prefix = RELEASE_NAME + "/"
    with zipfile.ZipFile(path) as archive:
        members = {n: i for n, i in entries}; manifest_name = prefix + "MANIFEST.json"; raw = archive.read(members[manifest_name]); manifest = json.loads(raw); declared = set()
        for record in manifest["payloads"]:
            name = prefix + safe_name(record["path"]); value = archive.read(members[name]); declared.add(name)
            if len(value) != record["bytes"] or digest(value) != record["sha256"]: raise ValueError(f"DELIVERY_MISMATCH:{name}")
        if declared | {manifest_name} != set(members): raise ValueError("DELIVERY_COVERAGE_FAILURE")
    return {"status": "PASS", "zip_sha256": sha256_file(path), "manifest_sha256": digest(raw), "entries": len(entries), "payloads": len(manifest["payloads"]), "crc_pass": True, "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0}


def build(root: Path, authority: Path) -> dict[str, object]:
    work = root / "review/D12/001"; stage = work / "package" / RELEASE_NAME; release = root / "review/releases" / f"{RELEASE_NAME}.zip"; queue = root / "review/00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists(): raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security_d12", "tests/web/security_d12", "reports/D12"): copy_tree(root / relative, stage / relative)
    evidence = stage / "review/D12"; evidence.mkdir(parents=True)
    for name in ("REPARSE_ESCAPE_EVIDENCE.json", "HTTP_PROBE.json", "MINIMAL_FAILURE_INPUTS.json"): shutil.copyfile(root / "review/D12" / name, evidence / name)
    input_result = extract_authority(authority, stage / "input_contract")
    target_dir = stage / "target_inputs/review/releases"; target_dir.mkdir(parents=True)
    target_hashes = {}
    for role, (name, expected) in TARGETS.items():
        source = root / "review/releases" / name; actual = sha256_file(source)
        if actual != expected: raise ValueError(f"TARGET_SHA_MISMATCH:{role}:{actual}")
        shutil.copyfile(source, target_dir / name); target_hashes[role] = actual
    a13 = root / "review/releases/CDH_A_R11_001_REVIEW.zip"
    if sha256_file(a13) != A13_SHA256: raise ValueError("A13_INPUT_IDENTITY_MISMATCH")
    extract_b15_source(target_dir / B15_FILENAME, stage / "review/D12/input_b15")
    (stage / "README_REVIEW.md").write_text("# D12 B15 focused write-boundary review\n\nTerminal result: REWORK_REQUIRED_P1. Exact reproduction and remediation are in reports/D12/FINDINGS.md. A13 REV2 integration is not run because only the incompatible original A13 was available.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d12 -t . -v\n", encoding="utf-8")
    stage_suites = suites(stage, stage / "evidence")
    package_audit = audit(stage); (stage / "evidence/PACKAGE_AUDIT.json").write_text(json.dumps(package_audit, indent=2) + "\n", encoding="utf-8")
    if not package_audit["passed"]: raise RuntimeError(f"PACKAGE_AUDIT_FAILURE:{package_audit}")
    build_result = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "input": input_result, "targets": target_hashes, "a13_received_sha256": A13_SHA256, "a13_rev2_integration": "NOT_RUN_REV2_INPUT_UNAVAILABLE", "stage_suites": stage_suites, "http_probe": "PASS_8_OF_8", "reparse_probe": "FAIL_P1_REPRODUCED", "priority_counts": {"P0": 0, "P1": 1, "P2": 2}, "package_audit": package_audit}
    (stage / "evidence/BUILD_RESULT.json").write_text(json.dumps(build_result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payloads = collect(stage); manifest = {"schema": "CDH-D12-R11-REVIEW-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_bundle_sha256": INPUT_SHA256, "input_manifest_sha256": INPUT_MANIFEST_SHA256, "target_release_sha256": target_hashes, "a13_received_sha256": A13_SHA256, "a13_rev2_integration": "NOT_RUN_REV2_INPUT_UNAVAILABLE", "status": "REWORK_REQUIRED_P1", "priority_counts": {"P0": 0, "P1": 1, "P2": 2}, "payload_count": len(payloads), "payloads": payloads}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for p in sorted(stage.rglob("*"), key=lambda v: v.as_posix().casefold()):
            if p.is_file(): archive.write(p, f"{RELEASE_NAME}/{p.relative_to(stage).as_posix()}")
    verification = verify_delivery(release); queue.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(release, queue)
    if release.read_bytes() != queue.read_bytes(): raise RuntimeError("QUEUE_NOT_BYTE_IDENTICAL")
    post = work / f"post_extract_{verification['zip_sha256'][:8]}"; post.mkdir(parents=True)
    with zipfile.ZipFile(release) as archive: archive.extractall(post)
    post_suites = suites(post / RELEASE_NAME, work / "post_extract_evidence")
    result = {"release": str(release), "queue_copy": str(queue), "release_sha256": verification["zip_sha256"], "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": verification["manifest_sha256"], "verification": verification, "input": input_result, "stage_suites": stage_suites, "post_extract_suites": post_suites}
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2]); parser.add_argument("--authority", type=Path, required=True); args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.authority.resolve()), ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
