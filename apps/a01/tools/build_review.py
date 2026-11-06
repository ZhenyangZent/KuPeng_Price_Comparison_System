from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = ROOT / "review/A01/001"
STAGING = TASK_ROOT / "package"
VERIFY_ROOT = TASK_ROOT / "verification"
ZIP_PATH = ROOT / "review/releases/CDH_A01_001_REVIEW.zip"
BASELINE_PATH = TASK_ROOT / "evidence/before/PROTECTED_SCOPE_BEFORE.json"
AFTER_PATH = TASK_ROOT / "evidence/after/PROTECTED_SCOPE_AFTER.json"
CSV_PATH = ROOT / "reports/A01/PROTECTED_SCOPE_HASHES_BEFORE_AFTER.csv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_relative(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and name not in {"", "."} and all(part not in {"", ".", ".."} for part in path.parts)


def protected_gate() -> dict[str, object]:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    missing: list[str] = []
    rows: list[dict[str, object]] = []
    after_files: dict[str, object] = {}
    for relative, expected in baseline["files"].items():
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
            rows.append({"path": relative, "before_sha256": expected["sha256"], "after_sha256": "MISSING", "before_bytes": expected["bytes"], "after_bytes": "", "gate": "FAIL"})
            continue
        actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        after_files[relative] = actual
        gate = "PASS" if actual == expected else "FAIL"
        if gate == "FAIL":
            mismatches.append(relative)
        rows.append({"path": relative, "before_sha256": expected["sha256"], "after_sha256": actual["sha256"], "before_bytes": expected["bytes"], "after_bytes": actual["bytes"], "gate": gate})
    new_files: list[str] = []
    baseline_names = set(baseline["files"])
    for relative_root in baseline["protected_roots"]:
        folder = ROOT / relative_root
        if folder.exists():
            for path in folder.rglob("*"):
                relative = path.relative_to(ROOT)
                if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                if path.is_file() and relative.as_posix() not in baseline_names:
                    new_files.append(relative.as_posix())
    result = {
        "task_id": "CDH-A01-WINDOWS-PREVIEW-001",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "before_file_count": baseline["file_count"],
        "verified_file_count": len(after_files),
        "missing": sorted(missing),
        "mismatch": sorted(mismatches),
        "new_files_in_protected_roots": sorted(new_files),
        "gate": "PASS" if not missing and not mismatches and not new_files else "FAIL",
        "files": after_files,
    }
    AFTER_PATH.parent.mkdir(parents=True, exist_ok=True)
    AFTER_PATH.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with CSV_PATH.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "before_sha256", "after_sha256", "before_bytes", "after_bytes", "gate"])
        writer.writeheader(); writer.writerows(rows)
    if result["gate"] != "PASS":
        raise RuntimeError(f"protected scope changed: missing={len(missing)} mismatch={len(mismatches)} new={len(new_files)}")
    return result


def copy_tree(source: Path, target: Path, *, excluded: set[str] | None = None) -> None:
    excluded = excluded or set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in excluded or part == "__pycache__" or part.endswith(".egg-info") for part in relative.parts):
            continue
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def collect_payload() -> None:
    if STAGING.exists() or VERIFY_ROOT.exists() or ZIP_PATH.exists():
        raise RuntimeError("refusing to overwrite an existing A01 package, verification directory, or release ZIP")
    STAGING.mkdir(parents=True)
    copy_tree(ROOT / "apps/a01", STAGING / "apps/a01", excluded={".venv", ".downloads", "local_state"})
    copy_tree(ROOT / "tests/a01", STAGING / "tests/a01")
    copy_tree(ROOT / "docs/A01", STAGING / "docs/A01")
    copy_tree(ROOT / "reports/A01", STAGING / "reports/A01")
    copy_tree(TASK_ROOT / "evidence", STAGING / "review/A01/001/evidence")
    prior_verification = TASK_ROOT / "ZIP_VERIFICATION.json"
    if prior_verification.is_file():
        destination = STAGING / "review/A01/001/PREFLIGHT_ZIP_VERIFICATION.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prior_verification, destination)
    prior_post_extract = TASK_ROOT / "POST_EXTRACT_TEST_RESULTS.txt"
    if prior_post_extract.is_file():
        destination = STAGING / "review/A01/001/PREFLIGHT_POST_EXTRACT_TEST_RESULTS.txt"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(prior_post_extract, destination)
    inputs = ROOT / "input/orchestrator_bundles/A01/extracted"
    selected = ["01_CODEX_TASK.md", "02_AUTHORITY_AND_PARALLEL_SCOPE.md", "03_FROZEN_SHARED_EXCHANGE_CONTRACT_V1.md", "06_README_FOR_USER.md", "10_SYNTHETIC_SUBMISSION_FIXTURE.json", "11_SYNTHETIC_SNAPSHOT_FIXTURE.json", "MANIFEST.json", "SHA256SUMS.txt"]
    for name in selected:
        destination = STAGING / "input_contract" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inputs / name, destination)
    (STAGING / "RUN_TESTS.ps1").write_text(
        "$ErrorActionPreference='Stop'\n"
        "$env:QT_QPA_PLATFORM='offscreen'\n"
        "python -m unittest discover -s tests/a01 -v\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8",
    )


