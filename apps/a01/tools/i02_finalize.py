from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "CDH-I02-LOCAL-SYNC-PREVIEW-001"
EXPECTED_INPUT_SHA256 = "949a8ab399656d956d19ff8ce035f063477108c83e937b03915edcb649056dcb"
REVIEW = ROOT / "review/I02/001"
STAGING = REVIEW / "package"
RELEASE = ROOT / "review/releases/CDH_I02_001_REVIEW.zip"
BASELINE = REVIEW / "evidence/before/PROTECTED_SCOPE_BEFORE.json"
A01_BASELINE = REVIEW / "evidence/before/A01_SOURCE_BEFORE.json"
INPUT_DIR = ROOT / "input/orchestrator_bundles/I02"
EXTRACTED = INPUT_DIR / "extracted"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def file_record(path: Path) -> dict[str, object]:
    return {"bytes": path.stat().st_size, "sha256": sha256(path)}


def safe_reset(path: Path, parent: Path) -> None:
    resolved = path.resolve()
    parent_resolved = parent.resolve()
    if resolved == parent_resolved or parent_resolved not in resolved.parents:
        raise RuntimeError(f"unsafe reset target: {resolved}")
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)


def compare_baseline() -> dict[str, object]:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    expected: dict[str, dict[str, object]] = baseline["files"]
    missing: list[str] = []
    mismatch: list[str] = []
    for relative, record in expected.items():
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
        elif file_record(path) != record:
            mismatch.append(relative)

    current_paths: set[str] = set()
    for relative_root in baseline["protected_roots"]:
        folder = ROOT / relative_root
        if folder.exists():
            current_paths.update(
                path.relative_to(ROOT).as_posix()
                for path in folder.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
            )
    releases = ROOT / "review/releases"
    current_paths.update(
        path.relative_to(ROOT).as_posix()
        for path in releases.glob("*.zip")
        if path.name != RELEASE.name
    )
    unexpected = sorted(current_paths - set(expected))
    result = {
        "task_id": TASK_ID,
        "observed_at_utc": utc_now(),
        "baseline_file_count": len(expected),
        "current_file_count_excluding_i02_release": len(current_paths),
        "missing": missing,
        "mismatch": mismatch,
        "unexpected": unexpected,
        "result": "PASS" if not missing and not mismatch and not unexpected else "FAIL",
    }
    write_json(REVIEW / "evidence/after/PROTECTED_SCOPE_COMPARISON.json", result)
    if result["result"] != "PASS":
        raise RuntimeError(f"protected-scope gate failed: {result}")
    return result


def compare_a01() -> dict[str, object]:
    baseline = json.loads(A01_BASELINE.read_text(encoding="utf-8"))["files"]
    ignored = {".venv", ".downloads", "__pycache__", ".pytest_cache", "local_state"}
    current: dict[str, dict[str, object]] = {}
    for path in (ROOT / "apps/a01").rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in ignored for part in relative.parts) or path.suffix == ".pyc":
            continue
        current[relative.as_posix()] = file_record(path)
    added = sorted(set(current) - set(baseline))
    removed = sorted(set(baseline) - set(current))
    changed = sorted(path for path in set(current) & set(baseline) if current[path] != baseline[path])
    unchanged = sorted(set(current) & set(baseline) - set(changed))
    result = {
        "task_id": TASK_ID,
        "observed_at_utc": utc_now(),
        "added": added,
        "changed": changed,
        "removed": removed,
        "unchanged_count": len(unchanged),
        "result": "PASS" if not removed else "FAIL",
    }
    write_json(REVIEW / "evidence/after/A01_SOURCE_COMPARISON.json", result)
    report = ROOT / "reports/I02/CHANGE_MANIFEST.csv"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["change", "path", "sha256", "bytes"])
        for change, paths in (("ADDED", added), ("CHANGED", changed)):
            for relative in paths:
                writer.writerow([change, relative, current[relative]["sha256"], current[relative]["bytes"]])
    if removed:
        raise RuntimeError(f"A01 source files removed: {removed}")
    return result


