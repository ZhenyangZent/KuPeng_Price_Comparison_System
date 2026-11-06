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


RELEASE_NAME = "CDH_D_R08_001_REVIEW"
TASK_ID = "CDH-D09-PORTABLE-ZIP-VERIFIER-AND-B11-SECURITY-001"
INPUT_SHA256 = "61d75b334fd7073202691bab887186261c85d1fa42af05e79f16d1a46f24b144"
INPUT_MANIFEST_SHA256 = "f2ff4d693c59818b5c425a74522ebbd44a46a3eacdfe3b55d3cfbb2d520f97d6"
TARGETS = {
    "CDH_A_R06_001_REVIEW.zip": "96d239e4a3bb5ca57624c0b8d6e06344ad68b6482b13d8ee9b72a8f1997ebbde",
    "CDH_B_R06_001_REVIEW.zip": "dfef51befb8785e069e4be5514b4eec106952deb5f52ee4cd98974c50273e549",
    "CDH_F_R06_001_REVIEW.zip": "8a90dd7c8d6212ec1d54a9e2c6004cdf25d5f7cc92636011b52e1ead6ed94dfc",
    "CDH_B_R07_001_REVIEW.zip": "6c51730debbd1388685b479ef9b945a5f7616b2a435af8bda2d86dbca6f4fd8a",
    "CDH_F_R07_001_REVIEW.zip": "c2db9aa981cbc935b52944516d5b4259829ffa5af892ac3dc7d28fc6b022ac89",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, ignore=lambda _d, names: [name for name in names if name in {"__pycache__", ".pytest_cache"} or name.endswith((".pyc", ".pyo"))])


def extract_authority(bundle: Path, destination: Path) -> dict[str, object]:
    if sha256_file(bundle) != INPUT_SHA256:
        raise ValueError("R08_INPUT_SHA256_MISMATCH")
    with zipfile.ZipFile(bundle) as archive:
        if archive.testzip() is not None:
            raise ValueError("R08_INPUT_CRC_FAILURE")
        members: dict[str, zipfile.ZipInfo] = {}
        folded: set[str] = set()
        for info in archive.infolist():
            name = normalize_member_name(info.orig_filename)
            if name.casefold() in folded or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("R08_INPUT_COLLISION_OR_SYMLINK")
            folded.add(name.casefold())
            members[name] = info
        raw_manifest = archive.read(members["MANIFEST.json"])
        if sha(raw_manifest) != INPUT_MANIFEST_SHA256:
            raise ValueError("R08_MANIFEST_SHA256_MISMATCH")
        manifest = json.loads(raw_manifest)
        if manifest.get("schema") != "CDH-R08-UNIFIED-TASK-MANIFEST-1":
            raise ValueError("R08_MANIFEST_SCHEMA_MISMATCH")
        records = manifest.get("payloads")
        declared: set[str] = set()
        for record in records:
            name = normalize_member_name(record["path"])
            raw = archive.read(members[name])
            declared.add(name)
            if len(raw) != record["bytes"] or sha(raw) != record["sha256"]:
                raise ValueError(f"R08_MANIFEST_PAYLOAD_MISMATCH:{name}")
        if declared | {"MANIFEST.json"} != set(members):
            raise ValueError("R08_MANIFEST_COVERAGE_FAILURE")
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
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(cwd)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=cwd, env=environment, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=360, check=False)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("COMMAND: " + " ".join(command) + f"\nEXIT_CODE: {result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}", encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"COMMAND_FAILURE:{result.returncode}:{command}")
    combined = result.stdout + result.stderr
    tests = None
    if "Ran " in combined:
        value = combined.split("Ran ", 1)[1].split(" ", 1)[0]
        tests = int(value) if value.isdigit() else None
    return {"exit_code": result.returncode, "tests_run": tests, "evidence": evidence.name}


