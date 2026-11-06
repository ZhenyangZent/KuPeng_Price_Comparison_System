from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
H13 = ROOT / "review" / "H13"
EVIDENCE = H13 / "evidence"
RESULT = EVIDENCE / "ACTUAL_H13_BROWSER_HTTP.json"
DB = H13 / "runtime" / "project" / "data" / "A17_private_history" / "private_user_observations.sqlite3"
COPY = EVIDENCE / "synthetic_A17_private_history.sqlite3"
OUT = EVIDENCE / "FAILURE_RECONCILIATION.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    browser = json.loads(RESULT.read_text(encoding="utf-8"))
    before = sha256(DB)
    connection = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    counts = {row[0]: connection.execute(f'SELECT count(*) FROM "{row[0]}"').fetchone()[0] for row in connection.execute("select name from sqlite_master where type='table' order by name")}
    rows = [dict(row) for row in connection.execute("""
        select product_id, sku_id, title, observed_at_utc, taipei_date,
               before_coupon_price_twd, user_reported_coupon_price_twd,
               confirmed_after_coupon_price_twd, source_class, visibility, platform_verified
          from observations order by product_id, observed_at_utc
    """)]
    connection.close()
    after = sha256(DB)
    shutil.copyfile(DB, COPY)
    network = browser["network"]
    csv_search_index = next(index for index, item in enumerate(network) if "products?q=PROD-B16-CSV" in item["url"])
    after_csv_search = network[csv_search_index:]
    stale_detail = next((item for item in after_csv_search if "/products/" in item["url"] and "products?" not in item["url"]), None)
    restart_index = next(index for index, item in enumerate(network) if index > 0 and item["url"].startswith("http://127.0.0.1:12341/?mode=synthetic") and item["method"] == "GET")
    after_restart = network[restart_index:]
    result = {
        "task_id": "CDH-H13-LOCAL-TRIAL-FIRST-USE-001",
        "status": "FAIL_H_TEST_STALE_RESULT_RACE",
        "browser_test_exit_code": browser["browser_test_exit_code"],
        "error": browser["error"],
        "database": DB.relative_to(ROOT).as_posix(),
        "database_sha256_before_readonly_inspection": before,
        "database_sha256_after_readonly_inspection": after,
        "readonly_inspection_hash_unchanged": before == after,
        "evidence_database_copy": COPY.relative_to(ROOT).as_posix(),
        "evidence_database_copy_sha256": sha256(COPY),
        "row_counts": counts,
        "observations": rows,
        "post_after_restart_count": sum(item["method"] == "POST" for item in after_restart),
        "csv_search_request": network[csv_search_index],
        "first_detail_request_after_csv_search": stale_detail,
        "stale_manual_detail_hash_observed": stale_detail is not None and stale_detail["url"].endswith("/1527ae16b8a0ec8e25aec2360b4b0c87fd4fead6cf183878aa000774c5370762"),
        "csv_detail_request_observed": any("/products/" in item["url"] and not item["url"].endswith("/1527ae16b8a0ec8e25aec2360b4b0c87fd4fead6cf183878aa000774c5370762") for item in after_csv_search),
        "interpretation": "The H search helper accepted the stale one-card manual result before the CSV query response updated the DOM, clicked the manual detail again, and timed out waiting for the CSV title. This is H harness evidence, not an A17 product defect determination.",
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    valid = (
        browser["status"] == "FAIL" and browser["browser_test_exit_code"] == 1
        and before == after == result["evidence_database_copy_sha256"]
        and counts.get("observations") == 5
        and result["post_after_restart_count"] == 0
        and result["stale_manual_detail_hash_observed"]
        and not result["csv_detail_request_observed"]
        and all(row["confirmed_after_coupon_price_twd"] is None and row["platform_verified"] == 0 for row in rows)
    )
    print(json.dumps({"status": "PASS" if valid else "FAIL", "observations": counts.get("observations"), "stale_manual_detail": result["stale_manual_detail_hash_observed"], "csv_detail_observed": result["csv_detail_request_observed"]}))
    raise SystemExit(0 if valid else 1)


if __name__ == "__main__":
    main()