def validate_input_and_history() -> dict[str, object]:
    input_zip = INPUT_DIR / "CDH_I02_001_INPUT_BUNDLE.zip"
    history = {
        "review/releases/CDH_A02_R01_REVIEW.zip": "40bb17a7a0aa8015473c3231c2dd215f3b8149558212f07f3a7802319e514fe4",
        "review/releases/CDH_D02_001_REVIEW.zip": "1931bc7da435f55154190925e046bf684427347f06d987fa4594d769ce765886",
        "review/releases/CDH_C01_R04_REVIEW.zip": "cce874a926acf06986e456bdac7e1a93e90611b696ab7917c7bb5cd56e8cdf00",
    }
    history_results = {}
    for relative, expected in history.items():
        path = ROOT / relative
        actual = sha256(path) if path.is_file() else None
        history_results[relative] = {"expected": expected, "actual": actual, "match": actual == expected}
    result = {
        "task_id": TASK_ID,
        "observed_at_utc": utc_now(),
        "input_path": str(input_zip),
        "input_bytes": input_zip.stat().st_size,
        "input_expected_sha256": EXPECTED_INPUT_SHA256,
        "input_actual_sha256": sha256(input_zip),
        "history": history_results,
    }
    result["result"] = "PASS" if result["input_actual_sha256"] == EXPECTED_INPUT_SHA256 and all(
        row["match"] for row in history_results.values()
    ) else "FAIL"
    write_json(REVIEW / "evidence/after/INPUT_AND_HISTORY_VALIDATION.json", result)
    if result["result"] != "PASS":
        raise RuntimeError(f"input/history identity failed: {result}")
    return result