def audit_stage(stage: Path) -> dict[str, object]:
    forbidden: list[str] = []
    secret_hits: list[str] = []
    signatures = (b"AK" + b"IA", b"gh" + b"p_", b"github" + b"_pat_", b"sk-" + b"proj-", b"sk-" + b"live-")
    files = 0
    for path in stage.rglob("*"):
        if not path.is_file():
            continue
        files += 1
        relative = path.relative_to(stage).as_posix()
        parts = {part.casefold() for part in PurePosixPath(relative).parts}
        basename = path.name.casefold()
        if parts & {"__pycache__", ".git", ".venv", "node_modules"} or basename == ".env" or (basename.startswith(".env.") and basename != ".env.example") or path.suffix.casefold() in {".key", ".pem", ".p12", ".pfx", ".reg"}:
            forbidden.append(relative)
        if path.suffix.casefold() not in {".zip", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg", ".gif"}:
            raw = path.read_bytes()
            secret_hits.extend(f"{relative}:{value.decode('ascii')}" for value in signatures if value in raw)
    return {"passed": not forbidden and not secret_hits, "files_scanned": files, "forbidden_paths": forbidden, "secret_pattern_hits": secret_hits}


def collect(stage: Path) -> list[dict[str, object]]:
    top_manifest = stage / "MANIFEST.json"
    return [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()) if path.is_file() and path != top_manifest]


def gate_command(output: str | None = None) -> list[str]:
    command = [sys.executable, "-m", "tools.web_security_d09.gate", "--releases", "target_inputs/review/releases", "--r07-bundle", "target_inputs/orchestrator/CDH_UNIFIED_CONTINUOUS_20261105_R07.zip"]
    if output:
        command.extend(["--json-out", output])
    return command


def upstream_command(role: str, evidence: str) -> list[str]:
    filename = "CDH_B_R07_001_REVIEW.zip" if role == "B11" else "CDH_F_R07_001_REVIEW.zip"
    return [sys.executable, "-m", "tools.web_security_d09.upstream", "--zip", f"target_inputs/review/releases/{filename}", "--role", role, "--evidence", evidence]


