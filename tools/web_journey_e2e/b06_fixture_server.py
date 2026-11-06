"""Loopback-only B06 V2 synthetic fixture server for H01 acceptance probes."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = PROJECT_ROOT / "services" / "price_query"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from price_query import PriceQueryApp, ReadonlyPriceRepository  # noqa: E402
from price_query.repository import SYNTHETIC_CLASSIFICATION  # noqa: E402


SCHEMA = """
CREATE TABLE observations(
 observation_id INTEGER PRIMARY KEY,
 submission_id TEXT NOT NULL,
 observed_at_utc TEXT NOT NULL,
 source_id TEXT,
 source_kind TEXT NOT NULL,
 product_title TEXT NOT NULL,
 product_id TEXT,
 variant_id TEXT,
 seller_id TEXT,
 displayed_price_twd INTEGER NOT NULL,
 price_basis TEXT NOT NULL,
 minimum_purchase_quantity INTEGER,
 shipping_status TEXT NOT NULL,
 stock_status TEXT NOT NULL,
 is_synthetic INTEGER NOT NULL
);
"""


def build_fixture(database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        rows = [
            (1, "syn-h01-1", "2026-11-01T03:00:00Z", "h01-1", "SYNTHETIC", "SYNTHETIC H01 耳機", "SYN-P-1", "SKU-H01-BLK", "SYN-SELLER-A", 399, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (2, "syn-h01-2", "2026-11-04T03:00:00Z", "h01-2", "SYNTHETIC", "SYNTHETIC H01 耳機", "SYN-P-1", "SKU-H01-BLK", "SYN-SELLER-A", 299, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (3, "syn-h01-red", "2026-11-04T04:00:00Z", "h01-red", "SYNTHETIC", "SYNTHETIC 多規格商品", "SYN-MULTI", "SKU-H01-RED", "SYN-SELLER-B", 500, "CURRENT_ITEM_PRICE", 1, "PAID", "IN_STOCK", 1),
            (4, "syn-h01-blue", "2026-11-04T04:05:00Z", "h01-blue", "SYNTHETIC", "SYNTHETIC 多規格商品", "SYN-MULTI", "SKU-H01-BLUE", "SYN-SELLER-B", 520, "CURRENT_ITEM_PRICE", 1, "PAID", "IN_STOCK", 1),
            (5, "syn-h01-zero", "2026-11-04T05:00:00Z", "h01-zero", "SYNTHETIC", "SYNTHETIC 零元觀測", "SYN-ZERO", "SKU-H01-ZERO", "SYN-SELLER-C", 0, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (6, "syn-h01-stale", "2026-10-20T05:00:00Z", "h01-stale", "SYNTHETIC", "SYNTHETIC 久未更新", "SYN-STALE", "SKU-H01-STALE", "SYN-SELLER-D", 888, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
        ]
        connection.executemany(
            "INSERT INTO observations VALUES(" + ",".join("?" for _ in range(15)) + ")",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    fixture_root = Path(args.fixture_root).resolve()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    database = fixture_root / "h01_synthetic.sqlite3"
    if database.exists():
        parser.error("fixture database already exists")
    build_fixture(database)
    repository = ReadonlyPriceRepository(
        database,
        allowed_root=fixture_root,
        clock=lambda: datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc),
        data_classification=SYNTHETIC_CLASSIFICATION,
    )
    app = PriceQueryApp(repository)
    print(json.dumps({
        "status": "READY",
        "classification": "SYNTHETIC_DEMO_ONLY",
        "url": f"http://127.0.0.1:{args.port}",
        "database": str(database),
    }, ensure_ascii=False), flush=True)
    with make_server("127.0.0.1", args.port, app) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

