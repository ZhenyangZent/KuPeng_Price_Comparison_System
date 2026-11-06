from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "review" / "H10_REV3" / "runtime" / "project" / "review" / "H10_REV3" / "private-data" / "private_user_observations.sqlite3"
OUT = ROOT / "review" / "H10_REV3" / "evidence" / "SQLITE_READONLY_EVIDENCE.json"
COPY = ROOT / "review" / "H10_REV3" / "evidence" / "private_user_observations.sqlite3"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    before = sha256(DB)
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        columns = [row[1] for row in connection.execute('PRAGMA table_info("observations")')]
        wanted = [name for name in ("submission_id", "product_id", "sku_id", "observed_at_utc", "taipei_date", "before_coupon_price_twd", "user_reported_coupon_price_twd", "confirmed_after_coupon_price_twd", "source_class", "visibility", "platform_verified") if name in columns]
        observations = [dict(row) for row in connection.execute(f'SELECT {", ".join(wanted)} FROM observations ORDER BY observed_at_utc')]
    finally:
        connection.close()
    after = sha256(DB)
    shutil.copyfile(DB, COPY)
    copy_hash = sha256(COPY)
    backups = sorted((DB.parent / "backups").glob("*.sqlite3")) if (DB.parent / "backups").is_dir() else []
    result = {
        "task_id": "CDH-H10-PRIVATE-HISTORY-REOPEN-E2E-001",
        "revision": "REV3",
        "database": DB.relative_to(ROOT).as_posix(),
        "open_mode": "READ_ONLY_IMMUTABLE",
        "sha256_before": before,
        "sha256_after": after,
        "read_only_hash_unchanged": before == after,
        "bytes": DB.stat().st_size,
        "tables": tables,
        "row_counts": counts,
        "observations": observations,
        "evidence_database_copy": COPY.relative_to(ROOT).as_posix(),
        "evidence_database_copy_sha256": copy_hash,
        "evidence_database_copy_matches": copy_hash == after,
        "backup_count": len(backups),
        "backup_sha256": [{"name": item.name, "sha256": sha256(item)} for item in backups],
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if before == after == copy_hash else 1)


if __name__ == "__main__":
    main()
