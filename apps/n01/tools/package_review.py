from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


RELEASE_NAME = "CDH_N01_001_REVIEW"
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return bool(normalized) and not normalized.startswith("/") and not path.is_absolute() and ".." not in path.parts and not (len(normalized) >= 2 and normalized[1] == ":")


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(
        source,
        target,
        ignore=lambda _path, names: [
            name
            for name in names
            if name in SKIP_PARTS or name.endswith((".pyc", ".pyo"))
        ],
    )


def extract_input_contract(bundle: Path, target: Path) -> dict[str, Any]:
    bundle_bytes = bundle.read_bytes()
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        lowered = [name.replace("\\", "/").lower() for name in names]
        if any(not safe_member(name) for name in names):
            raise ValueError("input bundle contains unsafe path")
        if len(lowered) != len(set(lowered)):
            raise ValueError("input bundle contains duplicate path")
        bad_crc = archive.testzip()
        if bad_crc is not None:
            raise ValueError(f"input bundle CRC failure: {bad_crc}")
        manifest = json.loads(archive.read("INPUT_MANIFEST.json"))
        mismatches = []
        for item in manifest["payloads"]:
            raw = archive.read(item["path"])
            if len(raw) != item["bytes"] or sha256_bytes(raw) != item["sha256"]:
                mismatches.append(item["path"])
        if mismatches:
            raise ValueError(f"input bundle manifest mismatch: {mismatches}")
        target.mkdir(parents=True)
        for name in names:
            if name.endswith("/"):
                continue
            destination = target / PurePosixPath(name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(name))
    return {
        "path": str(bundle),
        "sha256": sha256_bytes(bundle_bytes),
        "zip_entries": len(names),
        "manifest_payloads": len(manifest["payloads"]),
        "manifest_mismatches": 0,
        "crc": "PASS",
        "safe_paths": "PASS",
    }


def run_staged_tests(stage: Path) -> dict[str, Any]:
    temp_root = stage / "experiments" / "N01" / "test_tmp"
    temp_root.mkdir(parents=True)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(stage / "src"), str(stage / "apps" / "n01"), str(stage)]
    )
    env["TEMP"] = str(temp_root)
    env["TMP"] = str(temp_root)
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests/n01",
        "-p",
        "test_*.py",
        "-v",
    ]
    result = subprocess.run(command, cwd=stage, env=env, text=True, capture_output=True, check=False)
    evidence = stage / "evidence" / "POST_STAGE_TEST_RESULTS.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        "COMMAND: " + " ".join(command) + "\n"
        + f"EXIT_CODE: {result.returncode}\n"
        + "\nSTDOUT\n"
        + result.stdout
        + "\nSTDERR\n"
        + result.stderr,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"staged tests failed; see {evidence}")
    return {"command": command, "exit_code": result.returncode, "evidence": "evidence/POST_STAGE_TEST_RESULTS.txt"}