def build(root: Path, r08_bundle: Path, r07_bundle: Path) -> dict[str, object]:
    work = root / "review" / "D09" / "001"
    stage = work / "package" / RELEASE_NAME
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    queue = root / "review" / "00_TO_UPLOAD" / f"{RELEASE_NAME}.zip"
    for target in (stage, release, queue):
        if target.exists():
            raise FileExistsError(f"REFUSING_TO_OVERWRITE:{target}")
    stage.mkdir(parents=True)
    for relative in ("tools/web_security_d06", "tools/web_security_d08", "tools/web_security_d09", "tests/web/security_d09", "reports/D09"):
        copy_tree(root / relative, stage / relative)
    input_result = extract_authority(r08_bundle, stage / "input_contract")
    target_dir = stage / "target_inputs" / "review" / "releases"
    target_dir.mkdir(parents=True)
    for name, expected in TARGETS.items():
        source = root / "review" / "releases" / name
        if sha256_file(source) != expected:
            raise ValueError(f"TARGET_SHA256_MISMATCH:{name}")
        shutil.copyfile(source, target_dir / name)
    orchestrator = stage / "target_inputs" / "orchestrator"
    orchestrator.mkdir(parents=True)
    if sha256_file(r07_bundle) != "76b1332c3e2cd82a05e5f26e6d3e0c01cdf65e828f82d5b586902bdfacda2827":
        raise ValueError("R07_BUNDLE_SHA256_MISMATCH")
    shutil.copyfile(r07_bundle, orchestrator / r07_bundle.name)
    shutil.copyfile(r08_bundle, orchestrator / r08_bundle.name)
    (stage / "README_REVIEW.md").write_text("# D09 R08 portable ZIP and B11 security review\n\nSelf-contained offline/synthetic verification. A10+B11 full-site integration remains NOT_RUN_INPUT_NOT_CENTRALLY_ACKNOWLEDGED.\n", encoding="utf-8")
    (stage / "RUN_TESTS.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m unittest discover -s tests/web/security_d09 -t . -v\n", encoding="utf-8")
    (stage / "RUN_GATE.ps1").write_text("$ErrorActionPreference='Stop'\n$env:PYTHONPATH=(Resolve-Path '.').Path\n$env:PYTHONDONTWRITEBYTECODE='1'\npython -m tools.web_security_d09.gate --releases target_inputs/review/releases --r07-bundle target_inputs/orchestrator/CDH_UNIFIED_CONTINUOUS_20261105_R07.zip --json-out evidence/GATE_RESULT.json\n", encoding="utf-8")
    suite = run([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d09", "-t", ".", "-v"], stage, stage / "evidence" / "D09_TESTS.txt")
    gate = run(gate_command("evidence/GATE_RESULT.json"), stage, stage / "evidence" / "GATE_OUTPUT.txt")
    b11 = run(upstream_command("B11", "evidence/B11_UPSTREAM_TESTS.txt"), stage, stage / "evidence" / "B11_UPSTREAM_OUTPUT.txt")
    f06 = run(upstream_command("F06", "evidence/F06_UPSTREAM_TESTS.txt"), stage, stage / "evidence" / "F06_UPSTREAM_OUTPUT.txt")
    gate_value = json.loads((stage / "evidence" / "GATE_RESULT.json").read_text(encoding="utf-8"))
    if gate_value["status"] != "PASS" or gate_value["a10_b11_full_site_integration"] != "NOT_RUN_INPUT_NOT_CENTRALLY_ACKNOWLEDGED":
        raise RuntimeError("D09_GATE_EXPECTATION_FAILURE")
    audit = audit_stage(stage)
    (stage / "evidence" / "PACKAGE_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stage / "evidence" / "BUILD_RESULT.json").write_text(json.dumps({"generated_at_utc": datetime.now(timezone.utc).isoformat(), "input": input_result, "targets": TARGETS, "suite": suite, "gate": gate, "b11_upstream": b11, "f06_upstream": f06, "audit": audit, "restrictions": gate_value["restrictions"]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not audit["passed"]:
        raise RuntimeError(f"PACKAGE_AUDIT_FAILURE:{audit}")
    records = collect(stage)
    manifest = {"schema": "CDH-D09-R08-REVIEW-MANIFEST-1", "task_id": TASK_ID, "release": RELEASE_NAME, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "input_bundle_sha256": INPUT_SHA256, "input_manifest_sha256": INPUT_MANIFEST_SHA256, "target_release_sha256": TARGETS, "payload_count": len(records), "payloads": records, "status": "READY_FOR_REVIEW", "a10_b11_full_site_integration": "NOT_RUN_INPUT_NOT_CENTRALLY_ACKNOWLEDGED"}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda value: value.as_posix().casefold()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")
    verification = verify_review_target(release, sha256_file(release)).as_dict()
    queue.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(release, queue)
    if sha256_file(queue) != sha256_file(release) or queue.read_bytes() != release.read_bytes():
        raise RuntimeError("QUEUE_COPY_IDENTITY_FAILURE")
    post = work / f"post_extract_{sha256_file(release)[:8]}"
    if post.exists():
        raise FileExistsError(f"REFUSING_TO_OVERWRITE:{post}")
    with zipfile.ZipFile(release) as archive:
        archive.extractall(post)
    extracted = post / RELEASE_NAME
    post_suite = run([sys.executable, "-m", "unittest", "discover", "-s", "tests/web/security_d09", "-t", ".", "-v"], extracted, work / "POST_EXTRACT_D09_TESTS.txt")
    post_gate = run(gate_command(), extracted, work / "POST_EXTRACT_GATE.txt")
    post_b11 = run(upstream_command("B11", "review/D09/001/B11_UPSTREAM_TESTS.txt"), extracted, work / "POST_EXTRACT_B11.txt")
    post_f06 = run(upstream_command("F06", "review/D09/001/F06_UPSTREAM_TESTS.txt"), extracted, work / "POST_EXTRACT_F06.txt")
    result = {"release": str(release), "queue_copy": str(queue), "release_sha256": sha256_file(release), "queue_sha256": sha256_file(queue), "same_byte_copy": True, "manifest_sha256": sha256_file(stage / "MANIFEST.json"), "verification": verification, "input": input_result, "staged": {"suite": suite, "gate": gate, "b11": b11, "f06": f06}, "post_extract": {"suite": post_suite, "gate": post_gate, "b11": post_b11, "f06": post_f06}}
    (work / "RELEASE_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--r08-bundle", type=Path, required=True)
    parser.add_argument("--r07-bundle", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.r08_bundle.resolve(), args.r07_bundle.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
