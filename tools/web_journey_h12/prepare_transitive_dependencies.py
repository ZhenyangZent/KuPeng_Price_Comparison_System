from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12"
EVIDENCE = H12 / "evidence"
PROJECT_RELEASES = H12 / "runtime" / "project" / "review" / "releases"
SOURCE_RELEASES = ROOT / "review" / "releases"
CURRENT = EVIDENCE / "ACTUAL_H12_BROWSER_HTTP.json"
PRESERVED = EVIDENCE / "ACTUAL_H12_BROWSER_HTTP_ATTEMPT1_UNDOCUMENTED_DEPENDENCY_FAIL.json"
OUT = EVIDENCE / "A16_TRANSITIVE_DEPENDENCY_GAP.json"
TRANSITIVE = {
    "CDH_B_R09_001_REVIEW.zip": "aa0c1b5e938ac87d7c9a81206e7a2df1e14ea656e3dcba74f59501a76f6a4638",
    "CDH_B_R10_001_REVIEW.zip": "db112964be7a5ada7b393902ee7a6de9d5a328b15b97880981046eef7cc9a6e9",
    "CDH_C_R10_002_REVIEW.zip": "9c8fea4d15750b3b875d5fa6b856366243fd73c58a9affb4a81debed2cc232aa",
    "CDH_A_R11_004_REVIEW.zip": "19dae9f84e53bbdabdc3389e49ababe82586581073258908fda314edb0f41160",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    failed = json.loads(CURRENT.read_text(encoding="utf-8"))
    if failed.get("status") != "FAIL" or "CDH_B_R09_001_REVIEW.zip" not in failed.get("error", ""):
        raise RuntimeError("expected A16 transitive dependency failure was not preserved")
    if PRESERVED.exists():
        raise RuntimeError("attempt-1 failure evidence already exists")
    shutil.copy2(CURRENT, PRESERVED)
    copied = {}
    for name, expected in TRANSITIVE.items():
        source = SOURCE_RELEASES / name
        actual = sha256(source)
        if actual != expected:
            raise RuntimeError(f"transitive dependency hash mismatch: {name}")
        destination = PROJECT_RELEASES / name
        if destination.exists():
            raise RuntimeError(f"transitive dependency unexpectedly already staged: {name}")
        shutil.copyfile(source, destination)
        copied[name] = actual
    result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "A16_DEPENDENCY_DECLARATION_GAP_CONFIRMED",
        "responsible_workline": "A",
        "first_failed_release": "CDH_B_R09_001_REVIEW.zip",
        "documented_and_preflight_checked_release_count": 4,
        "additional_transitive_release_count": len(copied),
        "additional_transitive_releases": copied,
        "a16_source_modification_count": 0,
        "retry_scope": "H12 isolated workspace only; exact existing release copies",
        "preserved_failure": PRESERVED.relative_to(ROOT).as_posix(),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