def payloads(stage: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.name in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        relative = path.relative_to(stage).as_posix()
        result.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return result


def build(root: Path, bundle: Path) -> dict[str, Any]:
    release = root / "review" / "releases" / f"{RELEASE_NAME}.zip"
    stage_parent = root / "review" / "N01" / "001" / "package"
    stage = stage_parent / RELEASE_NAME
    verification_path = root / "review" / "N01" / "001" / "RELEASE_VERIFICATION.json"
    if release.exists():
        raise FileExistsError(f"refusing to overwrite release: {release}")
    if stage.exists():
        raise FileExistsError(f"refusing to overwrite staging directory: {stage}")
    stage.mkdir(parents=True)

    for relative in ("apps/n01", "tests/n01", "docs/N01", "reports/N01"):
        copy_tree(root / relative, stage / relative)
    copy_tree(root / "src" / "cdh_core", stage / "src" / "cdh_core")
    copy_tree(root / "src" / "cdh_integration", stage / "src" / "cdh_integration")
    input_evidence = extract_input_contract(bundle, stage / "input_contract")

    (stage / "RUN_TESTS.ps1").write_text(
        "$ErrorActionPreference = 'Stop'\n"
        "New-Item -ItemType Directory -Force experiments/N01/test_tmp | Out-Null\n"
        "$env:PYTHONPATH = ((Resolve-Path 'src').Path + ';' + (Resolve-Path 'apps/n01').Path + ';' + (Resolve-Path '.').Path)\n"
        "$env:TEMP = (Resolve-Path 'experiments/N01/test_tmp').Path\n"
        "$env:TMP = $env:TEMP\n"
        "python -m unittest discover -s tests/n01 -p 'test_*.py' -v\n",
        encoding="utf-8",
    )
    (stage / "README_REVIEW.md").write_text(
        "# CDH N01 001 review\n\n"
        "Offline-only synthetic notification outbox. Run `RUN_TESTS.ps1` from this directory. "
        "No real notification, network source, Firefox profile, Registry, coupon claim, cart, checkout, order, or payment capability is included.\n",
        encoding="utf-8",
    )
    test_evidence = run_staged_tests(stage)
    environment = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": sys.platform,
        "input_bundle": input_evidence,
        "staged_test": test_evidence,
        "real_notification_count": 0,
        "network_send_count": 0,
        "registry_access_count": 0,
        "firefox_profile_access_count": 0,
    }
    (stage / "evidence" / "PACKAGING_ENVIRONMENT.json").write_text(
        json.dumps(environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    files = payloads(stage)
    manifest = {
        "contract": "CDH-N01-REVIEW-MANIFEST-1",
        "release": RELEASE_NAME,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_bundle_sha256": input_evidence["sha256"],
        "payload_count": len(files),
        "payloads": files,
        "safety": {
            "offline_synthetic_only": True,
            "real_notification_enabled": False,
            "external_exactly_once_claimed": False,
        },
    }
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (stage / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in files), encoding="utf-8"
    )

    release.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(release, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*"), key=lambda item: item.as_posix().lower()):
            if path.is_file():
                archive.write(path, f"{RELEASE_NAME}/{path.relative_to(stage).as_posix()}")

    with zipfile.ZipFile(release) as archive:
        names = archive.namelist()
        lower_names = [name.lower() for name in names]
        bad_crc = archive.testzip()
        unsafe = [name for name in names if not safe_member(name)]
        duplicate_count = len(lower_names) - len(set(lower_names))
        archived_manifest = json.loads(archive.read(f"{RELEASE_NAME}/MANIFEST.json"))
        mismatches = []
        declared = {item["path"]: item for item in archived_manifest["payloads"]}
        for relative, item in declared.items():
            raw = archive.read(f"{RELEASE_NAME}/{relative}")
            if len(raw) != item["bytes"] or sha256_bytes(raw) != item["sha256"]:
                mismatches.append(relative)
        actual_payloads = {
            name.removeprefix(f"{RELEASE_NAME}/")
            for name in names
            if not name.endswith("/")
            and name not in {f"{RELEASE_NAME}/MANIFEST.json", f"{RELEASE_NAME}/SHA256SUMS.txt"}
        }
        undeclared = sorted(actual_payloads - set(declared))
        missing = sorted(set(declared) - actual_payloads)
    verification = {
        "release": str(release),
        "release_sha256": sha256_file(release),
        "release_bytes": release.stat().st_size,
        "zip_entries": len(names),
        "crc_pass": bad_crc is None,
        "safe_path_pass": not unsafe,
        "casefold_duplicate_count": duplicate_count,
        "manifest_payload_count": len(declared),
        "manifest_mismatch_count": len(mismatches),
        "manifest_missing_count": len(missing),
        "manifest_undeclared_count": len(undeclared),
        "mismatches": mismatches,
        "missing": missing,
        "undeclared": undeclared,
    }
    verification_path.parent.mkdir(parents=True, exist_ok=True)
    verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not (
        verification["crc_pass"]
        and verification["safe_path_pass"]
        and duplicate_count == 0
        and not mismatches
        and not missing
        and not undeclared
    ):
        raise RuntimeError(f"release verification failed: {verification}")
    return verification


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--input-bundle", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve(), args.input_bundle.resolve()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
