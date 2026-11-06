from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H12 = ROOT / "review" / "H12_REV2"
DB = H12 / "runtime" / "project" / "data" / "private_user_observations_b15" / "private_user_observations.sqlite3"
EVIDENCE = H12 / "evidence"
COPY = EVIDENCE / "synthetic_private_user_observations.sqlite3"
OUT = EVIDENCE / "SQLITE_READONLY_EVIDENCE.json"


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
    tables = [row[0] for row in connection.execute("select name from sqlite_master where type='table' order by name")]
    counts = {table: connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in tables}
    rows = [dict(row) for row in connection.execute("""
        select product_id, sku_id, title, observed_at_utc, taipei_date,
               before_coupon_price_twd, user_reported_coupon_price_twd,
               confirmed_after_coupon_price_twd, source_class, visibility,
               platform_verified
          from observations
         order by product_id, observed_at_utc
    """)]
    connection.close()
    after = sha256(DB)
    shutil.copyfile(DB, COPY)
    result = {
        "task_id": "CDH-H12-LOCAL-MVP-FIRST-USE-001",
        "revision": "REV2",
        "open_mode": "READ_ONLY_IMMUTABLE",
        "database": DB.relative_to(ROOT).as_posix(),
        "sha256_before": before,
        "sha256_after": after,
        "read_only_hash_unchanged": before == after,
        "bytes": DB.stat().st_size,
        "tables": tables,
        "row_counts": counts,
        "observations": rows,
        "evidence_database_copy": COPY.relative_to(ROOT).as_posix(),
        "evidence_database_copy_sha256": sha256(COPY),
    }
    result["evidence_database_copy_matches"] = result["evidence_database_copy_sha256"] == after
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        before == after
        and result["evidence_database_copy_matches"]
        and counts.get("observations") == 5
        and {row["product_id"] for row in rows} == {"PROD-B16-CSV", "PROD-B16-EXAMPLE", "PROD-H12-MANUAL"}
        and all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in rows)
        and all(row["source_class"] == "USER_ENTERED" and row["visibility"] == "PRIVATE_LOCAL" for row in rows)
    )
    print(json.dumps({"status": "PASS" if valid else "FAIL", "observations": counts.get("observations"), "sha256": after}))
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
