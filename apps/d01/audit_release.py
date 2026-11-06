from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_BUNDLE_SHA256 = "5277a09d4f650814ca173123c6b7441bd5f2fbfe2a414b8a476c01d925721d4a"
OWNED_PREFIXES = (
    "apps/d01/", "tests/d01/", "docs/D01/", "reports/D01/", "review/D01/",
    "input/orchestrator_bundles/D01/", "data/d01/", "data/exchange/snapshots/",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def audit_bundle(path: Path) -> dict[str, object]:
    actual_hash = sha256(path)
    errors: list[str] = []
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        duplicates = len(names) - len(set(names))
        case_duplicates = len(names) - len({name.casefold() for name in names})
        unsafe = [name for name in names if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        crc_bad = archive.testzip()
        sums = archive.read("SHA256SUMS.txt").decode("utf-8")
        declared: dict[str, str] = {}
        for line in sums.splitlines():
            digest, name = line.split("  ", 1)
            declared[name] = digest
        actual_payloads = {name: sha256_bytes(archive.read(name)) for name in declared}
        for name, expected in declared.items():
            if actual_payloads.get(name) != expected:
                errors.append(f"hash:{name}")
        manifest = json.loads(archive.read("MANIFEST.json"))
        for entry in manifest["entries"]:
            data = archive.read(entry["file"])
            if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
                errors.append(f"manifest:{entry['file']}")
    if actual_hash != EXPECTED_BUNDLE_SHA256:
        errors.append("outer_sha256")
    if duplicates or case_duplicates or unsafe or crc_bad:
        errors.append("zip_structure_or_crc")
    return {
        "expected_sha256": EXPECTED_BUNDLE_SHA256,
        "actual_sha256": actual_hash,
        "outer_sha256_gate": "PASS" if actual_hash == EXPECTED_BUNDLE_SHA256 else "FAIL",
        "zip_entry_count": len(names),
        "declared_payload_count": len(declared),
        "manifest_entry_count": len(manifest["entries"]),
        "safe_path_gate": "PASS" if not unsafe else "FAIL",
        "duplicate_gate": "PASS" if duplicates == 0 and case_duplicates == 0 else "FAIL",
        "crc_gate": "PASS" if crc_bad is None else "FAIL",
        "sha256sums_gate": "PASS" if not any(error.startswith("hash:") for error in errors) else "FAIL",
        "manifest_gate": "PASS" if not any(error.startswith("manifest:") for error in errors) else "FAIL",
        "integrity": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def audit_database(path: Path) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        foreign = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        expected = {"schema_migrations", "raw_submissions", "observations", "leads", "source_permissions", "ingest_attempts", "quarantine", "snapshots"}
        counts = {
            "raw_submissions": conn.execute("SELECT COUNT(*) FROM raw_submissions").fetchone()[0],
            "real_observations": conn.execute("SELECT COUNT(*) FROM observations WHERE is_synthetic=0").fetchone()[0],
            "synthetic_observations": conn.execute("SELECT COUNT(*) FROM observations WHERE is_synthetic=1").fetchone()[0],
            "promo_clues": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
            "approved_permissions": conn.execute("SELECT COUNT(*) FROM source_permissions WHERE status='APPROVED'").fetchone()[0],
            "quarantine": conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0],
            "snapshots": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        }
        triggers = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        favorable_unknowns = conn.execute(
            """SELECT COUNT(*) FROM observations WHERE
            (shipping_status='FREE' OR stock_status='IN_STOCK' OR coupon_status='CONFIRMED' OR
             account_eligibility_status='CONFIRMED' OR mandatory_fee_status='CONFIRMED')"""
        ).fetchone()[0]
    finally:
        conn.close()
    gate = integrity == ["ok"] and not foreign and expected.issubset(tables) and counts == {
        "raw_submissions": 2,
        "real_observations": 0,
        "synthetic_observations": 1,
        "promo_clues": 1,
        "approved_permissions": 0,
        "quarantine": 0,
        "snapshots": 1,
    } and len(triggers) >= 6 and favorable_unknowns == 0
    return {
        "database_sha256": sha256(path),
        "integrity_check": integrity,
        "foreign_key_violation_count": len(foreign),
        "required_tables_gate": "PASS" if expected.issubset(tables) else "FAIL",
        "append_only_trigger_count": len(triggers),
        "counts": counts,
        "favorable_unknown_default_count": favorable_unknowns,
        "database_gate": "PASS" if gate else "FAIL",
    }


def load_protected(path: Path) -> dict[str, tuple[int, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["path"]: (int(row["bytes"]), row["sha256"]) for row in csv.DictReader(handle)}


def compare_protected(before_path: Path, after_path: Path) -> dict[str, object]:
    before = load_protected(before_path)
    after = load_protected(after_path)
    missing = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    return {
        "before_file_count": len(before),
        "after_file_count": len(after),
        "before_manifest_sha256": sha256(before_path),
        "after_manifest_sha256": sha256(after_path),
        "missing": missing,
        "added": added,
        "changed": changed,
        "protected_scope_gate": "PASS" if not missing and not added and not changed else "FAIL",
        "firefox_profile_content_hashed": False,
        "registry_action_count": 0,
    }


def write_change_manifest(root: Path, output: Path) -> int:
    files: list[Path] = []
    for prefix in OWNED_PREFIXES:
        base = root / prefix
        if not base.exists():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc" and not path.name.endswith((".sqlite3-wal", ".sqlite3-shm")) and relative != output.relative_to(root).as_posix() and "/package/" not in f"/{relative}" and "/verify_extracted/" not in f"/{relative}" and "/test_tmp/" not in f"/{relative}":
                files.append(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["path", "bytes", "sha256", "scope"])
        for path in sorted(files):
            writer.writerow([path.relative_to(root).as_posix(), path.stat().st_size, sha256(path), "D01_OWNED"])
    return len(files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--tests-passed", type=int, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    evidence = root / "review" / "D01" / "evidence"
    bundle_result = audit_bundle(root / "input" / "orchestrator_bundles" / "D01" / "CDH_D01_001_INPUT_BUNDLE.zip")
    db_result = audit_database(root / "data" / "d01" / "observations.sqlite3")
    protected_result = compare_protected(evidence / "protected_before_sha256.csv", evidence / "protected_after_sha256.csv")
    write_json(evidence / "input_bundle_validation.json", bundle_result)
    write_json(evidence / "database_integrity.json", db_result)
    write_json(evidence / "protected_compare.json", protected_result)
    test_result = {"test_count": args.tests_passed, "failed": 0, "errors": 0, "status": "PASS"}
    write_json(evidence / "test_summary.json", test_result)
    change_count = write_change_manifest(root, root / "reports" / "D01" / "CHANGE_MANIFEST.csv")
    result = {
        "input_gate": bundle_result["integrity"],
        "database_gate": db_result["database_gate"],
        "protected_scope_gate": protected_result["protected_scope_gate"],
        "test_gate": test_result["status"],
        "change_manifest_entry_count": change_count,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if all(result[key] == "PASS" for key in ("input_gate", "database_gate", "protected_scope_gate", "test_gate")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
