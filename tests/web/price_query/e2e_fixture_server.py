from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from wsgiref.simple_server import make_server


ROOT = Path(__file__).resolve().parents[3]
SERVICE = ROOT / "services" / "price_query"
if str(SERVICE) not in sys.path:
    sys.path.insert(0, str(SERVICE))

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


def build_synthetic_fixture(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        rows = [
            (1, "syn-e2e-1", "2026-11-03T03:00:00Z", "fixture-1", "SYNTHETIC", "SYNTHETIC E2E 耳機", "SYN-P-1", "SKU-E2E-BLK", "SYN-SELLER", 399, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
            (2, "syn-e2e-2", "2026-11-04T03:00:00Z", "fixture-2", "SYNTHETIC", "SYNTHETIC E2E 耳機", "SYN-P-1", "SKU-E2E-BLK", "SYN-SELLER", 299, "CURRENT_ITEM_PRICE", 1, "UNKNOWN", "UNKNOWN", 1),
        ]
        connection.executemany(
            "INSERT INTO observations VALUES(" + ",".join("?" for _ in range(15)) + ")",
            rows,
        )
        connection.commit()
    finally:
        connection.close()


def create_app(database: Path, fixture_root: Path) -> PriceQueryApp:
    repository = ReadonlyPriceRepository(
        database,
        allowed_root=fixture_root,
        clock=lambda: datetime(2026, 11, 5, 4, 0, tzinfo=timezone.utc),
        data_classification=SYNTHETIC_CLASSIFICATION,
    )
    return PriceQueryApp(repository)


def main() -> int:
    parser = argparse.ArgumentParser(description="Loopback-only B06 synthetic E2E API")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--frontend-port", type=int, default=4173)
    arguments = parser.parse_args()
    if not 1024 <= arguments.api_port <= 65535 or arguments.frontend_port != 4173:
        parser.error("API port must be 1024..65535 and the frozen frontend proxy port is 4173")
    temporary_root = Path(__file__).parent / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b06_e2e_", dir=temporary_root) as temporary_name:
        fixture_root = Path(temporary_name)
        database = fixture_root / "synthetic.sqlite3"
        build_synthetic_fixture(database)
        app = create_app(database, fixture_root)
        print(
            f"SYNTHETIC_DEMO_ONLY API http://127.0.0.1:{arguments.api_port}; "
            f"frontend http://127.0.0.1:{arguments.frontend_port} proxies /api/v2/*",
            flush=True,
        )
        with make_server("127.0.0.1", arguments.api_port, app) as server:
            server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
