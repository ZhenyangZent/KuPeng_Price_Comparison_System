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
TASK_ROOT = ROOT / "review/A02/R01"
STAGING = TASK_ROOT / "package"
VERIFY_ROOT = TASK_ROOT / "verification"
ZIP_PATH = ROOT / "review/releases/CDH_A02_R01_REVIEW.zip"
PROTECTED_BEFORE = TASK_ROOT / "evidence/before/PROTECTED_SCOPE_BEFORE.json"
A02_BEFORE = TASK_ROOT / "evidence/before/A02_SOURCE_BEFORE.json"
ALLOWED_CHANGED = {
    "apps/a01/a01_app/receipt.py",
    "tests/a02/test_receipt_status.py",
}
ALLOWED_ADDED = {
    "apps/a01/tools/a02_r01_direct_writer.py",
    "apps/a01/tools/build_a02_r01_review.py",
    "apps/a01/tools/capture_a02_r01_compat.py",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tracked_files(relative_roots: list[str]) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = {}
    for relative_root in relative_roots:
        folder = ROOT / relative_root
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            relative = path.relative_to(ROOT)
            if (
                not path.is_file()
                or any(part in {".venv", ".downloads", "local_state", "__pycache__"} for part in relative.parts)
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            files[relative.as_posix()] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    return files


def protected_gate() -> dict[str, object]:
    baseline = json.loads(PROTECTED_BEFORE.read_text(encoding="utf-8-sig"))
    expected: dict[str, dict[str, object]] = baseline["files"]
    current = tracked_files(baseline["protected_roots"])
    for path in sorted((ROOT / "review/releases").glob("*.zip")):
        if path.resolve() == ZIP_PATH.resolve():
            continue
        relative = path.relative_to(ROOT).as_posix()
        current[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    mismatch = sorted(name for name in set(expected) & set(current) if expected[name] != current[name])
    rows = []
    for name in sorted(set(expected) | set(current)):
        before = expected.get(name, {})
        after = current.get(name, {})
        rows.append(
            {
                "path": name,
                "before_bytes": before.get("bytes", ""),
                "before_sha256": before.get("sha256", ""),
                "after_bytes": after.get("bytes", ""),
                "after_sha256": after.get("sha256", ""),
                "gate": "PASS" if name in expected and name in current and before == after else "FAIL",
            }
        )
    report_dir = ROOT / "reports/A02/R01"
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "PROTECTED_SCOPE_BEFORE_AFTER.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    result = {
        "task_id": "CDH-A02-RECEIPT-COMPAT-REWORK-002",
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "expected_file_count": len(expected),
        "verified_file_count": len(set(expected) & set(current)),
        "missing": missing,
        "added": added,
        "mismatch": mismatch,
        "gate": "PASS" if not missing and not added and not mismatch else "FAIL",
    }
    after = TASK_ROOT / "evidence/after/PROTECTED_SCOPE_AFTER.json"
    after.parent.mkdir(parents=True, exist_ok=True)
    after.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    if result["gate"] != "PASS":
        raise RuntimeError(f"protected scope changed: missing={missing} added={added} mismatch={mismatch}")
    return result


def change_manifest() -> dict[str, object]:
    baseline = json.loads(A02_BEFORE.read_text(encoding="utf-8-sig"))
    before: dict[str, dict[str, object]] = baseline["files"]
    after = tracked_files(baseline["roots"])
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    unexpected_changed = sorted(set(changed) - ALLOWED_CHANGED)
    unexpected_added = sorted(set(added) - ALLOWED_ADDED)
    rows = []
    for name in sorted(set(before) | set(after)):
        old = before.get(name, {})
        new = after.get(name, {})
        status = "CHANGED" if name in changed else "ADDED" if name in added else "REMOVED" if name in removed else "UNCHANGED"
        if status != "UNCHANGED":
            rows.append(
                {
                    "status": status,
                    "path": name,
                    "before_bytes": old.get("bytes", ""),
                    "before_sha256": old.get("sha256", ""),
                    "after_bytes": new.get("bytes", ""),
                    "after_sha256": new.get("sha256", ""),
                }
            )
    with (ROOT / "reports/A02/R01/CHANGE_MANIFEST.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["status", "path", "before_bytes", "before_sha256", "after_bytes", "after_sha256"])
        writer.writeheader()
        writer.writerows(rows)
    result = {
        "changed": changed,
        "added": added,
        "removed": removed,
        "unexpected_changed": unexpected_changed,
        "unexpected_added": unexpected_added,
        "gate": "PASS" if not removed and not unexpected_changed and not unexpected_added else "FAIL",
    }
    (TASK_ROOT / "evidence/after/A02_CHANGE_MANIFEST.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    if result["gate"] != "PASS":
        raise RuntimeError(f"A02 change scope failed: {result}")
    return result


def copy_tree(source: Path, target: Path, excluded: set[str] | None = None) -> None:
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


def collect() -> None:
    if STAGING.exists() or VERIFY_ROOT.exists() or ZIP_PATH.exists():
        raise RuntimeError("refusing to overwrite existing A02 R01 staging, verification, or release ZIP")
    STAGING.mkdir(parents=True)
    copy_tree(ROOT / "apps/a01", STAGING / "apps/a01", {".venv", ".downloads", "local_state"})
    copy_tree(ROOT / "tests/a01", STAGING / "tests/a01")
    copy_tree(ROOT / "tests/a02", STAGING / "tests/a02")
    copy_tree(ROOT / "docs/A02", STAGING / "docs/A02")
    copy_tree(ROOT / "reports/A02/R01", STAGING / "reports/A02/R01")
    copy_tree(TASK_ROOT / "evidence", STAGING / "review/A02/R01/evidence")
    for source_name, target_name in (
        ("ZIP_VERIFICATION.json", "PREFLIGHT_ZIP_VERIFICATION.json"),
        ("POST_EXTRACT_TEST_RESULTS.txt", "PREFLIGHT_POST_EXTRACT_TEST_RESULTS.txt"),
    ):
        source = TASK_ROOT / source_name
        if source.is_file():
            destination = STAGING / "review/A02/R01" / target_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    audit = ROOT / "input/orchestrator_audits/A02_D02_002/extracted"
    for name in (
        "CDH_A02_RECEIPT_COMPAT_REWORK_002_CODEX_TASK.md",
        "CDH_A02_D02_ORCHESTRATOR_REVIEW_002.md",
        "CDH_A02_D02_AUDIT_002_README.md",
        "CDH_AB_INDEPENDENT_CROSSLINE_12_CASES.py",
        "CDH_AB_INDEPENDENT_RESULTS_12.txt",
        "MANIFEST.json",
        "SHA256SUMS.txt",
    ):
        destination = STAGING / "input_contract" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audit / name, destination)
    shutil.copy2(ROOT / "input/orchestrator_bundles/A02/extracted/CDH_AB_RECEIPT_CONTRACT_V1.md", STAGING / "input_contract/CDH_AB_RECEIPT_CONTRACT_V1.md")
    shutil.copy2(ROOT / "input/orchestrator_bundles/A01/extracted/11_SYNTHETIC_SNAPSHOT_FIXTURE.json", STAGING / "input_contract/11_SYNTHETIC_SNAPSHOT_FIXTURE.json")
    (STAGING / "RUN_A01_A02_TESTS.ps1").write_text(
        "$ErrorActionPreference='Stop'\n$env:QT_QPA_PLATFORM='offscreen'\n"
        "python -m unittest discover -s tests/a01 -v\nif($LASTEXITCODE -ne 0){exit $LASTEXITCODE}\n"
        "python -m unittest discover -s tests/a02 -v\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )
    (STAGING / "RUN_CROSSLINE_TESTS.ps1").write_text(
        "param([Parameter(Mandatory=$true)][string]$ProjectRoot)\n$ErrorActionPreference='Stop'\n"
        "$env:CDH_PROJECT_ROOT=(Resolve-Path -LiteralPath $ProjectRoot).Path\n"
        "$env:CDH_TEST_TMP_ROOT=Join-Path $env:CDH_PROJECT_ROOT 'review/A02/R01/tmp/replay'\n"
        "New-Item -ItemType Directory -Force -Path $env:CDH_TEST_TMP_ROOT | Out-Null\n"
        "python input_contract/CDH_AB_INDEPENDENT_CROSSLINE_12_CASES.py -v\nexit $LASTEXITCODE\n",
        encoding="utf-8",
    )


def build_manifest() -> tuple[int, str]:
    payloads = []
    for path in sorted(STAGING.rglob("*")):
        relative = path.relative_to(STAGING).as_posix()
        if path.is_file() and relative not in {"MANIFEST.json", "SHA256SUMS.txt"}:
            payloads.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "task_id": "CDH-A02-RECEIPT-COMPAT-REWORK-002",
        "authority": "AUTHORIZED_OFFLINE_SYNTHETIC_A02_ONLY",
        "payload_count": len(payloads),
        "payloads": payloads,
        "excluded": [".venv", ".downloads", "local_state", "production data", "Cookie", "Token", "__pycache__"],
    }
    manifest_path = STAGING / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (STAGING / "SHA256SUMS.txt").write_text(
        "".join(f"{item['sha256']}  {item['path']}\n" for item in payloads), encoding="utf-8"
    )
    return len(payloads), sha256(manifest_path)


def safe_name(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)


def build_and_verify() -> dict[str, object]:
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(STAGING.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(STAGING).as_posix())
    VERIFY_ROOT.mkdir(parents=True)
    unsafe: list[str] = []
    duplicates: list[str] = []
    symlinks: list[str] = []
    seen: set[str] = set()
    with zipfile.ZipFile(ZIP_PATH) as archive:
        bad_crc = archive.testzip()
        for info in archive.infolist():
            if not safe_name(info.filename):
                unsafe.append(info.filename)
            folded = info.filename.casefold()
            if folded in seen:
                duplicates.append(info.filename)
            seen.add(folded)
            if stat.S_ISLNK((info.external_attr >> 16) & 0xFFFF):
                symlinks.append(info.filename)
        if bad_crc or unsafe or duplicates or symlinks:
            raise RuntimeError("ZIP safety gate failed")
        archive.extractall(VERIFY_ROOT)
    manifest = json.loads((VERIFY_ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    declared = {item["path"]: item for item in manifest["payloads"]}
    actual = {
        path.relative_to(VERIFY_ROOT).as_posix()
        for path in VERIFY_ROOT.rglob("*")
        if path.is_file()
        and path.relative_to(VERIFY_ROOT).as_posix() not in {"MANIFEST.json", "SHA256SUMS.txt"}
    }
    missing = sorted(set(declared) - actual)
    undeclared = sorted(actual - set(declared))
    mismatch = sorted(
        name
        for name, item in declared.items()
        if name in actual and (sha256(VERIFY_ROOT / name) != item["sha256"] or (VERIFY_ROOT / name).stat().st_size != item["bytes"])
    )
    sums = {}
    for line in (VERIFY_ROOT / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        sums[name] = digest
    sums_mismatch = sorted(name for name, item in declared.items() if sums.get(name) != item["sha256"])
    if missing or undeclared or mismatch or sums_mismatch:
        raise RuntimeError("manifest gate failed")
    return {
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256(ZIP_PATH),
        "entry_count": len(actual) + 2,
        "payload_count": len(declared),
        "crc": "PASS",
        "safe_paths": "PASS",
        "case_collision": "PASS",
        "symlink": "PASS",
        "missing": 0,
        "mismatch": 0,
        "undeclared": 0,
        "duplicates": 0,
        "manifest_sha256": sha256(VERIFY_ROOT / "MANIFEST.json"),
        "gate": "PASS",
    }


def main() -> int:
    protected = protected_gate()
    changes = change_manifest()
    collect()
    payload_count, manifest_hash = build_manifest()
    result = build_and_verify()
    result.update(
        {
            "protected_scope_gate": protected["gate"],
            "changed_count": len(changes["changed"]),
            "added_count": len(changes["added"]),
            "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    (TASK_ROOT / "ZIP_VERIFICATION.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"payload_count": payload_count, "manifest_sha256": manifest_hash, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
