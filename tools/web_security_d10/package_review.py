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

from tools.web_security_d06.targets import normalize_member_name, sha256_file
from tools.web_security_d09.portable import verify_review_target
from tools.web_security_d10.targets import FILES, HASHES


RELEASE_NAME = "CDH_D_R09_001_REVIEW"
TASK_ID = "CDH-D10-INTEGRATED-REVIEW-SECURITY-001"
INPUT_SHA256 = "be0ee2febae110a16bac12dd6c00e26c74e8006f4eb944b5fdad0d6d0a76a71b"
INPUT_MANIFEST_SHA256 = "e72aa27c08e7e496c09628a905652a39ccc2f8e2cbdc1e523ddf4fe28e95a476"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=lambda _d, names: [name for name in names if name in {"__pycache__", ".pytest_cache", "node_modules", "dist", "runtime_probe", "runtime_tmp"} or name.endswith((".pyc", ".pyo"))])


def extract_authority(bundle: Path, destination: Path) -> dict[str, object]:
    if sha256_file(bundle) != INPUT_SHA256:
        raise ValueError("R09_INPUT_SHA256_MISMATCH")
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:
            raise ValueError("R09_INPUT_CRC_FAILURE")
        members: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in archive.infolist():
            name = normalize_member_name(info.orig_filename)
            if name.casefold() in folded or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("R09_INPUT_COLLISION_OR_SYMLINK")
            folded.add(name.casefold())
            members[name] = info
        manifest_raw = archive.read(members["MANIFEST.json"])
        if digest(manifest_raw) != INPUT_MANIFEST_SHA256:
            raise ValueError("R09_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(manifest_raw)
        if manifest.get("schema") != "CDH-R09-UNIFIED-TASK-MANIFEST-1":
            raise ValueError("R09_MANIFEST_SCHEMA_MISMATCH")
        records = manifest.get("payloads")
        declared: set[str] = set()
        for record in records:
            name = normalize_member_name(record["path"])
            raw = archive.read(members[name])
            declared.add(name)
            if len(raw) != record["bytes"] or digest(raw) != record["sha256"]:
                raise ValueError(f"R09_MANIFEST_PAYLOAD_MISMATCH:{name}")
        if declared | {"MANIFEST.json"} != set(members):
            raise ValueError("R09_MANIFEST_COVERAGE_FAILURE")
        destination.mkdir(parents=True, exist_ok=False)
        for name, info in members.items():
            target = destination.joinpath(*PurePosixPath(name.rstrip("/")).parts)
            if name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
    return {"zip_sha256": INPUT_SHA256, "manifest_sha256": INPUT_MANIFEST_SHA256, "entries": len(members), "payloads": len(records), "crc_pass": True, "safe_paths": True, "no_symlinks": True, "no_casefold_duplicates": True, "manifest_coverage_pass": True}


def run(command: list[str], cwd: Path, evidence: Path) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(cwd)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run(command, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False, timeout=360)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {process.returncode}\n\nSTDOUT\n{process.stdout}\nSTDERR\n{process.stderr}", encoding="utf-8")
    if process.returncode:
        raise RuntimeError(f"D10_COMMAND_FAILURE:{process.returncode}:{command}")
    combined = process.stdout + process.stderr
    count = None
    if "Ran " in combined:
        value = combined.split("Ran ", 1)[1].split(" ", 1)[0]
        count = int(value) if value.isdigit() else None
    return {"exit_code": process.returncode, "tests_run": count, "evidence": evidence.name}


def audit_stage(stage: Path) -> dict[str, object]:
    forbidden: list[str] = []
    hits: list[str] = []
    signatures = (b"AK" + b"IA", b"gh" + b"p_", b"github" + b"_pat_", b"sk-" + b"proj-", b"sk-" + b"live-")
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
            hits.extend(f"{relative}:{item.decode('ascii')}" for item in signatures if item in raw)
    return {"passed": not forbidden and not hits, "files_scanned": files, "forbidden_paths": forbidden, "secret_pattern_hits": hits}


def collect(stage: Path) -> list[dict[str, object]]:
    top = stage / "MANIFEST.json"
    return [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()) if path.is_file() and path != top]


def gate_command(output: str | None = None) -> list[str]:
    command = [sys.executable, "-m", "tools.web_security_d10.gate", "--releases", "target_inputs/review/releases"]
    if output:
        command.extend(["--json-out", output])
    return command


def upstream_command(role: str, evidence: str) -> list[str]:
    return [sys.executable, "-m", "tools.web_security_d10.upstream", "--zip", f"target_inputs/review/releases/{FILES[role]}", "--role", role, "--evidence", evidence]


