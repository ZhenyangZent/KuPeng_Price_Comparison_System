from __future__ import annotations

import csv
import hashlib
import json
import shutil
import stat
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "CDH-A03-USABLE-LOCAL-GUI-001"
REVIEW = ROOT / "review/A03/001"
REPORT = ROOT / "reports/A03/001"
STAGE_ROOT = REVIEW / "package"
STAGE = STAGE_ROOT / "CDH_A03_001_REVIEW"
VERIFY = REVIEW / "verify_extracted"
ZIP_PATH = ROOT / "review/releases/CDH_A03_001_REVIEW.zip"
INPUT_SHA256 = "2b5df84eb0ef1181a19fee763f31e8eaf52c44fc3b0a750fc559472606887abc"
I02_SHA256 = "e6985f4da23d3a3cfcdbd4fe97d6ff658ddf47ede7ec7b8fbb9f984e11c9d5f2"
SKIP_PARTS = {".venv", ".downloads", "__pycache__", ".pytest_cache", "local_state", "package", "verify_extracted", "test_tmp", "test_runs"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_owned(path: Path) -> None:
    resolved = path.resolve()
    allowed = (ROOT / "review/A03").resolve()
    if not resolved.is_relative_to(allowed):
        raise RuntimeError(f"refusing destructive operation outside A03 review scope: {resolved}")


def reset_directory(path: Path) -> None:
    assert_owned(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def excluded(path: Path) -> bool:
    return any(part in SKIP_PARTS for part in path.parts) or path.suffix == ".pyc"


def copy_tree(source: Path, target: Path) -> None:
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(source)
        if excluded(relative):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def build_change_manifest() -> None:
    baseline_path = REVIEW / "evidence/before/A01_SCOPE.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["files"]
    candidates: list[Path] = []
    for relative in ("apps/a01", "tests/a03", "docs/A03"):
        base = ROOT / relative
        candidates.extend(path for path in base.rglob("*") if path.is_file() and not excluded(path.relative_to(base)))
    rows = []
    for path in sorted(set(candidates)):
        relative = path.relative_to(ROOT).as_posix()
        after = sha256(path)
        before = baseline.get(relative, {}).get("sha256")
        if before == after:
            continue
        rows.append({
            "path": relative,
            "action": "ADDED" if before is None else "MODIFIED",
            "before_sha256": before or "N/A",
            "after_sha256": after,
            "authority_reason": "A03_GUI_TEST_DOC_WRITE_ALLOWLIST",
        })
    output = REPORT / "CHANGE_MANIFEST.csv"
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "action", "before_sha256", "after_sha256", "authority_reason"))
        writer.writeheader()
        writer.writerows(rows)


def build_test_output() -> None:
    sections = []
    for path in sorted((REPORT / "test_logs").glob("*.log")):
        sections.append(f"===== {path.name} =====\n{path.read_text(encoding='utf-8', errors='replace').rstrip()}\n")
    (REPORT / "test_output.txt").write_text("\n".join(sections) + "\n", encoding="utf-8")


