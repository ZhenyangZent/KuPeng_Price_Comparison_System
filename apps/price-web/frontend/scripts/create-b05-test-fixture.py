from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: create-b05-test-fixture.py <new-db-path>")
    target = Path(sys.argv[1]).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit(f"refusing to overwrite: {target}")
    connection = sqlite3.connect(target)
    try:
        connection.execute(
            """CREATE TABLE observations (
                observation_id INTEGER PRIMARY KEY,
                submission_id TEXT NOT NULL,
                observed_at_utc TEXT NOT NULL,
                source_id TEXT,
                source_kind TEXT NOT NULL,
                product_title TEXT NOT NULL,
                product_id TEXT,
                variant_id TEXT,
                seller_id TEXT,
                displayed_price_twd INTEGER,
                price_basis TEXT,
                minimum_purchase_quantity INTEGER,
                shipping_status TEXT NOT NULL,
                stock_status TEXT NOT NULL,
                is_synthetic INTEGER NOT NULL
            )"""
        )
        rows = [
            (1, "a06-submission-1", "2026-11-02T02:00:00Z", "a06-source-1", "USER_ENTERED", "SYNTHETIC TEST FIXTURE｜B05 外套", "PRODUCT-TEST", "SKU-XL-42", "SELLER-TEST", 699, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", 0),
            (2, "a06-submission-2", "2026-11-04T02:00:00Z", "a06-source-2", "USER_FILE", "SYNTHETIC TEST FIXTURE｜B05 外套", "PRODUCT-TEST", "SKU-XL-42", "SELLER-TEST", 599, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", 0),
        ]
        connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        connection.commit()
    finally:
        connection.close()
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