def build(root: Path, authority: Path) -> dict[str, object]:
    work = root / "review" / "D10" / "001"
    stage = work / "package" / RELEASE_NAME
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review" / "00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security_d06", "tools/web_security_d09", "tools/web_security_d10", "tests/web/security_d10", "reports/D10"):
        copy_tree(root / relative, stage / relative)
    copy_tree(work / "evidence", stage / "evidence")
    input_result = extract_authority(authority, stage / "input_contract")
    target_dir = stage / "target_inputs" / "review" / "releases"
    target_dir.mkdir(parents=True)
    for role, filename in FILES.items():
        source = root / "review" / "releases" / filename
        if sha256_file(source) != HASHES[role]:
            raise ValueError(f"D10_TARGET_IDENTITY_FAILURE:{role}")
        shutil.copyfile(source, target_dir / filename)
    orchestrator = stage / "target_inputs" / "orchestrator"
    orchestrator.mkdir(parents=True)
    shutil.copyfile(authority, orchestrator / authority.name)
    (stage / "README_REVIEW.md").write_text("# D10 R09 exact integrated security review\n\nOffline/synthetic exact A10 R08, B11, B12, C09 and F07 review. Contains one upstream B12 P1 and three P2 findings. Browser integration is NOT_RUN_ENV_BLOCKED.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d10 -t . -v\n", encoding="utf-8")
    (stage / "RUN_GATE.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m tools.web_security_d10.gate --releases target_inputs/review/releases --json-out evidence/GATE_RESULT.json\n", encoding="utf-8")
    suite = run([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d10", "-t", ".", "-v"], stage, stage / "evidence" / "D10_TESTS.txt")
    gate = run(gate_command("evidence/GATE_RESULT.json"), stage, stage / "evidence" / "GATE_OUTPUT.txt")
    upstream = {role: run(upstream_command(role, f"evidence/{role}_UPSTREAM_TESTS.txt"), stage, stage / "evidence" / f"{role}_UPSTREAM_OUTPUT.txt") for role in ("B11", "B12", "C09")}
    gate_value = json.loads((stage / "evidence" / "GATE_RESULT.json").read_text(encoding="utf-8"))
    if gate_value["audit_execution"] != "PASS" or gate_value["priority_counts"] != {"P0": 0, "P1": 1, "P2": 3}:
        raise RuntimeError("D10_GATE_EXPECTATION_FAILURE")
    audit = audit_stage(stage)
    (stage / "evidence" / "PACKAGE_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not audit["passed"]:
        raise RuntimeError(f"D10_PACKAGE_AUDIT_FAILURE:{audit}")
    build_info = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "input": input_result, "targets": HASHES, "suite": suite, "gate": gate, "upstream": upstream, "audit": audit, "findings": gate_value["priority_counts"], "browser": gate_value["browser_integration"], "restrictions": gate_value["restrictions"]}
    (stage / "evidence" / "BUILD_RESULT.json").write_text(json.dumps(build_info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = collect(stage)
    manifest = {"schema": "CDH-D10-R09-REVIEW-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_bundle_sha256": INPUT_SHA256, "input_manifest_sha256": INPUT_MANIFEST_SHA256, "target_release_sha256": HASHES, "payload_count": len(records), "payloads": records, "status": "READY_FOR_REVIEW_WITH_P1_FINDING", "priority_counts": {"P0": 0, "P1": 1, "P2": 3}, "browser_integration": gate_value["browser_integration"]}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_review_target(release, sha256_file(release)).as_dict()
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    if queue.read_bytes() != release.read_bytes():
        raise RuntimeError("D10_QUEUE_COPY_MISMATCH")
    post = work / f"post_extract_{sha256_file(release)[:8]}"
    if post.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{post}")
    with zipfile.ZipFile(release) as archive:
        archive.extractall(post)
    extracted = post / RELEASE_NAME
    post_suite = run([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d10", "-t", ".", "-v"], extracted, work / "POST_EXTRACT_D10_TESTS.txt")
    post_gate = run(gate_command(), extracted, work / "POST_EXTRACT_GATE.txt")
    post_upstream = {role: run(upstream_command(role, f"review/D10/001/{role}_UPSTREAM_TESTS.txt"), extracted, work / f"POST_EXTRACT_{role}.txt") for role in ("B11", "B12", "C09")}
    result = {"release": str(release), "queue_copy": str(queue), "release_sha256": sha256_file(release), "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": sha256_file(stage / "MANIFEST.json"), "verification": verification, "input": input_result, "staged": {"suite": suite, "gate": gate, "upstream": upstream}, "post_extract": {"suite": post_suite, "gate": post_gate, "upstream": post_upstream}}
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
