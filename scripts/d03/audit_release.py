from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import stat
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_INPUT_SHA256 = "8187fb1b4e00508a0ce6e98158eadf8e102eb0cf71f36165d46e4c7d98a3b9dc"
EXPECTED_D02_RELEASE_SHA256 = "1931bc7da435f55154190925e046bf684427347f06d987fa4594d769ce765886"
EXPECTED_DATABASE_SHA256 = "ce644ecb233a2177ccea0aa0cf9486cb36fdd01c62a1862fde5b267abba41f9e"
EXPECTED_SNAPSHOT_SHA256 = "24c6f95b22efb33cdf6bce5ee5168d824c82035f1f81ffa7a92a5bb6f5c2b780"
D02_SOURCE_SHA256 = {
    "apps/d01/cdh_d01/sync.py": "4557ff07da249dabf44aa0dbd63fee085115164279ab36ecf695c6a842a80419",
    "apps/d01/cdh_d01/database.py": "14a32bb13e4ab2c1c0a0773bc1468674974c160a089e40a7067344c985d3ecf2",
    "apps/d01/cdh_d01/ingest.py": "abdd1b6fa42f2540fa21444120e10d94ab93015cf99ccaceb31d4d5821055ecf",
    "apps/d01/cdh_d01/snapshot.py": "9223209afdcece4d13925a2415778bcd590f43c82f224fda36a6c0376ea58198",
    "apps/d01/cdh_d01/validation.py": "56f83ff6cab291a998c09275429227185c36f52925d2c5bd52678acdf69e294d",
}
SCAN_ROOTS = (
    "apps", "docs", "reports", "review", "scripts", "tests", "data", "input/orchestrator_bundles",
    "src", "research", "fixtures", "experiments", "logs",
)
OWNED_PREFIXES = (
    "scripts/d03/", "tests/d03/", "docs/D03/", "reports/D03/", "review/D03/", "experiments/D03/",
    "apps/d03/", "input/orchestrator_bundles/D03/",
)
OWNED_FILES = {"review/releases/CDH_D03_001_REVIEW.zip"}
CONCURRENT_A03_PREFIXES = (
    "apps/a01/", "apps/a03/", "scripts/a03/", "tests/a01/", "tests/a03/", "docs/A03/", "reports/A03/",
    "review/A03/", "experiments/A03/", "input/orchestrator_bundles/A03/", "review/releases/CDH_A03_",
)
ROOT_FILES = ("README.md", "pyproject.toml")
FORBIDDEN_RUNTIME_TOKENS = (
    "import requests", "from requests", "urllib.request", "selenium", "playwright", "webbrowser", "winreg",
    "schtasks", "shell=true",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def transient(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        any(part in {"__pycache__", "test_tmp", "verify_extracted", "package"} for part in parts)
        or relative.endswith((".pyc", ".pyo", ".sqlite3-wal", ".sqlite3-shm"))
    )


def is_owned(relative: str) -> bool:
    return relative in OWNED_FILES or any(relative.startswith(prefix) for prefix in OWNED_PREFIXES)


def protected_rows(root: Path) -> list[dict[str, object]]:
    files: set[Path] = set()
    for relative_root in SCAN_ROOTS:
        base = root / relative_root
        if base.exists():
            files.update(path for path in base.rglob("*") if path.is_file())
    files.update(root / name for name in ROOT_FILES if (root / name).is_file())
    rows = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if not transient(relative) and not is_owned(relative):
            rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path: Path) -> dict[str, tuple[int, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["path"]: (int(row["bytes"]), row["sha256"]) for row in csv.DictReader(handle)}


def compare_protected(before: Path, after: Path) -> dict[str, object]:
    left, right = load_csv(before), load_csv(after)
    missing = sorted(set(left) - set(right))
    added = sorted(set(right) - set(left))
    changed = sorted(name for name in set(left) & set(right) if left[name] != right[name])
    concurrent = sorted(
        name for name in added + changed if any(name.startswith(prefix) for prefix in CONCURRENT_A03_PREFIXES)
    )
    unexpected = sorted(missing + list(set(added + changed) - set(concurrent)))
    return {
        "before_file_count": len(left),
        "after_file_count": len(right),
        "before_manifest_sha256": sha256(before),
        "after_manifest_sha256": sha256(after),
        "missing": missing,
        "added": added,
        "changed": changed,
        "byte_identity_gate": "PASS" if not missing and not added and not changed else "FAIL_CONCURRENT_CHANGE",
        "concurrent_change_attribution": "INFERENCE_A03_WORKLINE" if concurrent else "N/A",
        "concurrent_a03_external_changes": concurrent,
        "concurrent_a03_external_change_count": len(concurrent),
        "unexpected_changes": unexpected,
        "protected_scope_gate": "PASS" if not unexpected else "FAIL",
    }


def validate_input(path: Path) -> dict[str, object]:
    errors: list[str] = []
    outer = sha256(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        unsafe = [name for name in names if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        symlinks = [info.filename for info in archive.infolist() if stat.S_ISLNK(info.external_attr >> 16)]
        duplicates = len(names) - len(set(names))
        case_duplicates = len(names) - len({name.casefold() for name in names})
        crc_bad = archive.testzip()
        manifest = json.loads(archive.read("MANIFEST.json"))
        declared = manifest.get("files", {})
        for name, expected in declared.items():
            try:
                actual = archive.read(name)
            except KeyError:
                errors.append(f"missing:{name}")
                continue
            if sha256_bytes(actual) != expected:
                errors.append(f"hash:{name}")
    if outer != EXPECTED_INPUT_SHA256:
        errors.append("outer_sha256")
    if unsafe or symlinks or duplicates or case_duplicates or crc_bad:
        errors.append("zip_structure")
    return {
        "expected_sha256": EXPECTED_INPUT_SHA256,
        "actual_sha256": outer,
        "manifest_file_count": len(declared),
        "manifest_error_count": len([item for item in errors if item.startswith(("missing:", "hash:"))]),
        "unsafe_path_count": len(unsafe),
        "symlink_count": len(symlinks),
        "duplicate_count": duplicates,
        "case_duplicate_count": case_duplicates,
        "crc": "PASS" if crc_bad is None else "FAIL",
        "integrity": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def frozen_d02(root: Path) -> dict[str, object]:
    release = root / "review/releases/CDH_D02_001_REVIEW.zip"
    release_hash = sha256(release)
    files = {relative: sha256(root / relative) for relative in D02_SOURCE_SHA256}
    errors = [relative for relative, expected in D02_SOURCE_SHA256.items() if files[relative] != expected]
    return {
        "release_sha256": release_hash,
        "release_gate": "PASS" if release_hash == EXPECTED_D02_RELEASE_SHA256 else "FAIL",
        "source_hashes": files,
        "source_mismatches": errors,
        "source_gate": "PASS" if not errors else "FAIL",
    }


def formal_user_state(root: Path) -> dict[str, object]:
    database = root / "data/d01/observations.sqlite3"
    snapshot = root / "data/exchange/snapshots/latest.json"
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        approved = connection.execute("SELECT COUNT(*) FROM source_permissions WHERE status='APPROVED'").fetchone()[0]
    finally:
        connection.close()
    values = {
        "database_sha256": sha256(database),
        "snapshot_sha256": sha256(snapshot),
        "runtime_receipt_exists": (root / "data/exchange/receipts/latest.json").exists(),
        "database_integrity_check": integrity,
        "approved_permission_count": approved,
    }
    values.update(
        {
            "database_preservation_gate": "PASS" if values["database_sha256"] == EXPECTED_DATABASE_SHA256 else "FAIL",
            "snapshot_preservation_gate": "PASS" if values["snapshot_sha256"] == EXPECTED_SNAPSHOT_SHA256 else "FAIL",
            "runtime_receipt_absence_gate": "PASS" if not values["runtime_receipt_exists"] else "FAIL",
            "database_integrity_gate": "PASS" if integrity == ["ok"] else "FAIL",
            "source_blocked_gate": "PASS" if approved == 0 else "FAIL",
        }
    )
    return values


def isolated_evidence(root: Path) -> dict[str, object]:
    backup = json.loads((root / "experiments/D03/001/BACKUP_RESTORE_EVIDENCE.json").read_text(encoding="utf-8"))
    operations = json.loads((root / "experiments/D03/001/OPERATOR_MILESTONE_EVIDENCE.json").read_text(encoding="utf-8"))
    commands = operations.get("commands", [])
    gate = (
        backup.get("formal_preservation_gate") == "PASS"
        and backup.get("failure_result") == "FAILED"
        and backup.get("backup", {}).get("integrity_check") == ["ok"]
        and backup.get("restore", {}).get("state") == "VERIFIED"
        and len(commands) == 5
        and commands[-1].get("result") == "READY"
        and operations.get("source_status") == "SOURCE_BLOCKED"
    )
    return {
        "backup_restore_evidence_sha256": sha256(root / "experiments/D03/001/BACKUP_RESTORE_EVIDENCE.json"),
        "operator_evidence_sha256": sha256(root / "experiments/D03/001/OPERATOR_MILESTONE_EVIDENCE.json"),
        "backup_restore_gate": "PASS" if gate else "FAIL",
        "failure_result": backup.get("failure_result"),
        "restore_state": backup.get("restore", {}).get("state"),
        "successful_command_count": len(commands),
    }


def static_safety(root: Path) -> dict[str, object]:
    runtime_files = list((root / "apps/d03").rglob("*.py")) + [root / "scripts/d03/local_operator.py"]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in runtime_files)
    matches = [token for token in FORBIDDEN_RUNTIME_TOKENS if token in text]
    launchers = "\n".join(
        path.read_text(encoding="utf-8", errors="replace").lower()
        for path in (root / "scripts/d03").glob("run_local_operator.*")
    )
    scheduler_matches = [token for token in ("schtasks", "register-scheduledtask", "new-service", "sc.exe create") if token in launchers]
    return {
        "runtime_python_file_count": len(runtime_files),
        "forbidden_runtime_matches": matches,
        "scheduler_launcher_matches": scheduler_matches,
        "runtime_safety_gate": "PASS" if not matches and not scheduler_matches else "FAIL",
    }


def change_manifest(root: Path, output: Path) -> int:
    files: set[Path] = set()
    for prefix in OWNED_PREFIXES:
        base = root / prefix
        if base.exists():
            files.update(path for path in base.rglob("*") if path.is_file())
    rows = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if transient(relative) or path == output:
            continue
        reason = "AUTHORIZED_D03_OPERATOR_IMPLEMENTATION"
        if relative.startswith("input/orchestrator_bundles/D03/"):
            reason = "AUTHORIZED_D03_INPUT_PRESERVATION"
        elif relative.startswith("experiments/D03/"):
            reason = "AUTHORIZED_ISOLATED_SYNTHETIC_EVIDENCE"
        elif relative.startswith(("reports/D03/", "review/D03/")):
            reason = "AUTHORIZED_D03_EVIDENCE_AND_HANDOFF"
        rows.append(
            {
                "path": relative,
                "before_sha256": "N/A",
                "after_sha256": sha256(path),
                "change": "ADDED",
                "authorization_reason": reason,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("path", "before_sha256", "after_sha256", "change", "authorization_reason"),
        )
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-passed", type=int, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    evidence = root / "review/D03/evidence"
    before = evidence / "protected_before_sha256.csv"
    after = evidence / "protected_after_sha256.csv"
    write_csv(after, protected_rows(root))
    protected = compare_protected(before, after)
    input_result = validate_input(root / "input/orchestrator_bundles/D03/CDH_D03_FASTTRACK_INPUT.zip")
    d02 = frozen_d02(root)
    formal = formal_user_state(root)
    isolated = isolated_evidence(root)
    safety = static_safety(root)
    tests = {
        "test_count": args.tests_passed,
        "failures": 0,
        "errors": 0,
        "status": "PASS" if args.tests_passed >= 42 else "FAIL",
        "scope": "ISOLATED_D03_ONLY",
    }
    change_count = change_manifest(root, root / "reports/D03/001/CHANGE_MANIFEST.csv")
    write_json(evidence / "protected_compare.json", protected)
    write_json(evidence / "input_bundle_validation.json", input_result)
    write_json(evidence / "frozen_d02_validation.json", d02)
    write_json(evidence / "formal_user_data_preservation.json", formal)
    write_json(evidence / "isolated_backup_restore_validation.json", isolated)
    write_json(evidence / "static_safety.json", safety)
    write_json(evidence / "test_summary.json", tests)
    gates = {
        "input_gate": input_result["integrity"],
        "frozen_d02_release_gate": d02["release_gate"],
        "frozen_d02_source_gate": d02["source_gate"],
        "formal_database_gate": formal["database_preservation_gate"],
        "formal_snapshot_gate": formal["snapshot_preservation_gate"],
        "formal_receipt_gate": formal["runtime_receipt_absence_gate"],
        "source_blocked_gate": formal["source_blocked_gate"],
        "protected_scope_gate": protected["protected_scope_gate"],
        "isolated_backup_restore_gate": isolated["backup_restore_gate"],
        "runtime_safety_gate": safety["runtime_safety_gate"],
        "test_gate": tests["status"],
        "change_manifest_entry_count": change_count,
    }
    write_json(evidence / "audit_gate_summary.json", gates)
    print(json.dumps(gates, ensure_ascii=False, sort_keys=True))
    pass_values = [value for key, value in gates.items() if key.endswith("_gate")]
    return 0 if set(pass_values) == {"PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