def verify_frozen_d02() -> dict[str, object]:
    archive = EXTRACTED / "05_CDHD02_FROZEN_BASELINE.zip"
    prefix = "CDH_D02_001_REVIEW/apps/d01/"
    archive_files: dict[str, dict[str, object]] = {}
    with zipfile.ZipFile(archive) as source:
        source.testzip()
        for info in source.infolist():
            if info.is_dir() or not info.filename.startswith(prefix):
                continue
            relative = info.filename[len(prefix):]
            data = source.read(info)
            archive_files[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    current_files = {
        path.relative_to(ROOT / "apps/d01").as_posix(): file_record(path)
        for path in (ROOT / "apps/d01").rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    missing = sorted(set(archive_files) - set(current_files))
    extra = sorted(set(current_files) - set(archive_files))
    mismatch = sorted(path for path in set(archive_files) & set(current_files) if archive_files[path] != current_files[path])
    result = {
        "task_id": TASK_ID,
        "observed_at_utc": utc_now(),
        "frozen_archive": str(archive),
        "frozen_archive_sha256": sha256(archive),
        "file_count": len(archive_files),
        "missing": missing,
        "extra": extra,
        "mismatch": mismatch,
        "result": "PASS" if not missing and not extra and not mismatch else "FAIL",
    }
    write_json(REVIEW / "evidence/after/FROZEN_D02_IDENTITY.json", result)
    if result["result"] != "PASS":
        raise RuntimeError(f"frozen D02 identity failed: {result}")
    return result


def prepare() -> None:
    compare_baseline()
    compare_a01()
    validate_input_and_history()
    verify_frozen_d02()
    print("PREPARE_PASS")


def copy_tree(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in {".venv", ".downloads", "__pycache__", ".pytest_cache", "local_state"} or name.endswith(".pyc")}
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def copy_payload() -> None:
    safe_reset(STAGING, REVIEW)
    for relative in ("apps/a01", "apps/d01", "scripts/d02", "tests/a01", "tests/a02", "tests/i02", "tests/d01", "tests/d02", "docs/I02", "docs/D02", "reports/I02"):
        copy_tree(ROOT / relative, STAGING / relative)
    for relative in ("review/I02/001/evidence", "experiments/I02/windows_gui_evidence", "experiments/I02/recovery_evidence"):
        copy_tree(ROOT / relative, STAGING / relative)
    contract = STAGING / "input_contract"
    contract.mkdir()
    for name in ("00_START_HERE.md", "01_ORCHESTRATOR_REVIEW.md", "02_RECEIPT_CONTRACT_V1.md", "03_INDEPENDENT_CROSSLINE_12_CASES.py", "MANIFEST.json", "SHA256SUMS.txt", "05_CDHD02_FROZEN_BASELINE.zip"):
        shutil.copy2(EXTRACTED / name, contract / name)
    fixture = ROOT / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
    shutil.copy2(fixture, contract / fixture.name)
    (STAGING / "README_REVIEW.md").write_text(
        "# CDH I02 Review\n\n"
        "Offline synthetic preview only. `apps/d01` is an unchanged frozen dependency included for reproducible review. "
        "Run `RUN_TESTS.ps1` from this extracted directory using the project A01 Python environment. "
        "No production database, network, Firefox, Registry, real notification, or shopping action is authorized.\n",
        encoding="utf-8",
    )
    (STAGING / "RUN_TESTS.ps1").write_text(
        "param([string]$Python = '..\\..\\apps\\a01\\.venv\\python.exe')\n"
        "$ErrorActionPreference = 'Stop'\n"
        "$root = (Resolve-Path $PSScriptRoot).Path\n"
        "$env:PYTHONPATH = \"$root\\apps\\a01;$root\\apps\\d01\"\n"
        "$tmp = Join-Path $root 'test_tmp'\n"
        "New-Item -ItemType Directory -Force $tmp | Out-Null\n"
        "$env:TEMP = $tmp; $env:TMP = $tmp; $env:CDH_PROJECT_ROOT = $root; $env:CDH_TEST_TMP_ROOT = $tmp\n"
        "foreach ($suite in @('a01','a02','i02','d01','d02')) { & $Python -m unittest discover -s (Join-Path $root \"tests/$suite\") -p 'test_*.py' -v; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }\n"
        "& $Python (Join-Path $root 'input_contract/03_INDEPENDENT_CROSSLINE_12_CASES.py')\n"
        "exit $LASTEXITCODE\n",
        encoding="utf-8-sig",
    )


def payload_manifest() -> dict[str, object]:
    files = {}
    for path in sorted(STAGING.rglob("*")):
        relative = path.relative_to(STAGING).as_posix()
        if not path.is_file() or relative in {"MANIFEST.json", "SHA256SUMS.txt"}:
            continue
        files[relative] = file_record(path)
    return {"task_id": TASK_ID, "generated_at_utc": utc_now(), "algorithm": "SHA-256", "file_count": len(files), "files": files}


def write_manifest() -> dict[str, object]:
    manifest = payload_manifest()
    write_json(STAGING / "MANIFEST.json", manifest)
    lines = [f"{manifest['files'][relative]['sha256']}  {relative}" for relative in sorted(manifest["files"])]
    (STAGING / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def write_zip(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())


def inspect_zip(path: Path, extract_to: Path | None = None) -> dict[str, object]:
    unsafe: list[str] = []
    case_collisions: list[str] = []
    symlinks: list[str] = []
    seen: dict[str, str] = {}
    with zipfile.ZipFile(path) as archive:
        bad_crc = archive.testzip()
        names = []
        for info in archive.infolist():
            name = info.filename
            names.append(name)
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or ":" in name or "\\" in name:
                unsafe.append(name)
            folded = name.casefold()
            if folded in seen and seen[folded] != name:
                case_collisions.append(f"{seen[folded]} :: {name}")
            seen[folded] = name
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                symlinks.append(name)
        manifest = json.loads(archive.read("MANIFEST.json"))
        sums = archive.read("SHA256SUMS.txt").decode("utf-8").splitlines()
        declared = manifest["files"]
        actual_payloads = {name for name in names if not name.endswith("/") and name not in {"MANIFEST.json", "SHA256SUMS.txt"}}
        missing = sorted(set(declared) - actual_payloads)
        undeclared = sorted(actual_payloads - set(declared))
        mismatch = []
        for name, record in declared.items():
            if name in actual_payloads:
                data = archive.read(name)
                if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
                    mismatch.append(name)
        expected_sums = [f"{declared[name]['sha256']}  {name}" for name in sorted(declared)]
        sums_match = sums == expected_sums
        if extract_to is not None:
            safe_reset(extract_to, extract_to.parent)
            archive.extractall(extract_to)
    result = {
        "task_id": TASK_ID,
        "observed_at_utc": utc_now(),
        "zip_path": str(path),
        "zip_bytes": path.stat().st_size,
        "zip_sha256": sha256(path),
        "zip_entry_count": len(names),
        "payload_count": len(manifest["files"]),
        "manifest_sha256": sha256(STAGING / "MANIFEST.json") if (STAGING / "MANIFEST.json").is_file() else None,
        "crc": "PASS" if bad_crc is None else f"FAIL:{bad_crc}",
        "unsafe_paths": unsafe,
        "case_collisions": case_collisions,
        "symlinks": symlinks,
        "missing": missing,
        "undeclared": undeclared,
        "mismatch": mismatch,
        "sha256sums_match": sums_match,
    }
    result["result"] = "PASS" if bad_crc is None and not unsafe and not case_collisions and not symlinks and not missing and not undeclared and not mismatch and sums_match else "FAIL"
    return result


def build() -> None:
    copy_payload()
    write_manifest()
    preflight_zip = REVIEW / "preflight.zip"
    write_zip(preflight_zip)
    preflight = inspect_zip(preflight_zip, REVIEW / "preflight_extract")
    write_json(STAGING / "ARCHIVE_PREFLIGHT.json", preflight)
    preflight_zip.unlink()
    shutil.rmtree(REVIEW / "preflight_extract")
    write_manifest()
    write_zip(RELEASE)
    result = inspect_zip(RELEASE, REVIEW / "verification")
    write_json(REVIEW / "FINAL_ZIP_VERIFICATION.json", result)
    if result["result"] != "PASS":
        raise RuntimeError(f"final ZIP verification failed: {result}")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


def verify() -> None:
    result = inspect_zip(RELEASE, REVIEW / "verification")
    write_json(REVIEW / "FINAL_ZIP_VERIFICATION.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["result"] != "PASS":
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "build", "verify"))
    args = parser.parse_args()
    {"prepare": prepare, "build": build, "verify": verify}[args.mode]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