def build_manifests() -> tuple[int, str]:
    payloads = []
    for path in sorted(STAGING.rglob("*")):
        if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS.txt"}:
            payloads.append({"path": path.relative_to(STAGING).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "task_id": "CDH-A01-WINDOWS-PREVIEW-001",
        "authority": "AUTHORIZED_OFFLINE_WINDOWS_PREVIEW_ONLY",
        "payload_count": len(payloads),
        "payloads": payloads,
        "excluded": ["apps/a01/.venv", "apps/a01/.downloads", "apps/a01/local_state", "__pycache__", "Cookie", "Token"],
    }
    manifest_path = STAGING / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    sums = "".join(f"{item['sha256']}  {item['path']}\n" for item in payloads)
    (STAGING / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    return len(payloads), sha256(manifest_path)


def write_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())


def verify_zip() -> dict[str, object]:
    VERIFY_ROOT.mkdir(parents=True)
    unsafe: list[str] = []
    case_names: set[str] = set()
    duplicates: list[str] = []
    symlinks: list[str] = []
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        for info in archive.infolist():
            if not safe_relative(info.filename): unsafe.append(info.filename)
            folded = info.filename.casefold()
            if folded in case_names: duplicates.append(info.filename)
            case_names.add(folded)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode): symlinks.append(info.filename)
        if bad_crc or unsafe or duplicates or symlinks:
            raise RuntimeError(f"unsafe ZIP: crc={bad_crc} unsafe={unsafe} duplicates={duplicates} symlinks={symlinks}")
        archive.extractall(VERIFY_ROOT)
    manifest = json.loads((VERIFY_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    declared = {item["path"]: item for item in manifest["payloads"]}
    actual_payloads = {path.relative_to(VERIFY_ROOT).as_posix() for path in VERIFY_ROOT.rglob("*") if path.is_file() and path.name not in {"MANIFEST.json", "SHA256SUMS.txt"}}
    missing = sorted(set(declared) - actual_payloads)
    undeclared = sorted(actual_payloads - set(declared))
    mismatch = sorted(name for name, item in declared.items() if name in actual_payloads and (sha256(VERIFY_ROOT / name) != item["sha256"] or (VERIFY_ROOT / name).stat().st_size != item["bytes"]))
    sums = {}
    for line in (VERIFY_ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1); sums[name] = digest
    sums_mismatch = sorted(name for name, item in declared.items() if sums.get(name) != item["sha256"])
    if missing or undeclared or mismatch or sums_mismatch:
        raise RuntimeError(f"manifest failure: missing={missing} undeclared={undeclared} mismatch={mismatch} sums={sums_mismatch}")
    return {
        "zip": str(ZIP_PATH), "zip_bytes": ZIP_PATH.stat().st_size, "zip_sha256": sha256(ZIP_PATH),
        "entry_count": len(actual_payloads) + 2, "payload_count": len(declared), "crc": "PASS", "safe_paths": "PASS",
        "case_collision": "PASS", "symlink": "PASS", "missing": 0, "mismatch": 0, "undeclared": 0, "duplicates": 0,
        "manifest_sha256": sha256(VERIFY_ROOT / "MANIFEST.json"), "gate": "PASS",
    }


def main() -> int:
    protected = protected_gate()
    collect_payload()
    payload_count, manifest_sha = build_manifests()
    write_zip()
    verified = verify_zip()
    verified["protected_scope_gate"] = protected["gate"]
    verified["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result_path = TASK_ROOT / "ZIP_VERIFICATION.json"
    result_path.write_text(json.dumps(verified, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"payload_count": payload_count, "manifest_sha256": manifest_sha, **verified}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
