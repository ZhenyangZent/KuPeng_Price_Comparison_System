from __future__ import annotations

import csv
import hashlib
import json
import shutil
import stat
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[3]
TASK_ROOT = ROOT / "review/A02/001"
STAGING = TASK_ROOT / "package"
VERIFY_ROOT = TASK_ROOT / "verification"
ZIP_PATH = ROOT / "review/releases/CDH_A02_001_REVIEW.zip"
PROTECTED_BEFORE = TASK_ROOT / "evidence/before/PROTECTED_SCOPE_BEFORE.json"
A01_BEFORE = TASK_ROOT / "evidence/before/A01_SOURCE_BEFORE.json"
CONCURRENT_PREFIXES = ("apps/d01/", "tests/d01/", "reports/D01/", "review/D01/")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and name not in {"", "."} and all(part not in {"", ".", ".."} for part in path.parts)


def protected_gate() -> dict[str, object]:
    before = json.loads(PROTECTED_BEFORE.read_text(encoding="utf-8-sig"))
    missing: list[str] = []
    mismatch: list[str] = []
    rows: list[dict[str, object]] = []
    after_files: dict[str, object] = {}
    for relative, expected in before["files"].items():
        path = ROOT / relative
        if not path.is_file():
            missing.append(relative)
            rows.append({"path": relative, "before_sha256": expected["sha256"], "after_sha256": "MISSING", "before_bytes": expected["bytes"], "after_bytes": "", "gate": "FAIL"})
            continue
        actual = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        after_files[relative] = actual
        if actual == expected:
            gate = "PASS"
        elif relative.startswith(CONCURRENT_PREFIXES):
            gate = "CONCURRENT_EXTERNAL_CHANGE"
        else:
            gate = "FAIL"
        if gate == "FAIL": mismatch.append(relative)
        rows.append({"path": relative, "before_sha256": expected["sha256"], "after_sha256": actual["sha256"], "before_bytes": expected["bytes"], "after_bytes": actual["bytes"], "gate": gate})
    baseline_names = set(before["files"])
    new_files: list[str] = []
    for relative_root in before["protected_roots"]:
        folder = ROOT / relative_root
        if not folder.exists(): continue
        for path in folder.rglob("*"):
            relative = path.relative_to(ROOT)
            if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}: continue
            if path.is_file() and relative.as_posix() not in baseline_names:
                new_files.append(relative.as_posix())
    concurrent_changes = sorted(
        [name for name in mismatch if name.startswith(CONCURRENT_PREFIXES)]
        + [name for name in new_files if name.startswith(CONCURRENT_PREFIXES)]
        + [name for name in missing if name.startswith(CONCURRENT_PREFIXES)]
    )
    unauthorized_missing = sorted(name for name in missing if not name.startswith(CONCURRENT_PREFIXES))
    unauthorized_mismatch = sorted(name for name in mismatch if not name.startswith(CONCURRENT_PREFIXES))
    unauthorized_new = sorted(name for name in new_files if not name.startswith(CONCURRENT_PREFIXES))
    result = {
        "task_id": "CDH-A02-UI-STATUS-HANDOFF-001",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "before_file_count": before["file_count"], "verified_file_count": len(after_files),
        "missing": sorted(missing), "mismatch": sorted(mismatch), "new_files_in_protected_roots": sorted(new_files),
        "concurrent_external_changes": concurrent_changes,
        "unauthorized_missing": unauthorized_missing, "unauthorized_mismatch": unauthorized_mismatch, "unauthorized_new": unauthorized_new,
        "gate": "PASS" if not unauthorized_missing and not unauthorized_mismatch and not unauthorized_new else "FAIL", "files": after_files,
    }
    after_path = TASK_ROOT / "evidence/after/PROTECTED_SCOPE_AFTER.json"
    after_path.parent.mkdir(parents=True, exist_ok=True)
    after_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    csv_path = ROOT / "reports/A02/PROTECTED_SCOPE_HASHES_BEFORE_AFTER.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "before_sha256", "after_sha256", "before_bytes", "after_bytes", "gate"])
        writer.writeheader(); writer.writerows(rows)
    if result["gate"] != "PASS":
        raise RuntimeError(f"unauthorized protected scope changed: missing={len(unauthorized_missing)} mismatch={len(unauthorized_mismatch)} new={len(unauthorized_new)}")
    return result


def a01_change_manifest() -> dict[str, object]:
    before = json.loads(A01_BEFORE.read_text(encoding="utf-8-sig"))["files"]
    after: dict[str, object] = {}
    for path in (ROOT / "apps/a01").rglob("*"):
        relative = path.relative_to(ROOT)
        if not path.is_file() or any(part in {".venv", ".downloads", "local_state", "__pycache__"} for part in relative.parts) or path.suffix in {".pyc", ".pyo"}:
            continue
        after[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    result = {"before_count": len(before), "after_count": len(after), "changed": changed, "added": added, "removed": removed}
    path = TASK_ROOT / "evidence/after/A01_SOURCE_CHANGE_MANIFEST.json"
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if removed:
        raise RuntimeError(f"A01 source removals are not authorized: {removed}")
    return result


def copy_tree(source: Path, target: Path, excluded: set[str] | None = None) -> None:
    excluded = excluded or set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in excluded or part == "__pycache__" or part.endswith(".egg-info") for part in relative.parts): continue
        destination = target / relative
        if path.is_dir(): destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(path, destination)


