"""Serve the extracted B06 implementation with H02-only controlled fixtures."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server


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
 displayed_price_twd INTEGER,
 price_basis TEXT NOT NULL,
 minimum_purchase_quantity INTEGER,
 shipping_status TEXT NOT NULL,
 stock_status TEXT NOT NULL,
 is_synthetic INTEGER NOT NULL
);
"""


def rows(classification: str) -> list[tuple[object, ...]]:
    synthetic = classification == "synthetic"
    kind = "SYNTHETIC" if synthetic else "USER_ENTERED"
    flag = 1 if synthetic else 0
    prefix = "SYNTHETIC FIXTURE" if synthetic else "H02 CONTROLLED LOCAL COPY"
    return [
        (1, "h02-red-1", "2026-11-01T02:00:00Z", "h02-red-source-1", kind, f"{prefix}｜同名耳機", "H02-P-HS", "SKU-H02-RED", "SELLER-H02-A", 699, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", flag),
        (2, "h02-red-2", "2026-11-04T02:00:00Z", "h02-red-source-2", kind, f"{prefix}｜同名耳機", "H02-P-HS", "SKU-H02-RED", "SELLER-H02-A", 599, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", flag),
        (3, "h02-blue-1", "2026-11-02T03:00:00Z", "h02-blue-source-1", kind, f"{prefix}｜同名耳機", "H02-P-HS", "SKU-H02-BLUE", "SELLER-H02-B", 799, "UNIT_DISPLAYED", 1, "PAID", "IN_STOCK", flag),
        (4, "h02-blue-2", "2026-11-04T03:00:00Z", "h02-blue-source-2", kind, f"{prefix}｜同名耳機", "H02-P-HS", "SKU-H02-BLUE", "SELLER-H02-B", 749, "UNIT_DISPLAYED", 1, "PAID", "IN_STOCK", flag),
        (5, "h02-zero", "2026-11-04T04:00:00Z", "h02-zero-source", kind, f"{prefix}｜零元觀測", "H02-P-ZERO", "SKU-H02-ZERO", "SELLER-H02-C", 0, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", flag),
        (6, "h02-stale", "2026-10-20T04:00:00Z", "h02-stale-source", kind, f"{prefix}｜久未更新", "H02-P-STALE", "SKU-H02-STALE", "SELLER-H02-D", 888, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", flag),
        (7, "h02-null", "2026-11-04T05:00:00Z", "h02-null-source", kind, f"{prefix}｜沒有有效價格歷史", "H02-P-NULL", "SKU-H02-NULL", "SELLER-H02-E", None, "UNIT_DISPLAYED", 1, "UNKNOWN", "UNKNOWN", flag),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b06-root", required=True)
    parser.add_argument("--fixture-root", required=True)
    parser.add_argument("--classification", choices=("user", "synthetic"), required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    service = Path(args.b06_root).resolve() / "services" / "price_query"
    sys.path.insert(0, str(service))
    from price_query import PriceQueryApp, ReadonlyPriceRepository  # noqa: PLC0415
    from price_query.repository import SYNTHETIC_CLASSIFICATION  # noqa: PLC0415

    fixture_root = Path(args.fixture_root).resolve()
    fixture_root.mkdir(parents=True, exist_ok=True)
    database = fixture_root / "h02.sqlite3"
    if database.exists():
        parser.error("fixture database already exists")
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO observations VALUES(" + ",".join("?" for _ in range(15)) + ")", rows(args.classification))
        connection.commit()
    finally:
        connection.close()
    repository = ReadonlyPriceRepository(
        database,
        allowed_root=fixture_root,
        clock=lambda: datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc),
        **({"data_classification": SYNTHETIC_CLASSIFICATION} if args.classification == "synthetic" else {}),
    )
    print(json.dumps({"status": "READY", "classification": args.classification, "database": str(database)}), flush=True)
    with make_server("127.0.0.1", args.port, PriceQueryApp(repository)) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