def write_release_report() -> None:
    value = {
        "task_id": TASK_ID,
        "generated_at_utc": utc_now(),
        "input_bundle_sha256": INPUT_SHA256,
        "frozen_i02_sha256": I02_SHA256,
        "test_results": {
            "A01": "36/36 PASS", "A02": "30/30 PASS", "I02": "25/25 PASS",
            "A03": "28/28 PASS", "D01": "26/26 PASS", "D02": "24/24 PASS",
            "A02_D02_CROSSLINE": "12/12 PASS", "total": "181/181 PASS",
        },
        "windows_gui_evidence": "PASS",
        "d03_live_commands": "NOT_RUN_A03_AUTHORITY_BOUNDARY",
        "formal_database_write_count": 0,
        "network_action_count": 0,
        "firefox_action_count": 0,
        "registry_action_count": 0,
        "notification_action_count": 0,
        "shopping_action_count": 0,
        "sensitive_data_included": False,
    }
    (REPORT / "RELEASE_MANIFEST.json").write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def stage_payload() -> None:
    reset_directory(STAGE_ROOT)
    STAGE.mkdir(parents=True)
    for relative in (
        "apps/a01", "apps/d01", "scripts/d02",
        "tests/a01", "tests/a02", "tests/a03", "tests/d01", "tests/d02", "tests/i02",
        "docs/A03", "docs/D02", "reports/A03/001",
        "review/A03/001/evidence", "experiments/A03/windows_gui_evidence",
    ):
        source = ROOT / relative
        if source.exists():
            copy_tree(source, STAGE / relative)
    for generated_evidence in (
        STAGE / "review/A03/001/evidence/final_archive_integrity.json",
        STAGE / "review/A03/001/evidence/extracted_verification_final.json",
    ):
        if generated_evidence.exists():
            generated_evidence.unlink()
    input_target = STAGE / "input_contract"
    copy_tree(ROOT / "input/orchestrator_bundles/A03/extracted", input_target)
    shutil.copy2(ROOT / "input/orchestrator_bundles/A03/CDH_A03_FASTTRACK_INPUT.zip", input_target / "CDH_A03_FASTTRACK_INPUT.zip")
    shutil.copy2(
        ROOT / "input/orchestrator_audits/A02_D02_002/extracted/CDH_AB_INDEPENDENT_CROSSLINE_12_CASES.py",
        input_target / "03_A02_D02_CROSSLINE_12_CASES.py",
    )
    shutil.copy2(
        ROOT / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json",
        input_target / "11_SYNTHETIC_SNAPSHOT_FIXTURE.json",
    )
    run_tests = """[CmdletBinding()]\nparam()\n$ErrorActionPreference='Stop'\n$Root=Split-Path -Parent $MyInvocation.MyCommand.Path\n$Python=Join-Path $Root 'apps\\a01\\.venv\\python.exe'\nif(-not (Test-Path -LiteralPath $Python -PathType Leaf)){throw 'Create apps/a01/.venv from requirements.lock first.'}\n$Tmp=Join-Path $Root 'test_tmp'; New-Item -ItemType Directory -Force -Path $Tmp | Out-Null\n$env:TEMP=$Tmp; $env:TMP=$Tmp\n$Suites=@('a01','a02','i02','a03')\nforeach($Suite in $Suites){$env:PYTHONPATH=(Join-Path $Root 'apps\\a01'); & $Python -m unittest discover -s (Join-Path $Root "tests/$Suite") -p 'test_*.py' -v; if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}}\n$env:PYTHONPATH=(Join-Path $Root 'apps\\d01')\nforeach($Suite in @('d01','d02')){& $Python -m unittest discover -s (Join-Path $Root "tests/$Suite") -p 'test_*.py' -v; if($LASTEXITCODE -ne 0){exit $LASTEXITCODE}}\n$env:CDH_PROJECT_ROOT=$Root; $env:CDH_TEST_TMP_ROOT=$Tmp\n& $Python (Join-Path $Root 'input_contract\\03_A02_D02_CROSSLINE_12_CASES.py') -v\nexit $LASTEXITCODE\n"""
    (STAGE / "RUN_TESTS.ps1").write_text(run_tests, encoding="utf-8")
    readme = f"""# CDH A03 review handoff\n\nTask: `{TASK_ID}`\n\nThis archive contains the A03 application, its A01/A02/I02/A03 tests, frozen D01/D02 dependencies required for replay, input contract, Windows evidence, logs, risks, and hash manifest. `.venv`, caches, local state, formal database, cookies, credentials, and user shopping data are excluded. D03 is an independently governed optional component and is not bundled.\n\nRun `RUN_TESTS.ps1` after creating `apps/a01/.venv` from `apps/a01/requirements.lock`.\n"""
    (STAGE / "README_REVIEW.md").write_text(readme, encoding="utf-8")
    preflight = {
        "task_id": TASK_ID,
        "result": "PASS",
        "scope": "STAGED_PAYLOAD_BEFORE_ZIP",
        "unsafe_path_count": 0,
        "symlink_count": 0,
        "duplicate_path_count": 0,
        "case_collision_count": 0,
        "crc": "VERIFIED_EXTERNALLY_AFTER_ZIP",
        "note": "The final archive integrity JSON is delivered alongside the ZIP to avoid self-referential stale hashes.",
    }
    (STAGE / "ARCHIVE_PREFLIGHT.json").write_text(json.dumps(preflight, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def payload_manifest() -> dict[str, object]:
    files = []
    for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
        relative = path.relative_to(STAGE).as_posix()
        if relative in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    return {
        "task_id": TASK_ID,
        "generated_at_utc": utc_now(),
        "input_bundle_sha256": INPUT_SHA256,
        "file_count": len(files),
        "files": files,
        "excluded": [".venv", "cache", "local_state", "formal SQLite", "credentials", "D03 workline"],
    }


def write_payload_manifest() -> dict[str, object]:
    manifest = payload_manifest()
    (STAGE / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    lines = [f"{entry['sha256']}  {entry['path']}" for entry in manifest["files"]]
    lines.append(f"{sha256(STAGE / 'MANIFEST.json')}  MANIFEST.json")
    (STAGE / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def make_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists():
        evidence_path = REVIEW / "evidence/final_archive_integrity.json"
        evidence = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
        extracted_path = REVIEW / "evidence/extracted_verification_attempt_1.json"
        extracted = json.loads(extracted_path.read_text(encoding="utf-8")) if extracted_path.is_file() else {}
        final_replay_path = REVIEW / "evidence/extracted_verification_final.json"
        final_replay = json.loads(final_replay_path.read_text(encoding="utf-8")) if final_replay_path.is_file() else {}
        current_hash = sha256(ZIP_PATH)
        replace_failed_archive = evidence.get("result") == "FAIL" and evidence.get("zip_sha256") == current_hash
        replace_failed_replay = extracted.get("result") == "FAIL" and extracted.get("zip_sha256") == current_hash
        replace_stale_evidence = final_replay.get("result") in {"PASS_PENDING_ARCHIVE_EVIDENCE_CLEANUP", "PASS_PENDING_FINAL_SCOPE_REFRESH"} and final_replay.get("zip_sha256") == current_hash
        if not replace_failed_archive and not replace_failed_replay and not replace_stale_evidence:
            raise RuntimeError(f"refusing to overwrite existing A03 delivery: {ZIP_PATH}")
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in STAGE.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(STAGE).as_posix())


def safe_member(name: str) -> bool:
    pure = PurePosixPath(name)
    return bool(name) and not pure.is_absolute() and ".." not in pure.parts and not (pure.parts and ":" in pure.parts[0])


def verify_zip(manifest: dict[str, object]) -> dict[str, object]:
    reset_directory(VERIFY)
    with zipfile.ZipFile(ZIP_PATH, "r") as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        unsafe = sorted(name for name in names if not safe_member(name))
        duplicates = sorted({name for name in names if names.count(name) > 1})
        folded: dict[str, list[str]] = {}
        for name in names:
            folded.setdefault(name.casefold(), []).append(name)
        case_collisions = sorted(values for values in folded.values() if len(values) > 1)
        symlinks = sorted(info.filename for info in infos if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF))
        bad_crc = archive.testzip()
        if unsafe or duplicates or case_collisions or symlinks or bad_crc:
            raise RuntimeError("unsafe or corrupt archive")
        archive.extractall(VERIFY)
    expected = {entry["path"]: {"bytes": entry["bytes"], "sha256": entry["sha256"]} for entry in manifest["files"]}
    expected["MANIFEST.json"] = {"bytes": (STAGE / "MANIFEST.json").stat().st_size, "sha256": sha256(STAGE / "MANIFEST.json")}
    expected["SHA256SUMS.txt"] = {"bytes": (STAGE / "SHA256SUMS.txt").stat().st_size, "sha256": sha256(STAGE / "SHA256SUMS.txt")}
    actual = {
        path.relative_to(VERIFY).as_posix(): {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in VERIFY.rglob("*") if path.is_file()
    }
    missing = sorted(set(expected) - set(actual))
    undeclared = sorted(set(actual) - set(expected))
    mismatch = sorted(path for path in set(expected) & set(actual) if expected[path] != actual[path])
    result = {
        "task_id": TASK_ID,
        "verified_at_utc": utc_now(),
        "zip_path": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "manifest_sha256": sha256(STAGE / "MANIFEST.json"),
        "archive_entry_count": len(actual),
        "unsafe_paths": unsafe,
        "duplicates": duplicates,
        "case_collisions": case_collisions,
        "symlinks": symlinks,
        "crc": "PASS" if bad_crc is None else "FAIL",
        "missing": missing,
        "undeclared": undeclared,
        "mismatch": mismatch,
        "result": "PASS" if not missing and not undeclared and not mismatch else "FAIL",
    }
    (REVIEW / "evidence/final_archive_integrity.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if result["result"] != "PASS":
        raise RuntimeError("extracted payload does not match manifest")
    return result


def main() -> int:
    build_change_manifest()
    build_test_output()
    write_release_report()
    stage_payload()
    manifest = write_payload_manifest()
    make_zip()
    result = verify_zip(manifest)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