def collect() -> None:
    if STAGING.exists() or VERIFY_ROOT.exists() or ZIP_PATH.exists():
        raise RuntimeError("refusing to overwrite existing A02 staging, verification, or release ZIP")
    STAGING.mkdir(parents=True)
    copy_tree(ROOT / "apps/a01", STAGING / "apps/a01", {".venv", ".downloads", "local_state"})
    copy_tree(ROOT / "tests/a01", STAGING / "tests/a01")
    copy_tree(ROOT / "tests/a02", STAGING / "tests/a02")
    copy_tree(ROOT / "docs/A02", STAGING / "docs/A02")
    copy_tree(ROOT / "reports/A02", STAGING / "reports/A02")
    copy_tree(TASK_ROOT / "evidence", STAGING / "review/A02/001/evidence")
    for source_name, target_name in (("ZIP_VERIFICATION.json", "PREFLIGHT_ZIP_VERIFICATION.json"), ("POST_EXTRACT_TEST_RESULTS.txt", "PREFLIGHT_POST_EXTRACT_TEST_RESULTS.txt")):
        source = TASK_ROOT / source_name
        if source.is_file():
            destination = STAGING / "review/A02/001" / target_name
            destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
    input_root = ROOT / "input/orchestrator_bundles/A02/extracted"
    for name in ("CDH_A02_UI_STATUS_HANDOFF_001_CODEX_TASK.md", "CDH_AB_RECEIPT_CONTRACT_V1.md", "CDH_A01_D01_ORCHESTRATOR_REVIEW_001.md", "README_FIRST.md", "MANIFEST.json", "AB_CROSS_TEST_REPLAY.txt", "A01_LINUX_TEST_REPLAY.txt"):
        destination = STAGING / "input_contract" / name
        destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(input_root / name, destination)
    a01_fixture = ROOT / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
    fixture_destination = STAGING / "input_contract/11_SYNTHETIC_SNAPSHOT_FIXTURE.json"
    fixture_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(a01_fixture, fixture_destination)
    (STAGING / "RUN_TESTS.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$env:QT_QPA_PLATFORM='offscreen'\n"
        "python -m unittest discover -s tests/a01 -v\nif($LASTEXITCODE -ne 0){exit $LASTEXITCODE}\n"
        "python -m unittest discover -s tests/a02 -v\nexit $LASTEXITCODE\n", encoding="utf-8")


def manifests() -> tuple[int, str]:
    payloads = []
    for path in sorted(STAGING.rglob("*")):
        relative = path.relative_to(STAGING).as_posix()
        if path.is_file() and relative not in {"MANIFEST.json", "SHA256SUMS.txt"}:
            payloads.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {"task_id":"CDH-A02-UI-STATUS-HANDOFF-001","authority":"AUTHORIZED_OFFLINE_A02_UI_ONLY","payload_count":len(payloads),"payloads":payloads,"excluded":[".venv",".downloads","local_state","production data","Cookie","Token","__pycache__"]}
    manifest_path = STAGING / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (STAGING / "SHA256SUMS.txt").write_text("".join(f"{item['sha256']}  {item['path']}\n" for item in payloads), encoding="utf-8")
    return len(payloads), sha256(manifest_path)


def build_zip() -> None:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file(): archive.write(path, path.relative_to(STAGING).as_posix())


def verify() -> dict[str, object]:
    VERIFY_ROOT.mkdir(parents=True)
    unsafe: list[str] = []; duplicates: list[str] = []; symlinks: list[str] = []; seen: set[str] = set()
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        for info in archive.infolist():
            if not safe_name(info.filename): unsafe.append(info.filename)
            folded = info.filename.casefold()
            if folded in seen: duplicates.append(info.filename)
            seen.add(folded)
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF): symlinks.append(info.filename)
        if bad_crc or unsafe or duplicates or symlinks: raise RuntimeError("ZIP safety gate failed")
        archive.extractall(VERIFY_ROOT)
    manifest = json.loads((VERIFY_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    declared = {item["path"]: item for item in manifest["payloads"]}
    actual = {
        path.relative_to(VERIFY_ROOT).as_posix()
        for path in VERIFY_ROOT.rglob("*")
        if path.is_file()
        and path.relative_to(VERIFY_ROOT).as_posix() not in {"MANIFEST.json", "SHA256SUMS.txt"}
    }
    missing = sorted(set(declared) - actual); undeclared = sorted(actual - set(declared))
    mismatch = sorted(name for name, item in declared.items() if name in actual and (sha256(VERIFY_ROOT / name) != item["sha256"] or (VERIFY_ROOT / name).stat().st_size != item["bytes"]))
    sums = {}
    for line in (VERIFY_ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    sums_mismatch = sorted(name for name,item in declared.items() if sums.get(name) != item["sha256"])
    if missing or undeclared or mismatch or sums_mismatch: raise RuntimeError("manifest gate failed")
    return {"zip":str(ZIP_PATH),"zip_bytes":ZIP_PATH.stat().st_size,"zip_sha256":sha256(ZIP_PATH),"entry_count":len(actual)+2,"payload_count":len(declared),"crc":"PASS","safe_paths":"PASS","case_collision":"PASS","symlink":"PASS","missing":0,"mismatch":0,"undeclared":0,"duplicates":0,"manifest_sha256":sha256(VERIFY_ROOT / "MANIFEST.json"),"gate":"PASS"}


def main() -> int:
    protected = protected_gate(); changes = a01_change_manifest(); collect(); payload_count, manifest_hash = manifests(); build_zip(); result = verify()
    result.update({"protected_scope_gate":protected["gate"],"a01_changed_count":len(changes["changed"]),"a01_added_count":len(changes["added"]),"generated_at_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z")})
    (TASK_ROOT / "ZIP_VERIFICATION.json").write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"payload_count":payload_count,"manifest_sha256":manifest_hash,**result},ensure_ascii=False,sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
