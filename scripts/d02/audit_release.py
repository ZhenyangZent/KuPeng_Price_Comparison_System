from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import stat
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_INPUT_SHA256 = "46f682da300e5a73ff83503c6432c8e6efc5aadd0f53f880a434368b03aea170"
EXPECTED_D01_RELEASE_SHA256 = "738ae737e85e0534c25548d93ec4665c9ceafd0544cbbca68cc2cfbe842bb767"
EXPECTED_USER_DB_SHA256 = "ce644ecb233a2177ccea0aa0cf9486cb36fdd01c62a1862fde5b267abba41f9e"
EXPECTED_USER_SNAPSHOT_SHA256 = "24c6f95b22efb33cdf6bce5ee5168d824c82035f1f81ffa7a92a5bb6f5c2b780"
PROTECTED_ROOTS = (
    "apps/a01", "docs/A01", "docs/A02", "reports/A01", "reports/A02", "review/A01", "review/A02",
    "tests/a01", "tests/a02", "reports/B01", "review/B01", "tests/b01", "input/orchestrator_bundles/B01",
    "review/C01", "src", "reports/I01", "review/I01", "tests/i01", "input/orchestrator_bundles/I01",
    "reports/G0", "review/G0", "tests/g0", "input/orchestrator_bundles/G0", "tests/d01", "docs/D01",
    "reports/D01", "review/D01", "input/orchestrator_bundles/D01", "data/d01", "data/exchange",
    "review/releases",
)
ROOT_FILES = ("README.md", "pyproject.toml")
CONCURRENT_A02_PREFIXES = (
    "apps/a01/", "tests/a01/", "tests/a02/", "docs/A01/", "docs/A02/", "reports/A01/", "reports/A02/",
    "review/A01/", "review/A02/", "input/orchestrator_bundles/A01/", "input/orchestrator_bundles/A02/",
    "review/releases/CDH_A02_",
)
FORBIDDEN_SOURCE_TOKENS = (
    "import requests", "from requests", "urllib.request", "selenium", "playwright", "webbrowser",
    "winreg", "schtasks", "scheduledtask", "firefox profile",
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


def ignored(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    return (
        any(part in {"__pycache__", "test_tmp", "verify_extracted", "package"} for part in parts)
        or relative.endswith((".pyc", ".pyo", ".sqlite3-wal", ".sqlite3-shm"))
        or relative == "review/releases/CDH_D02_001_REVIEW.zip"
    )


def protected_rows(root: Path) -> list[dict[str, object]]:
    files: set[Path] = set()
    for relative_root in PROTECTED_ROOTS:
        base = root / relative_root
        if base.exists():
            files.update(path for path in base.rglob("*") if path.is_file())
    files.update(root / name for name in ROOT_FILES if (root / name).is_file())
    rows = []
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        if not ignored(relative):
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
    concurrent_a02 = sorted(
        name for name in added + changed if any(name.startswith(prefix) for prefix in CONCURRENT_A02_PREFIXES)
    )
    unexpected_added_or_changed = sorted(set(added + changed) - set(concurrent_a02))
    unexpected = sorted(missing + unexpected_added_or_changed)
    return {
        "before_file_count": len(left),
        "after_file_count": len(right),
        "before_manifest_sha256": sha256(before),
        "after_manifest_sha256": sha256(after),
        "missing": missing,
        "added": added,
        "changed": changed,
        "byte_identity_gate": "PASS" if not missing and not added and not changed else "FAIL_CONCURRENT_CHANGE",
        "concurrent_change_attribution": "INFERENCE_A02_WORKLINE",
        "concurrent_a02_external_changes": concurrent_a02,
        "concurrent_a02_external_change_count": len(concurrent_a02),
        "unexpected_changes": unexpected,
        "protected_scope_gate": "PASS" if not unexpected else "FAIL",
    }


def validate_input_bundle(path: Path) -> dict[str, object]:
    errors: list[str] = []
    outer = sha256(path)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        unsafe = [name for name in names if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts]
        symlinks = [info.filename for info in archive.infolist() if stat.S_ISLNK(info.external_attr >> 16)]
        duplicate_count = len(names) - len(set(names))
        case_duplicate_count = len(names) - len({name.casefold() for name in names})
        crc_bad = archive.testzip()
        manifest = json.loads(archive.read("MANIFEST.json"))
        for entry in manifest["entries"]:
            try:
                data = archive.read(entry["path"])
            except KeyError:
                errors.append(f"missing:{entry['path']}")
                continue
            if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
                errors.append(f"mismatch:{entry['path']}")
    if outer != EXPECTED_INPUT_SHA256:
        errors.append("outer_sha256")
    if unsafe or symlinks or duplicate_count or case_duplicate_count or crc_bad:
        errors.append("zip_structure")
    return {
        "expected_sha256": EXPECTED_INPUT_SHA256,
        "actual_sha256": outer,
        "manifest_entry_count": len(manifest["entries"]),
        "manifest_error_count": len([item for item in errors if item.startswith(("missing:", "mismatch:"))]),
        "unsafe_path_count": len(unsafe),
        "symlink_count": len(symlinks),
        "duplicate_count": duplicate_count,
        "case_duplicate_count": case_duplicate_count,
        "crc": "PASS" if crc_bad is None else "FAIL",
        "integrity": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def audit_user_state(root: Path) -> dict[str, object]:
    db = root / "data/d01/observations.sqlite3"
    snapshot = root / "data/exchange/snapshots/latest.json"
    release = root / "review/releases/CDH_D01_001_REVIEW.zip"
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in conn.execute("PRAGMA integrity_check")]
        approved = conn.execute("SELECT COUNT(*) FROM source_permissions WHERE status='APPROVED'").fetchone()[0]
    finally:
        conn.close()
    values = {
        "d01_release_sha256": sha256(release),
        "database_sha256": sha256(db),
        "snapshot_sha256": sha256(snapshot),
        "database_integrity_check": integrity,
        "approved_permission_count": approved,
        "runtime_receipt_exists": (root / "data/exchange/receipts/latest.json").exists(),
    }
    values["d01_release_preserved_gate"] = "PASS" if values["d01_release_sha256"] == EXPECTED_D01_RELEASE_SHA256 else "FAIL"
    values["user_database_preserved_gate"] = "PASS" if values["database_sha256"] == EXPECTED_USER_DB_SHA256 else "FAIL"
    values["user_snapshot_preserved_gate"] = "PASS" if values["snapshot_sha256"] == EXPECTED_USER_SNAPSHOT_SHA256 else "FAIL"
    values["runtime_receipt_not_published_gate"] = "PASS" if not values["runtime_receipt_exists"] else "FAIL"
    values["source_blocked_gate"] = "PASS" if approved == 0 else "FAIL"
    values["database_integrity_gate"] = "PASS" if integrity == ["ok"] else "FAIL"
    return values


def static_safety(root: Path) -> dict[str, object]:
    source_files = list((root / "apps/d01").rglob("*.py")) + [root / "scripts/d02/d02_sync.py"]
    text = "\n".join(path.read_text(encoding="utf-8").lower() for path in source_files)
    matches = [token for token in FORBIDDEN_SOURCE_TOKENS if token in text]
    scheduler_files = [path.relative_to(root).as_posix() for path in (root / "scripts/d02").rglob("*") if path.suffix.lower() in {".xml", ".vbs"}]
    launchers = "\n".join(
        path.read_text(encoding="utf-8", errors="replace").lower()
        for path in (root / "scripts/d02").glob("run_local_sync.*")
        if path.is_file()
    )
    scheduler_tokens = [token for token in ("schtasks", "register-scheduledtask", "new-service", "sc.exe create") if token in launchers]
    return {
        "python_file_count": len(source_files),
        "forbidden_token_matches": matches,
        "scheduler_artifacts": scheduler_files,
        "scheduler_launcher_tokens": scheduler_tokens,
        "external_collection_gate": "PASS" if not matches else "FAIL",
        "permanent_scheduler_gate": "PASS" if not scheduler_files and not scheduler_tokens else "FAIL",
    }


def main() -> int:
    root = Path.cwd().resolve()
    evidence = root / "review/D02/evidence"
    before = evidence / "protected_before_sha256.csv"
    after = evidence / "protected_after_sha256.csv"
    write_csv(after, protected_rows(root))
    protected = compare_protected(before, after)
    bundle = validate_input_bundle(root / "input/orchestrator_bundles/D02/CDH_D02_001_INPUT_BUNDLE.zip")
    user_state = audit_user_state(root)
    safety = static_safety(root)
    write_json(evidence / "protected_compare.json", protected)
    write_json(evidence / "input_bundle_validation.json", bundle)
    write_json(evidence / "user_data_preservation.json", user_state)
    write_json(evidence / "static_safety.json", safety)
    gates = {
        "input_bundle_gate": bundle["integrity"],
        "protected_scope_gate": protected["protected_scope_gate"],
        "user_database_gate": user_state["user_database_preserved_gate"],
        "user_snapshot_gate": user_state["user_snapshot_preserved_gate"],
        "historic_d01_release_gate": user_state["d01_release_preserved_gate"],
        "runtime_receipt_gate": user_state["runtime_receipt_not_published_gate"],
        "source_blocked_gate": user_state["source_blocked_gate"],
        "external_collection_gate": safety["external_collection_gate"],
        "permanent_scheduler_gate": safety["permanent_scheduler_gate"],
    }
    write_json(evidence / "audit_gate_summary.json", gates)
    print(json.dumps(gates, ensure_ascii=False, sort_keys=True))
    return 0 if set(gates.values()) == {"PASS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
