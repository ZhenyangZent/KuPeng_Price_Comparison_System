from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "review" / "H09" / "runtime" / "project" / "review" / "H09" / "private-data" / "private_user_observations.sqlite3"
OUT = ROOT / "review" / "H09" / "evidence" / "SQLITE_READONLY_EVIDENCE.json"
EVIDENCE_DB = ROOT / "review" / "H09" / "evidence" / "private_user_observations.sqlite3"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    before = sha256(DB)
    uri = DB.resolve().as_uri() + "?mode=ro&immutable=1"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in tables}
        columns = {name: [row[1] for row in connection.execute(f'PRAGMA table_info("{name}")')] for name in tables}
        synthetic_matches = {}
        for name in tables:
            if "product_id" in columns[name]:
                synthetic_matches[name] = connection.execute(f'SELECT COUNT(*) FROM "{name}" WHERE product_id = ?', ("P-H09-PRIVATE",)).fetchone()[0]
    finally:
        connection.close()
    after = sha256(DB)
    shutil.copyfile(DB, EVIDENCE_DB)
    evidence_copy_sha256 = sha256(EVIDENCE_DB)
    backups = sorted((DB.parent / "backups").glob("*.sqlite3")) if (DB.parent / "backups").is_dir() else []
    result = {
        "task_id": "CDH-H09-A13REV3-B15REV2-WINDOWS-E2E-001",
        "database": DB.relative_to(ROOT).as_posix(), "open_mode": "READ_ONLY_IMMUTABLE",
        "sha256_before": before, "sha256_after": after, "read_only_hash_unchanged": before == after,
        "bytes": DB.stat().st_size, "tables": tables, "row_counts": counts,
        "evidence_database_copy": EVIDENCE_DB.relative_to(ROOT).as_posix(),
        "evidence_database_copy_sha256": evidence_copy_sha256,
        "evidence_database_copy_matches": evidence_copy_sha256 == after,
        "h09_main_product_matches": synthetic_matches, "backup_count": len(backups),
        "backup_sha256": [{"name": path.name, "sha256": sha256(path)} for path in backups],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
